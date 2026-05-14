import sqlite3

conn = sqlite3.connect('mail_crm.db')
cursor = conn.cursor()

# Получить все таблицы
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()

print("Таблицы в БД:")
for table in tables:
    table_name = table[0]
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    print(f"  - {table_name}: {count} записей")

# Если есть письма
cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='email'")
if cursor.fetchone()[0] > 0:
    cursor.execute("SELECT subject, sender_email, received_date FROM email LIMIT 5")
    print("\nПримеры писем:")
    for row in cursor.fetchall():
        print(f"  {row[0][:50]} от {row[1]} ({row[2]})")

conn.close()
