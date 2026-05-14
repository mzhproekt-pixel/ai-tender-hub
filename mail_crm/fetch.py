"""
fetch.py — выгрузка писем с Mail.ru (IMAP) в локальную SQLite-базу.

Запуск:
    MAILRU_LOGIN=info@casc.kz \
    MAILRU_APP_PASSWORD=xxxxxxxxxxxxxxxx \
    START_DATE=2026-04-13 \
    python fetch.py
"""
from __future__ import annotations

import email
import imaplib
import logging
import re
import ssl
import sys
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime

from bs4 import BeautifulSoup

import db

logger = logging.getLogger("fetch")

IMAP_HOST = "imap.mail.ru"
IMAP_PORT = 993
PROGRESS_EVERY = 50


def decode_value(value: str | None) -> str:
    """Декодирует MIME-кодированные заголовки в обычную строку."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def normalize_addresses(raw: str | None) -> list[str]:
    """Парсит список адресов из заголовка To/Cc."""
    if not raw:
        return []
    decoded = decode_value(raw)
    return [addr.lower() for _, addr in getaddresses([decoded]) if addr]


def extract_body(msg: Message) -> str:
    """
    Извлекает текстовое тело письма.
    Приоритет: text/plain → text/html (через BeautifulSoup).
    """
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            if ctype == "text/plain":
                plain_parts.append(_decode_payload(part))
            elif ctype == "text/html":
                html_parts.append(_decode_payload(part))
    else:
        ctype = msg.get_content_type()
        if ctype == "text/plain":
            plain_parts.append(_decode_payload(msg))
        elif ctype == "text/html":
            html_parts.append(_decode_payload(msg))

    if plain_parts:
        return "\n".join(p for p in plain_parts if p).strip()
    if html_parts:
        soup = BeautifulSoup("\n".join(html_parts), "html.parser")
        return soup.get_text("\n", strip=True)
    return ""


def _decode_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return payload.decode("utf-8", errors="replace")


def parse_references(value: str | None) -> list[str]:
    """References — список Message-ID, разделённых пробелами/переводами строк."""
    if not value:
        return []
    return [r for r in re.findall(r"<[^>]+>", value)]


def parse_date(raw: str | None) -> str | None:
    """Возвращает ISO-строку в UTC, либо None."""
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def find_sent_folder(imap: imaplib.IMAP4_SSL) -> str:
    """
    Находит имя папки «Отправленные» через LIST.
    Mail.ru использует флаг \\Sent или имя в IMAP UTF-7.
    """
    typ, data = imap.list()
    if typ != "OK":
        raise RuntimeError("Не удалось получить список папок IMAP")

    candidates: list[str] = []
    for row in data:
        if row is None:
            continue
        line = row.decode(errors="replace") if isinstance(row, bytes) else row
        # формат: (\HasNoChildren \Sent) "/" "&BB4EQgQ_BEAEMAQ2BDsENQQ9BDoENQQ1-"
        m = re.match(r"\((?P<flags>[^)]*)\)\s+\"(?P<delim>[^\"]*)\"\s+\"?(?P<name>.+?)\"?$",
                     line.strip())
        if not m:
            continue
        flags = m.group("flags").lower()
        name = m.group("name")
        if "\\sent" in flags:
            return name
        # запасной вариант — по имени
        if any(token in name.lower() for token in ("sent", "отправ")):
            candidates.append(name)

    if candidates:
        return candidates[0]
    # fallback — стандартное имя Mail.ru
    return "Sent"


def imap_date(start_date: str) -> str:
    """Преобразует YYYY-MM-DD или DD.MM.YYYY в формат IMAP SINCE: DD-Mon-YYYY."""
    # Попытка парсить оба формата: YYYY-MM-DD и DD.MM.YYYY
    for fmt in ["%Y-%m-%d", "%d.%m.%Y"]:
        try:
            dt = datetime.strptime(start_date, fmt)
            return dt.strftime("%d-%b-%Y")
        except ValueError:
            continue
    # Если оба формата не сработали, выбросить ошибку
    raise ValueError(f"Неподдерживаемый формат даты: {start_date} (используй YYYY-MM-DD или DD.MM.YYYY)")


def fetch_folder(imap: imaplib.IMAP4_SSL, folder: str,
                 since: str, direction: str) -> int:
    """
    Загружает письма из папки folder начиная с даты since (IMAP-формат).
    direction: 'sent' или 'inbox' — пишется в messages.folder.
    Возвращает количество вставленных сообщений.
    """
    typ, _ = imap.select(folder, readonly=True)
    if typ != "OK":
        logger.error("Не удалось открыть папку %s", folder)
        return 0

    typ, data = imap.search(None, f'(SINCE "{since}")')
    if typ != "OK":
        logger.error("IMAP SEARCH вернул не-OK для %s", folder)
        return 0

    ids = data[0].split() if data and data[0] else []
    logger.info("Папка %s: найдено %d писем с %s", folder, len(ids), since)

    inserted = 0
    conn = db.get_conn()
    try:
        for idx, num in enumerate(ids, start=1):
            try:
                inserted += _fetch_one(imap, num, direction, conn)
            except Exception as exc:
                logger.exception("Ошибка при обработке письма uid=%s в %s: %s",
                                 num, folder, exc)

            if idx % PROGRESS_EVERY == 0:
                print(f"  [{folder}] {idx}/{len(ids)} обработано, "
                      f"добавлено новых: {inserted}", flush=True)
    finally:
        conn.close()

    return inserted


def _fetch_one(imap: imaplib.IMAP4_SSL, num: bytes,
               direction: str, conn) -> int:
    typ, msg_data = imap.fetch(num, "(RFC822)")
    if typ != "OK" or not msg_data:
        logger.warning("FETCH вернул не-OK для uid=%s", num)
        return 0

    raw_bytes: bytes | None = None
    for item in msg_data:
        if isinstance(item, tuple) and len(item) >= 2:
            raw_bytes = item[1]
            break
    if raw_bytes is None:
        return 0

    msg = email.message_from_bytes(raw_bytes)
    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        # Mail.ru обычно проставляет Message-ID, но на всякий случай
        # синтезируем по uid+folder, чтобы не терять письма
        message_id = f"<no-id-{direction}-{num.decode()}@local>"

    subject = decode_value(msg.get("Subject"))
    from_addrs = normalize_addresses(msg.get("From"))
    from_email = from_addrs[0] if from_addrs else ""

    to_addrs = (normalize_addresses(msg.get("To"))
                + normalize_addresses(msg.get("Cc")))

    date_iso = parse_date(msg.get("Date"))
    in_reply_to = (msg.get("In-Reply-To") or "").strip() or None
    references = parse_references(msg.get("References"))

    body_text = extract_body(msg)

    cur = conn.execute("""
        INSERT OR IGNORE INTO messages
        (message_id, in_reply_to, references_ids, folder, date,
         from_email, to_emails, subject, body_text, raw_size)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        message_id, in_reply_to, db.json_dumps(references),
        direction, date_iso, from_email,
        db.json_dumps(to_addrs), subject, body_text, len(raw_bytes),
    ))
    return cur.rowcount or 0


