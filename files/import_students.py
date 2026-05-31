"""
Import students from Datos_Student.csv into school.db
Run: python import_students.py
"""
import csv, sqlite3, re, os, sys
from datetime import datetime

DB = "school.db"
CSV_FILE = "Datos_Student.csv"

MONTHS = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
          "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}

def clean(val):
    """Return None for blank/N/A variants, else stripped value."""
    if not val:
        return None
    v = val.strip()
    if not v or v.upper() in ("N/A", "NA", "N?A", "N/S", "NONE", "0", "-0-",
                               "NOT PROVIDED", "UNKNOWN", "DECEASED", "N", "?",
                               "NO NAME PROVIDED", "NOT MENTIONED", "FATHER",
                               "INACTIVE INACTIVE", "â¦.", "â¦"):
        return None
    return v

def parse_date(val):
    """Convert DD-Mon-YY or DD-Mon-YYYY to YYYY-MM-DD."""
    v = clean(val)
    if not v:
        return None
    v = v.strip()
    # Try DD-Mon-YY or DD-Mon-YYYY
    m = re.match(r"(\d{1,2})[-/](\w{3})[-/](\d{2,4})$", v)
    if m:
        day, mon, yr = m.groups()
        mon_num = MONTHS.get(mon.lower())
        if not mon_num:
            return None
        yr = int(yr)
        day = int(day)
        if yr < 100:
            yr += 2000 if yr <= 30 else 1900
        try:
            return datetime(yr, mon_num, day).strftime("%Y-%m-%d")
        except:
            return None
    # Try YYYY-MM-DD passthrough
    m2 = re.match(r"(\d{4})-(\d{2})-(\d{2})$", v)
    if m2:
        return v
    return None

def pick_parent(row):
    """Prefer mother, fall back to father."""
    name  = clean(row.get("Mother-Name"))   or clean(row.get("Father-Name"))
    phone = clean(row.get("M-contact number")) or clean(row.get("F-contac number"))
    email = clean(row.get("M-email"))        or clean(row.get("F-email"))
    return name, phone, email

def normalize_gender(val):
    v = clean(val)
    if not v: return None
    v = v.strip().upper()
    if v in ("M", "MALE", "BOY"):    return "Male"
    if v in ("F", "FEMALE", "GIRL"): return "Female"
    return None

def determine_status(row):
    active = (row.get("Active") or "").strip().upper()
    term   = clean(row.get("TerminationDate"))
    if active == "TRUE":
        return "Active"
    if term:
        return "Inactive"
    return "Inactive"

# ── Connect ──────────────────────────────────────────────────────────────────
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")

# ── Ensure classes exist for each TeamGrup value ──────────────────────────────
GROUPS = ["Poinciana", "Lignum Vitae", "Yellow Elder"]
class_map = {}
for grp in GROUPS:
    row = conn.execute("SELECT id FROM classes WHERE name=?", (grp,)).fetchone()
    if row:
        class_map[grp] = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO classes (name, academic_year) VALUES (?, ?)",
            (grp, "2025-2026")
        )
        class_map[grp] = cur.lastrowid

# ── Read CSV ──────────────────────────────────────────────────────────────────
csv_path = CSV_FILE
if not os.path.exists(csv_path):
    print(f"ERROR: {csv_path} not found — place it next to this script.")
    sys.exit(1)

with open(csv_path, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print(f"CSV rows read: {len(rows)}")

inserted = updated = skipped = 0

for row in rows:
    # Only import currently active students
    if (row.get("Active") or "").strip().upper() != "TRUE":
        skipped += 1
        continue

    raw_id    = (row.get("ID_Student") or "").strip()
    last_name = clean(row.get("LastName"))  or "Unknown"
    first_name= clean(row.get("Name"))      or "Unknown"

    if not raw_id or not first_name:
        skipped += 1
        continue

    # Use the raw CSV ID as student_id string
    student_id = raw_id

    dob      = parse_date(row.get("DOB"))
    gender   = normalize_gender(row.get("Gender"))
    phone    = clean(row.get("Home Phone"))
    address  = clean(row.get("Address"))
    status   = "Active"
    enroll   = parse_date(row.get("StartDate"))

    grp = (row.get("TeamGrup") or "").strip()
    class_id = class_map.get(grp)

    p_name, p_phone, p_email = pick_parent(row)

    # Emergency contact
    ec_name = clean(row.get("Other contact Name"))
    ec_rel  = clean(row.get("Relationship"))
    ec_cell = clean(row.get("Cell"))
    ec_parts = [x for x in [ec_name, ec_rel, ec_cell] if x]
    emergency = " | ".join(ec_parts) if ec_parts else None

    # Email: use Other Email if present, else None
    email = clean(row.get("Other Email"))

    # Check if already exists
    existing = conn.execute(
        "SELECT id FROM students WHERE student_id=?", (student_id,)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE students SET
                first_name=?, last_name=?, dob=?, gender=?, class_id=?,
                phone=?, address=?, email=?,
                parent_name=?, parent_phone=?, parent_email=?,
                enrollment_date=?, status=?, emergency_contact=?
            WHERE student_id=?
        """, (first_name, last_name, dob, gender, class_id,
              phone, address, email,
              p_name, p_phone, p_email,
              enroll, status, emergency,
              student_id))
        updated += 1
    else:
        conn.execute("""
            INSERT INTO students
                (student_id, first_name, last_name, dob, gender, class_id,
                 phone, address, email,
                 parent_name, parent_phone, parent_email,
                 enrollment_date, status, emergency_contact)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (student_id, first_name, last_name, dob, gender, class_id,
              phone, address, email,
              p_name, p_phone, p_email,
              enroll, status, emergency))
        inserted += 1

conn.commit()
conn.close()

print(f"\nDone.")
print(f"  Inserted : {inserted}")
print(f"  Updated  : {updated}")
print(f"  Skipped  : {skipped}")
print(f"  Total    : {inserted + updated + skipped}/{len(rows)}")
