import sqlite3
conn = sqlite3.connect("payroll.db")
conn.row_factory = sqlite3.Row

print("=== Payroll employees (id field) ===")
emps = conn.execute("SELECT name, id FROM employees ORDER BY name").fetchall()
for e in emps:
    print(f"  {e['name']:<25} id={e['id']!r}")

print("\n=== Loan employees (staff_id field, distinct) ===")
loans = conn.execute("SELECT DISTINCT employee_name, staff_id FROM loans ORDER BY employee_name").fetchall()
for l in loans:
    print(f"  {l['employee_name']:<30} staff_id={l['staff_id']!r}")

print("\n=== Matches ===")
emp_ids = {str(e["id"]).split(".")[0]: e["name"] for e in emps}
for l in loans:
    sid = str(l["staff_id"]).split(".")[0]
    match = emp_ids.get(sid, "NO MATCH")
    print(f"  {l['employee_name']:<30} -> {match}")

conn.close()
