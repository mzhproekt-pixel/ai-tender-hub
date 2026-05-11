"""
Flask-приложение для работы с почтовой CRM.

Запуск:
    cd mail_crm
    MAILRU_LOGIN=info@casc.kz \
    MAILRU_APP_PASSWORD=... \
    ANTHROPIC_API_KEY=sk-ant-... \
    python -m web.app

Откроется на http://127.0.0.1:5000.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Делаем родительский каталог импортируемым (db.py живёт там)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

import db
from web import mailer, tasks

ACTIVE_DAYS = 14
FOLLOWUP_DAYS = 3

app = Flask(__name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"))
app.secret_key = "mail-crm-local-dev"  # локальное приложение, секрет не критичен


# --- Хелперы ---

def get_db():
    """Соединение на запрос."""
    return db.get_conn()


@app.template_filter("dt")
def fmt_dt(value: str | None) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return value


@app.template_filter("jl")
def fmt_jsonlist(value: str | None) -> list:
    return db.json_loads(value) or []


@app.template_filter("awaiting")
def fmt_awaiting(value: str | None) -> str:
    return {"me": "Жду — от меня", "them": "Жду — от них"}.get(value, "Закрыт / без ожидания")


@app.context_processor
def inject_globals():
    return {
        "task_state": tasks.all_status(),
        "ACTIVE_DAYS": ACTIVE_DAYS,
        "FOLLOWUP_DAYS": FOLLOWUP_DAYS,
    }


# --- Routes: dashboard ---

@app.route("/")
def dashboard():
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT
              (SELECT COUNT(*) FROM messages)                                       AS total_msgs,
              (SELECT COUNT(*) FROM messages WHERE analyzed_at IS NULL)             AS unanalyzed,
              (SELECT COUNT(*) FROM contacts)                                       AS total_contacts,
              (SELECT COUNT(*) FROM threads WHERE days_since_last <= ?)             AS active_threads,
              (SELECT COUNT(*) FROM threads WHERE awaiting_response_from='me')      AS my_turn,
              (SELECT COUNT(*) FROM threads
                  WHERE awaiting_response_from='them' AND days_since_last >= ?)     AS their_turn
        """, (ACTIVE_DAYS, FOLLOWUP_DAYS)).fetchone()

        top_contacts = conn.execute("""
            SELECT email, name, company, relation_type, sent_count, received_count,
                   (sent_count + received_count) AS total
            FROM contacts ORDER BY total DESC LIMIT 10
        """).fetchall()

        urgent = conn.execute("""
            SELECT t.id, t.subject_normalized, t.participants, t.days_since_last,
                   t.awaiting_response_from
            FROM threads t
            WHERE t.awaiting_response_from='me'
            ORDER BY t.days_since_last DESC LIMIT 10
        """).fetchall()
    finally:
        conn.close()

    return render_template("dashboard.html",
                           stats=row, top_contacts=top_contacts, urgent=urgent)


# --- Routes: contacts ---

