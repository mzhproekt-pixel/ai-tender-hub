"""
match.py — построение тредов и аналитики.

1. Объединяет письма в треды по графу in_reply_to / references.
2. Письма без связей группирует по нормализованной теме + участникам.
3. Считает направление, awaiting_response_from, days_since_last.
4. Обновляет relation_type у контактов на основе категории большинства писем.
"""
from __future__ import annotations

import logging
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import db

logger = logging.getLogger("match")

# Регэксп префиксов темы: Re:, Fwd:, Fw:, Отв:, Пересл:
SUBJECT_PREFIX_RE = re.compile(
    r"^\s*(?:re|fwd|fw|отв|пересл)\s*\[?\d*\]?\s*:\s*",
    re.IGNORECASE,
)

# Порог "закрытого" треда — короткое благодарственное письмо
CLOSING_PHRASES = ("спасибо", "благодар", "thanks", "thank you")
CLOSING_LEN_LIMIT = 50

ACTIVE_DAYS = 14
FOLLOWUP_DAYS = 3


def normalize_subject(subject: str | None) -> str:
    """Убирает Re:/Fwd:/пробелы, приводит к lowercase."""
    if not subject:
        return ""
    prev = None
    cur = subject.strip()
    # повторно срезаем префиксы (Re: Re: Fwd:)
    while prev != cur:
        prev = cur
        cur = SUBJECT_PREFIX_RE.sub("", cur, count=1).strip()
    return re.sub(r"\s+", " ", cur).lower()


def load_messages(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT message_id, in_reply_to, references_ids, folder, date,
               from_email, to_emails, subject, body_text, category
        FROM messages
        ORDER BY date ASC
    """).fetchall()
    return [dict(r) for r in rows]


class UnionFind:
    """Стандартный union-find: используем для слияния тредов по графу ссылок."""
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def build_threads(messages: list[dict]) -> dict[str, list[dict]]:
    """
    Возвращает словарь thread_key → список сообщений.
    Сначала объединяем по in_reply_to/references; остатки — по теме+участникам.
    """
    uf = UnionFind()
    known_ids = {m["message_id"] for m in messages}

    for m in messages:
        mid = m["message_id"]
        uf.find(mid)  # регистрируем
        if m["in_reply_to"] and m["in_reply_to"] in known_ids:
            uf.union(mid, m["in_reply_to"])
        for ref in (db.json_loads(m["references_ids"]) or []):
            if ref in known_ids:
                uf.union(mid, ref)

    # Сначала собираем кластеры по графу ссылок
    clusters: dict[str, list[dict]] = defaultdict(list)
    for m in messages:
        root = uf.find(m["message_id"])
        clusters[root].append(m)

    # Затем досклеиваем "одинокие" кластеры по теме+участникам.
    # Делаем это в два прохода: считаем сигнатуру каждого кластера и
    # объединяем те, у которых сигнатура совпадает.
    sig_to_root: dict[tuple, str] = {}
    extra_unions: list[tuple[str, str]] = []
    for root, msgs in clusters.items():
        # сигнатура — нормализованная тема + множество участников
        subj = normalize_subject(msgs[0]["subject"])
        if not subj:
            continue
        participants = set()
        for msg in msgs:
            if msg["from_email"]:
                participants.add(msg["from_email"].lower())
            for t in (db.json_loads(msg["to_emails"]) or []):
                participants.add(t.lower())
        sig = (subj, frozenset(participants))
        if sig in sig_to_root:
            extra_unions.append((root, sig_to_root[sig]))
        else:
            sig_to_root[sig] = root

    for a, b in extra_unions:
        uf.union(a, b)

    # Финальная сборка
    final: dict[str, list[dict]] = defaultdict(list)
    for m in messages:
        root = uf.find(m["message_id"])
        final[root].append(m)

    for root in final:
        final[root].sort(key=lambda x: x["date"] or "")
    return final


def is_closing_message(body: str | None) -> bool:
    """Короткое благодарственное письмо считаем сигналом закрытия треда."""
    if not body:
        return False
    snippet = body.strip()
    if len(snippet) > CLOSING_LEN_LIMIT:
        return False
    low = snippet.lower()
    return any(phrase in low for phrase in CLOSING_PHRASES)


def days_between(date_iso: str | None) -> int | None:
    if not date_iso:
        return None
    try:
        dt = datetime.fromisoformat(date_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return max(delta.days, 0)
    except ValueError:
        return None


def upsert_threads(conn, threads: dict[str, list[dict]]) -> None:
    """Полностью переписываем таблицу threads — это аналитика-снимок."""
    conn.execute("DELETE FROM thread_messages")
    conn.execute("DELETE FROM threads")

    for msgs in threads.values():
        if not msgs:
            continue
        first = msgs[0]
        last = msgs[-1]

        participants: set[str] = set()
        for m in msgs:
            if m["from_email"]:
                participants.add(m["from_email"].lower())
            for t in (db.json_loads(m["to_emails"]) or []):
                participants.add(t.lower())

        last_direction = "out" if last["folder"] == "sent" else "in"

        # awaiting_response_from
        if is_closing_message(last["body_text"]):
            awaiting = None
        elif last_direction == "out":
            awaiting = "them"
        else:
            awaiting = "me"

        days_since = days_between(last["date"])

        cur = conn.execute("""
            INSERT INTO threads
            (subject_normalized, participants, first_message_date,
             last_message_date, message_count, last_direction,
             awaiting_response_from, days_since_last)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            normalize_subject(first["subject"]),
            db.json_dumps(sorted(participants)),
            first["date"],
            last["date"],
            len(msgs),
            last_direction,
            awaiting,
            days_since,
        ))
        thread_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO thread_messages (thread_id, message_id) VALUES (?, ?)",
            [(thread_id, m["message_id"]) for m in msgs],
        )


