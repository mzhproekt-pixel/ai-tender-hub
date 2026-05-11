"""
Отправка ответов через SMTP smtp.mail.ru.

Используется при ответе из веб-интерфейса. После отправки письмо
сохраняется в локальную таблицу messages с folder='sent', чтобы
сразу появилось в тредах. Дубль с серверной папкой «Отправленные»
не страшен — INSERT OR IGNORE по Message-ID отработает при следующем fetch.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import db

logger = logging.getLogger("mailer")

SMTP_HOST = "smtp.mail.ru"
SMTP_PORT = 465  # SSL
SENDER_NAME_DEFAULT = "ТОО CASC"


class MailerError(Exception):
    pass


def send_reply(*, to: list[str], subject: str, body: str,
               in_reply_to: str | None,
               references: list[str] | None) -> dict:
    """
    Отправляет письмо через SMTP_SSL и возвращает словарь с метаданными
    отправленного письма для записи в БД.
    """
    login = db.env("MAILRU_LOGIN", required=True)
    password = db.env("MAILRU_APP_PASSWORD", required=True)
    sender_name = db.env("MAILRU_SENDER_NAME", default=SENDER_NAME_DEFAULT)

    if not to:
        raise MailerError("Не указаны получатели")

    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, login))
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg_id = make_msgid(domain=login.split("@", 1)[-1] or "mail.ru")
    msg["Message-ID"] = msg_id

    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    refs = list(references or [])
    if in_reply_to and in_reply_to not in refs:
        refs.append(in_reply_to)
    if refs:
        msg["References"] = " ".join(refs)

    msg.set_content(body)

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=30) as s:
            s.login(login, password)
            s.send_message(msg)
    except smtplib.SMTPException as exc:
        logger.exception("SMTP-ошибка при отправке: %s", exc)
        raise MailerError(f"SMTP-ошибка: {exc}") from exc

    return {
        "message_id": msg_id,
        "in_reply_to": in_reply_to,
        "references": refs,
        "from_email": login,
        "to_emails": to,
        "subject": subject,
        "body_text": body,
        "date": datetime.now(timezone.utc).isoformat(),
    }


def record_sent(meta: dict) -> None:
    """Сохраняет отправленное письмо в локальную таблицу messages."""
    conn = db.get_conn()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO messages
            (message_id, in_reply_to, references_ids, folder, date,
             from_email, to_emails, subject, body_text, raw_size,
             summary, category, analyzed_at)
            VALUES (?, ?, ?, 'sent', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            meta["message_id"], meta["in_reply_to"],
            db.json_dumps(meta["references"]),
            meta["date"], meta["from_email"],
            db.json_dumps(meta["to_emails"]),
            meta["subject"], meta["body_text"], len(meta["body_text"] or ""),
            "Отправлено из веб-интерфейса", "followup",
            meta["date"],
        ))
        # Обновляем счётчики получателей
        for addr in meta["to_emails"]:
            db.upsert_contact(conn, addr, direction="sent",
                              date_iso=meta["date"])
    finally:
        conn.close()
