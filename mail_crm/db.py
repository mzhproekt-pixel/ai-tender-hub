"""
Общий модуль работы с SQLite-базой mail_crm.
Содержит подключение, инициализацию схемы и хелперы.
"""
import sqlite3
import json
import logging
import os
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "mail_crm.db"

logger = logging.getLogger(__name__)


# Схема БД (см. ТЗ)
SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT UNIQUE NOT NULL,
    name            TEXT,
    company         TEXT,
    sphere          TEXT,
    relation_type   TEXT,
    first_seen      TEXT,
    last_seen       TEXT,
    sent_count      INTEGER DEFAULT 0,
    received_count  INTEGER DEFAULT 0,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id         TEXT UNIQUE NOT NULL,
    in_reply_to        TEXT,
    references_ids     TEXT,
    folder             TEXT NOT NULL,
    date               TEXT,
    from_email         TEXT,
    to_emails          TEXT,
    subject            TEXT,
    body_text          TEXT,
    raw_size           INTEGER,
    summary            TEXT,
    category           TEXT,
    mentioned_projects TEXT,
    mentioned_amounts  TEXT,
    commitments        TEXT,
    analyzed_at        TEXT
);

CREATE TABLE IF NOT EXISTS threads (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    root_message_id          TEXT,
    subject_normalized       TEXT,
    participants             TEXT,
    first_message_date       TEXT,
    last_message_date        TEXT,
    message_count            INTEGER DEFAULT 0,
    last_direction           TEXT,
    awaiting_response_from   TEXT,
    days_since_last          INTEGER
);

CREATE TABLE IF NOT EXISTS thread_messages (
    thread_id  INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    PRIMARY KEY (thread_id, message_id),
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

-- Сохраняется между пересборками тредов: ключ — root_message_id (первое письмо)
CREATE TABLE IF NOT EXISTS thread_state (
    root_message_id TEXT PRIMARY KEY,
    notes           TEXT,
    status          TEXT,
    updated_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_message_id    ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_messages_in_reply_to   ON messages(in_reply_to);
CREATE INDEX IF NOT EXISTS idx_messages_analyzed_at   ON messages(analyzed_at);
CREATE INDEX IF NOT EXISTS idx_messages_from          ON messages(from_email);
CREATE INDEX IF NOT EXISTS idx_messages_date          ON messages(date);
CREATE INDEX IF NOT EXISTS idx_contacts_email         ON contacts(email);
CREATE INDEX IF NOT EXISTS idx_threads_root           ON threads(root_message_id);
"""


def migrate_schema() -> None:
    """
    Лёгкая миграция для существующих БД: добавляет недостающие колонки.
    Безопасно для свежих БД — там всё уже есть из CREATE TABLE.
    """
    with get_conn() as conn:
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(contacts)")}
        if "notes" not in existing:
            conn.execute("ALTER TABLE contacts ADD COLUMN notes TEXT")

        existing = {r["name"] for r in conn.execute("PRAGMA table_info(threads)")}
        if "root_message_id" not in existing:
            conn.execute("ALTER TABLE threads ADD COLUMN root_message_id TEXT")


def get_conn() -> sqlite3.Connection:
    """Возвращает соединение с включёнными внешними ключами и row_factory."""
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema() -> None:
    """Создаёт таблицы, если их нет. Идемпотентно."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    migrate_schema()
    logger.info("Схема БД инициализирована: %s", DB_PATH)


def setup_logging() -> None:
    """Логирование: INFO в stdout, ERROR в errors.log."""
    log_dir = Path(__file__).parent
    err_handler = logging.FileHandler(log_dir / "errors.log", encoding="utf-8")
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    stdout_handler = logging.StreamHandler()
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    ))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Очищаем старые хендлеры, чтобы повторный запуск не дублировал вывод
    root.handlers.clear()
    root.addHandler(stdout_handler)
    root.addHandler(err_handler)


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    """Безопасное чтение переменной окружения."""
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Не задана обязательная переменная окружения: {name}")
    return val


def upsert_contact(conn: sqlite3.Connection, email: str, *, direction: str,
                   date_iso: str, name: str | None = None,
                   company: str | None = None, sphere: str | None = None) -> None:
    """
    UPSERT контакта. direction: 'sent' (мы → этот email) или 'received' (он → нам).
    Имя/компания/сфера обновляются только если в БД они пустые.
    """
    email = (email or "").strip().lower()
    if not email:
        return

    row = conn.execute("SELECT id, name, company, sphere, first_seen, last_seen "
                       "FROM contacts WHERE email = ?", (email,)).fetchone()

    if row is None:
        conn.execute("""
            INSERT INTO contacts (email, name, company, sphere,
                                  first_seen, last_seen,
                                  sent_count, received_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            email, name, company, sphere,
            date_iso, date_iso,
            1 if direction == "sent" else 0,
            1 if direction == "received" else 0,
        ))
        return

    # Обновляем поля, если они пустые
    new_name = row["name"] or name
    new_company = row["company"] or company
    new_sphere = row["sphere"] or sphere

    first_seen = min(row["first_seen"], date_iso) if row["first_seen"] else date_iso
    last_seen = max(row["last_seen"], date_iso) if row["last_seen"] else date_iso

    if direction == "sent":
        conn.execute("""
            UPDATE contacts
            SET name=?, company=?, sphere=?,
                first_seen=?, last_seen=?,
                sent_count = sent_count + 1
            WHERE id=?
        """, (new_name, new_company, new_sphere,
              first_seen, last_seen, row["id"]))
    else:
        conn.execute("""
            UPDATE contacts
            SET name=?, company=?, sphere=?,
                first_seen=?, last_seen=?,
                received_count = received_count + 1
            WHERE id=?
        """, (new_name, new_company, new_sphere,
              first_seen, last_seen, row["id"]))


def json_dumps(value) -> str:
    """JSON-сериализация для хранения в TEXT-полях."""
    return json.dumps(value, ensure_ascii=False)


def json_loads(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None
