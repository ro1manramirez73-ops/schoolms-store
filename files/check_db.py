import sqlite3
conn = sqlite3.connect("school.db")
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print("=== TABLES ===")
for t in tables:
    name = t[0]
    count = conn.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
    print("  " + name + ": " + str(count) + " rows")
    if count > 0:
        cols = [d[0] for d in conn.execute("SELECT * FROM " + name + " LIMIT 1").description]
        print("    cols: " + ", ".join(cols))
conn.close()