def update_relation_types(conn) -> None:
    """
    Простая эвристика relation_type по преобладающей категории писем контакта:

      - большинство 'offer' или 'negotiation' → 'lead'
        (если есть и documents — повышаем до 'client')
      - большинство 'documents'              → 'partner'
                                               (или 'client', если был offer/negotiation)
      - иначе                                → 'contact'

    Контакт = тот, с кем мы переписываемся (исходящие to_emails и входящие from_email).
    """
    # Соберём все письма с категориями
    rows = conn.execute("""
        SELECT folder, from_email, to_emails, category
        FROM messages
        WHERE category IS NOT NULL
    """).fetchall()

    # email → Counter(category)
    per_contact: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r["folder"] == "inbox":
            email_addr = (r["from_email"] or "").lower()
            if email_addr:
                per_contact[email_addr][r["category"]] += 1
        else:
            for t in (db.json_loads(r["to_emails"]) or []):
                per_contact[t.lower()][r["category"]] += 1

    for email_addr, counter in per_contact.items():
        categories = set(counter.keys())
        most_common, _ = counter.most_common(1)[0]

        has_deal = bool(categories & {"offer", "negotiation"})
        has_docs = "documents" in categories

        if most_common in ("offer", "negotiation"):
            relation = "client" if has_docs else "lead"
        elif most_common == "documents":
            relation = "client" if has_deal else "partner"
        elif most_common == "spam":
            relation = "spam"
        else:
            relation = "contact"

        conn.execute(
            "UPDATE contacts SET relation_type = ? WHERE email = ?",
            (relation, email_addr),
        )


def main() -> int:
    db.setup_logging()
    db.init_schema()

    conn = db.get_conn()
    try:
        messages = load_messages(conn)
        logger.info("Загружено писем: %d", len(messages))

        threads = build_threads(messages)
        logger.info("Построено тредов: %d", len(threads))

        conn.execute("BEGIN")
        try:
            upsert_threads(conn, threads)
            update_relation_types(conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        # Сводка
        stats = conn.execute("""
            SELECT
              SUM(CASE WHEN days_since_last <= ? THEN 1 ELSE 0 END) AS active,
              SUM(CASE WHEN awaiting_response_from='me'   THEN 1 ELSE 0 END) AS my_turn,
              SUM(CASE WHEN awaiting_response_from='them' THEN 1 ELSE 0 END) AS their_turn
            FROM threads
        """, (ACTIVE_DAYS,)).fetchone()
        logger.info("Активных тредов (<= %d дн.): %s; жду ответа от меня: %s; "
                    "жду от них: %s",
                    ACTIVE_DAYS, stats["active"], stats["my_turn"], stats["their_turn"])
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