def main() -> int:
    db.setup_logging()
    db.init_schema()

    login = db.env("MAILRU_LOGIN", required=True)
    password = db.env("MAILRU_APP_PASSWORD", required=True)
    start_date = db.env("START_DATE", default="2026-04-13")

    # Pre-flight: ловим незаполненный плейсхолдер до похода в сеть.
    # Подстрока "замените" покрывает шаблон из .env.example.
    if not password or "замените" in password.lower():
        logger.error(
            "MAILRU_APP_PASSWORD не задан или содержит плейсхолдер из .env. "
            "Откройте /settings и впишите настоящий пароль приложения Mail.ru "
            "(https://account.mail.ru/user/2-step-auth/passwords). "
            "Пайплайн не запустится, пока значение не будет заменено."
        )
        return 3
    if not login or "замените" in login.lower():
        logger.error("MAILRU_LOGIN не задан или содержит плейсхолдер. Откройте /settings.")
        return 3

    logger.info("Подключаемся к %s:%d как %s", IMAP_HOST, IMAP_PORT, login)
    ctx = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx)
    try:
        imap.login(login, password)
    except imaplib.IMAP4.error as exc:
        logger.error("Ошибка авторизации IMAP: %s", exc)
        return 2

    try:
        since = imap_date(start_date)
        logger.info("Фильтр: SINCE %s", since)

        sent_folder = find_sent_folder(imap)
        logger.info("Папка отправленных: %s", sent_folder)

        total = 0
        total += fetch_folder(imap, "INBOX", since, "inbox")
        total += fetch_folder(imap, sent_folder, since, "sent")
        logger.info("Готово. Всего новых писем в БД: %d", total)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
