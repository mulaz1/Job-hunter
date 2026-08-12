import sqlite3
from src.config import load_config
cfg = load_config()
conn = sqlite3.connect(cfg.db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute('SELECT company, title, notified, first_seen_at, updated_at FROM jobs')
rows = cursor.fetchall()
print(f'Total jobs in DB: {len(rows)}')
unnotified = [r for r in rows if r['notified'] == 0]
print(f'Unnotified jobs: {len(unnotified)}')
for r in rows[:15]:
    print(f"{r['company']}: {r['title']} (notified={r['notified']})")
