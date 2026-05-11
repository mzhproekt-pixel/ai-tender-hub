"""
analyze.py — обогащение писем через Claude API.

Для каждого письма с analyzed_at IS NULL вызывает claude-opus-4-7,
парсит JSON-ответ, сохраняет в messages и обновляет contacts.

Запуск:
    ANTHROPIC_API_KEY=sk-ant-... \
    MAILRU_LOGIN=info@casc.kz \
    python analyze.py
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from datetime import datetime, timezone

from anthropic import Anthropic

import db

logger = logging.getLogger("analyze")

MODEL = "claude-opus-4-7"
MAX_TOKENS = 1024
RATE_LIMIT_SEC = 0.5
BODY_LIMIT = 8000

SYSTEM_PROMPT = """Ты — аналитик деловой переписки. На вход получаешь письмо.
Верни СТРОГО JSON без markdown-обёрток:
{
  "summary": "1-2 предложения по сути письма",
  "category": "offer|negotiation|documents|followup|info|spam|other",
  "contact_name": "имя отправителя из подписи или null",
  "contact_company": "компания из подписи/домена или null",
  "contact_sphere": "сфера деятельности одним словом или null",
  "mentioned_projects": ["проект1", "проект2"],
  "mentioned_amounts": ["100000 руб", "$5000"],
  "commitments": ["я обещал прислать договор до пятницы"]
}
Все поля кроме summary и category могут быть пустыми массивами или null.
Отвечай на русском."""


def build_user_message(row) -> str:
    """Собирает текст для модели из полей письма."""
    to_emails = db.json_loads(row["to_emails"]) or []
    body = (row["body_text"] or "")[:BODY_LIMIT]
    return (
        f"From: {row['from_email']}\n"
        f"To: {', '.join(to_emails)}\n"
        f"Date: {row['date']}\n"
        f"Subject: {row['subject']}\n\n"
        f"{body}"
    )


def extract_json(text: str) -> dict:
    """
    Достаёт JSON из ответа модели. Сначала пробуем чистый json.loads,
    затем — поиск фигурных скобок (на случай если модель обернула в текст).
    """
    text = text.strip()
    # Срезаем markdown-fence на всякий случай
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Запасной вариант — первый блок {...}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError("Не удалось распарсить JSON в ответе модели")


def call_claude(client: Anthropic, content: str) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    text_parts = [
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    raw = "\n".join(text_parts).strip()
    return extract_json(raw)


def update_contacts_for_message(conn, row, analysis: dict,
                                 my_email: str) -> set[str]:
    """
    Обновляет contacts по результатам анализа письма.
    Для inbox — обогащаем from_email; для sent — каждый to_email.
    Возвращает множество email-ов, которых раньше не было в БД (для подсчёта новых).
    """
    folder = row["folder"]
    date_iso = row["date"] or datetime.now(timezone.utc).isoformat()
    name = (analysis.get("contact_name") or "").strip() or None
    company = (analysis.get("contact_company") or "").strip() or None
    sphere = (analysis.get("contact_sphere") or "").strip() or None

    new_emails: set[str] = set()

    def ensure_new(email_addr: str) -> None:
        existing = conn.execute(
            "SELECT 1 FROM contacts WHERE email = ?", (email_addr,)
        ).fetchone()
        if not existing:
            new_emails.add(email_addr)

    if folder == "inbox":
        addr = (row["from_email"] or "").lower()
        if addr and addr != my_email:
            ensure_new(addr)
            db.upsert_contact(conn, addr, direction="received",
                              date_iso=date_iso, name=name,
                              company=company, sphere=sphere)
    else:  # sent
        to_emails = db.json_loads(row["to_emails"]) or []
        for raw_addr in to_emails:
            addr = raw_addr.lower()
            if not addr or addr == my_email:
                continue
            ensure_new(addr)
            # При исходящем письме имя/компанию получателя из подписи не берём —
            # подпись отправителя в данном случае наша. Передаём только email.
            db.upsert_contact(conn, addr, direction="sent",
                              date_iso=date_iso)

    return new_emails


def save_analysis(conn, message_id: str, analysis: dict) -> None:
    """Записывает результат анализа в строку messages."""
    conn.execute("""
        UPDATE messages SET
            summary = ?,
            category = ?,
            mentioned_projects = ?,
            mentioned_amounts = ?,
            commitments = ?,
            analyzed_at = ?
        WHERE message_id = ?
    """, (
        analysis.get("summary"),
        analysis.get("category"),
        db.json_dumps(analysis.get("mentioned_projects") or []),
        db.json_dumps(analysis.get("mentioned_amounts") or []),
        db.json_dumps(analysis.get("commitments") or []),
        datetime.now(timezone.utc).isoformat(),
        message_id,
    ))


def main() -> int:
    db.setup_logging()
    db.init_schema()

    api_key = db.env("ANTHROPIC_API_KEY", required=True)
    my_email = (db.env("MAILRU_LOGIN", required=True) or "").lower()

    client = Anthropic(api_key=api_key)
    conn = db.get_conn()

    pending = conn.execute("""
        SELECT message_id, in_reply_to, folder, date, from_email,
               to_emails, subject, body_text
        FROM messages
        WHERE analyzed_at IS NULL
        ORDER BY date ASC
    """).fetchall()

    logger.info("К обработке: %d писем", len(pending))
    if not pending:
        return 0

    processed = 0
    failed = 0
    all_new_contacts: set[str] = set()

    for row in pending:
        try:
            user_text = build_user_message(row)
            analysis = call_claude(client, user_text)

            # Транзакция на письмо: и анализ, и контакты — атомарно
            conn.execute("BEGIN")
            try:
                new_contacts = update_contacts_for_message(
                    conn, row, analysis, my_email
                )
                save_analysis(conn, row["message_id"], analysis)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            all_new_contacts.update(new_contacts)
            processed += 1

            if processed % 10 == 0:
                logger.info("Обработано: %d / %d", processed, len(pending))
        except Exception as exc:
            failed += 1
            logger.exception("Ошибка при анализе message_id=%s: %s",
                             row["message_id"], exc)
        finally:
            time.sleep(RATE_LIMIT_SEC)

    conn.close()
    logger.info("Готово. Обработано писем: %d, ошибок: %d, новых контактов: %d",
                processed, failed, len(all_new_contacts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
