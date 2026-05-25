"""检查 learning.db 中的用户和表"""
import sqlite3
conn = sqlite3.connect('data/learning.db')
c = conn.cursor()

c.execute('SELECT id, username, email FROM users')
users = c.fetchall()
print("=== Users ===")
for u in users:
    print(f"  id={u[0]}, user={u[1]}, email={u[2]}")

c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print(f"\n=== Tables ({len(tables)}) ===")
for t in tables:
    c.execute(f'SELECT COUNT(*) FROM [{t}]')
    count = c.fetchone()[0]
    print(f"  {t}: {count} rows")

conn.close()
