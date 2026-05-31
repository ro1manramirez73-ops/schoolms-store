"""
Import active staff from Staff_tbl.csv into school.db teachers table.
Run: python import_staff.py
"""
import csv, sqlite3, re, os, sys
from datetime import datetime

DB = "school.db"
CSV_FILE = "Staff_tbl.csv"

MONTHS = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
          "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}

def clean(val):
    if not val:
        return None
    v = val.strip()
    if not v or v.upper() in ("N/A","NA","NONE","0","","NOT PROVIDED","UNKNOWN","INACTIVE"):
        return None
    return v

def parse_date(val):
    v = clean(val)
    if not v:
        return None
    m = re.match(r"(\d{1,2})[-/](\w{3})[-/](\d{2,4})$", v)
    if m:
        day, mon, yr = m.groups()
        mon_num = MONTHS.get(mon.lower())
        if not mon_num:
            return None
        yr, day = int(yr), int(day)
        if yr < 100:
            yr += 2000 if yr <= 30 else 1900
        try:
            return datetime(yr, mon_num, day).strftime("%Y-%m-%d")
        except:
            return None
    m2 = re.match(r"(\d{4})-(\d{2})-(\d{2})$", v)
    if m2:
        return v
    return None

def parse_salary(val):
    v = clean(val)
    if not v:
        return 0.0
    v = v.replace("$", "").replace(",", "").strip()
    try:
        return float(v)
    except:
        return 0.0

def build_address(row):
    parts = [clean(row.get("Address")), clean(row.get("City")), clean(row.get("State/Province"))]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None

if not os.path.exists(CSV_FILE):
    print(f"ERROR: {CSV_FILE} not found.")
    sys.exit(1)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")

with open(CSV_FILE, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print(f"CSV rows read: {len(rows)}")

inserted = updated = skipped = 0

for row in rows:
    # Only import active staff
    if (row.get("Active") or "").strip().upper() != "TRUE":
        skipped += 1
        continue

    raw_id     = (row.get("ID") or "").strip()
    last_name  = clean(row.get("Last Name"))  or "Unknown"
    first_name = clean(row.get("First Name")) or "Unknown"

    # Skip placeholder rows
    if first_name.upper() == "INACTIVE" or last_name.upper() == "INACTIVE":
        skipped += 1
        continue

    if not raw_id:
        skipped += 1
        continue

    teacher_id = raw_id
    dob        = parse_date(row.get("Staff_DOB"))
    email      = clean(row.get("E-mail Address"))
    phone      = clean(row.get("Mobile Phone")) or clean(row.get("Home Phone"))
    address    = build_address(row)
    job_title  = clean(row.get("Job Title"))
    salary     = parse_salary(row.get("Base_Salary"))
    status     = "Active"

    existing = conn.execute(
        "SELECT id FROM teachers WHERE teacher_id=?", (teacher_id,)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE teachers SET
                first_name=?, last_name=?, dob=?, email=?, phone=?, address=?,
                subject=?, qualification=?, salary=?, status=?
            WHERE teacher_id=?
        """, (first_name, last_name, dob, email, phone, address,
              job_title, job_title, salary, status, teacher_id))
        updated += 1
    else:
        conn.execute("""
            INSERT INTO teachers
                (teacher_id, first_name, last_name, dob, email, phone, address,
                 subject, qualification, salary, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (teacher_id, first_name, last_name, dob, email, phone, address,
              job_title, job_title, salary, status))
        inserted += 1

conn.commit()
conn.close()

print(f"\nDone.")
print(f"  Inserted : {inserted}")
print(f"  Updated  : {updated}")
print(f"  Skipped  : {skipped}")
print(f"  Total    : {inserted + updated + skipped}/{len(rows)}")