@app.route("/contacts")
def contacts_list():
    q = (request.args.get("q") or "").strip()
    relation = (request.args.get("relation") or "").strip()

    where, params = [], []
    if q:
        where.append("(email LIKE ? OR name LIKE ? OR company LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    if relation:
        where.append("relation_type = ?")
        params.append(relation)

    sql = "SELECT * FROM contacts"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY last_seen DESC"

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        relations = [r["relation_type"] for r in conn.execute(
            "SELECT DISTINCT relation_type FROM contacts "
            "WHERE relation_type IS NOT NULL ORDER BY relation_type"
        )]
    finally:
        conn.close()

    return render_template("contacts.html",
                           contacts=rows, q=q,
                           relation=relation, relations=relations)


@app.route("/contacts/<int:contact_id>", methods=["GET", "POST"])
def contact_detail(contact_id: int):
    conn = get_db()
    try:
        if request.method == "POST":
            conn.execute("""
                UPDATE contacts
                SET relation_type = ?, notes = ?,
                    name = COALESCE(NULLIF(?, ''), name),
                    company = COALESCE(NULLIF(?, ''), company),
                    sphere = COALESCE(NULLIF(?, ''), sphere)
                WHERE id = ?
            """, (
                request.form.get("relation_type") or None,
                request.form.get("notes") or None,
                request.form.get("name", "").strip(),
                request.form.get("company", "").strip(),
                request.form.get("sphere", "").strip(),
                contact_id,
            ))
            flash("Контакт обновлён", "success")
            return redirect(url_for("contact_detail", contact_id=contact_id))

        c = conn.execute("SELECT * FROM contacts WHERE id = ?",
                         (contact_id,)).fetchone()
        if not c:
            abort(404)

        messages = conn.execute("""
            SELECT message_id, folder, date, subject, summary, category
            FROM messages
            WHERE from_email = ? OR to_emails LIKE ?
            ORDER BY date DESC LIMIT 100
        """, (c["email"], f'%"{c["email"]}"%')).fetchall()
    finally:
        conn.close()

    return render_template("contact_detail.html",
                           contact=c, messages=messages)


# --- Routes: threads ---

@app.route("/threads")
def threads_list():
    view = request.args.get("view", "active")  # active|me|them|frozen|all
    q = (request.args.get("q") or "").strip()

    where, params = [], []
    if view == "active":
        where.append("days_since_last <= ?")
        params.append(ACTIVE_DAYS)
    elif view == "me":
        where.append("awaiting_response_from = 'me'")
    elif view == "them":
        where.append("awaiting_response_from = 'them' AND days_since_last >= ?")
        params.append(FOLLOWUP_DAYS)
    elif view == "frozen":
        # Замороженные: давно тишина, но среди писем есть offer/negotiation
        where.append("""
            days_since_last > ?
            AND id IN (
                SELECT t.id FROM threads t
                JOIN thread_messages tm ON tm.thread_id = t.id
                JOIN messages m ON m.message_id = tm.message_id
                WHERE m.category IN ('offer', 'negotiation')
            )
        """)
        params.append(ACTIVE_DAYS)

    if q:
        where.append("(subject_normalized LIKE ? OR participants LIKE ?)")
        like = f"%{q.lower()}%"
        params += [like, like]

    sql = """SELECT t.*, ts.status AS state_status, ts.notes AS state_notes
             FROM threads t
             LEFT JOIN thread_state ts ON ts.root_message_id = t.root_message_id"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.days_since_last ASC, t.last_message_date DESC"

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    return render_template("threads.html",
                           threads=rows, view=view, q=q)


@app.route("/threads/<int:thread_id>")
def thread_detail(thread_id: int):
    conn = get_db()
    try:
        t = conn.execute("""
            SELECT t.*, ts.status AS state_status, ts.notes AS state_notes
            FROM threads t
            LEFT JOIN thread_state ts ON ts.root_message_id = t.root_message_id
            WHERE t.id = ?
        """, (thread_id,)).fetchone()
        if not t:
            abort(404)

        msgs = conn.execute("""
            SELECT m.*
            FROM messages m
            JOIN thread_messages tm ON tm.message_id = m.message_id
            WHERE tm.thread_id = ?
            ORDER BY m.date ASC
        """, (thread_id,)).fetchall()
    finally:
        conn.close()

    return render_template("thread_detail.html", thread=t, messages=msgs)


@app.route("/threads/<int:thread_id>/state", methods=["POST"])
def thread_state(thread_id: int):
    """Сохраняет заметки/статус треда (живёт в thread_state, переживает rebuild)."""
    conn = get_db()
    try:
        t = conn.execute(
            "SELECT root_message_id FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
        if not t or not t["root_message_id"]:
            abort(404)

        notes = (request.form.get("notes") or "").strip() or None
        status = (request.form.get("status") or "").strip() or None
        now = datetime.now(timezone.utc).isoformat()

        conn.execute("""
            INSERT INTO thread_state (root_message_id, notes, status, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(root_message_id) DO UPDATE SET
                notes = excluded.notes,
                status = excluded.status,
                updated_at = excluded.updated_at
        """, (t["root_message_id"], notes, status, now))
    finally:
        conn.close()

    flash("Заметки треда сохранены", "success")
    return redirect(url_for("thread_detail", thread_id=thread_id))


@app.route("/threads/<int:thread_id>/reply", methods=["POST"])
def thread_reply(thread_id: int):
    """Отправляет ответ через SMTP smtp.mail.ru и сохраняет письмо в БД."""
    conn = get_db()
    try:
        msgs = conn.execute("""
            SELECT m.* FROM messages m
            JOIN thread_messages tm ON tm.message_id = m.message_id
            WHERE tm.thread_id = ?
            ORDER BY m.date ASC
        """, (thread_id,)).fetchall()
    finally:
        conn.close()

    if not msgs:
        abort(404)
    last = msgs[-1]

    raw_to = (request.form.get("to") or "").strip()
    body = (request.form.get("body") or "").strip()
    subject = (request.form.get("subject") or "").strip()

    to_list = [a.strip() for a in raw_to.split(",") if a.strip()]
    if not to_list:
        flash("Не указан получатель", "danger")
        return redirect(url_for("thread_detail", thread_id=thread_id))
    if not body:
        flash("Пустое тело письма", "danger")
        return redirect(url_for("thread_detail", thread_id=thread_id))

    refs = db.json_loads(last["references_ids"]) or []
    if last["in_reply_to"] and last["in_reply_to"] not in refs:
        refs.append(last["in_reply_to"])

    try:
        meta = mailer.send_reply(
            to=to_list, subject=subject, body=body,
            in_reply_to=last["message_id"],
            references=refs,
        )
        mailer.record_sent(meta)
        flash("Письмо отправлено", "success")
    except mailer.MailerError as exc:
        flash(f"Ошибка отправки: {exc}", "danger")
    except Exception as exc:
        app.logger.exception("Неожиданная ошибка отправки: %s", exc)
        flash(f"Неожиданная ошибка: {exc}", "danger")

    return redirect(url_for("thread_detail", thread_id=thread_id))


# --- Routes: messages (просмотр одного письма во фрейме) ---

@app.route("/messages/<path:message_id>")
def message_detail(message_id: str):
    conn = get_db()
    try:
        m = conn.execute("SELECT * FROM messages WHERE message_id = ?",
                         (message_id,)).fetchone()
    finally:
        conn.close()
    if not m:
        abort(404)
    return render_template("message_detail.html", m=m)


# --- Routes: pipeline tasks ---

@app.route("/tasks")
def tasks_page():
    return render_template("tasks.html")


@app.route("/tasks/<name>/start", methods=["POST"])
def task_start(name: str):
    try:
        tasks.start(name)
        flash(f"Задача «{name}» запущена", "info")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(request.referrer or url_for("tasks_page"))


@app.route("/tasks/status.json")
def tasks_status_json():
    return jsonify(tasks.all_status())


def main() -> None:
    db.setup_logging()
    db.init_schema()
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
