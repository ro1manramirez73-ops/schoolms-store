import sqlite3

conn = sqlite3.connect("payroll.db")
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("=== PAYROLL DATABASE ===")
for t in tables:
    count = conn.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
    print(f"{t[0]}: {count} rows")
conn.close()
