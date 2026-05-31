"""
Seed script for School Management System — sample data
Run: python seed_db.py
"""
import sqlite3, hashlib, random
from datetime import date, timedelta, datetime

DB = "school.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")

def ph(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

today = date.today()
def days_ago(n): return (today - timedelta(days=n)).isoformat()
def days_from(n): return (today + timedelta(days=n)).isoformat()

# ── 1. Teachers ──────────────────────────────────────────────────────────────
teachers = [
    ("Mrs. Sandra Clarke",    "sandra.clarke@school.edu",    "5001234",  "Math"),
    ("Mr. James Rolle",       "james.rolle@school.edu",      "5002345",  "Science"),
    ("Ms. Patricia Thompson", "patricia.thompson@school.edu","5003456",  "English"),
    ("Mr. Kevin Knowles",     "kevin.knowles@school.edu",    "5004567",  "History"),
    ("Ms. Angela Sands",      "angela.sands@school.edu",     "5005678",  "Art"),
]
teacher_ids = []
for name, email, phone, dept in teachers:
    cur = conn.execute(
        "INSERT INTO teachers (full_name, email, phone, department, hire_date, status) VALUES (?,?,?,?,?,?)",
        (name, email, phone, dept, days_ago(random.randint(365,2000)), "Active")
    )
    teacher_ids.append(cur.lastrowid)

# ── 2. Users for teachers ────────────────────────────────────────────────────
for i, (tid, (name, email, _, __)) in enumerate(zip(teacher_ids, teachers)):
    uname = email.split("@")[0]
    conn.execute(
        "INSERT OR IGNORE INTO users (username,password_hash,full_name,email,role,linked_id,is_active) VALUES (?,?,?,?,?,?,?)",
        (uname, ph("teacher123"), name, email, "teacher", tid, 1)
    )

# ── 3. Classes ───────────────────────────────────────────────────────────────
class_defs = [
    ("Grade 7A", teacher_ids[0]),
    ("Grade 7B", teacher_ids[1]),
    ("Grade 8A", teacher_ids[2]),
    ("Grade 8B", teacher_ids[3]),
    ("Grade 9A", teacher_ids[0]),
    ("Grade 9B", teacher_ids[2]),
]
class_ids = []
for name, tid in class_defs:
    cur = conn.execute(
        "INSERT INTO classes (name, teacher_id, academic_year, room) VALUES (?,?,?,?)",
        (name, tid, "2025-2026", f"Room {random.randint(101,220)}")
    )
    class_ids.append(cur.lastrowid)

# ── 4. Subjects ──────────────────────────────────────────────────────────────
subject_defs = [
    ("Mathematics",        teacher_ids[0]),
    ("Science",            teacher_ids[1]),
    ("English Language",   teacher_ids[2]),
    ("Social Studies",     teacher_ids[3]),
    ("Art & Crafts",       teacher_ids[4]),
    ("Physical Education", teacher_ids[1]),
    ("Spanish",            teacher_ids[2]),
    ("Information Technology", teacher_ids[3]),
]
subject_ids = []
for name, tid in subject_defs:
    cur = conn.execute(
        "INSERT INTO subjects (name, teacher_id) VALUES (?,?)",
        (name, tid)
    )
    subject_ids.append(cur.lastrowid)

# ── 5. Students ──────────────────────────────────────────────────────────────
first_names = ["Alicia","Brandon","Camille","Deon","Ebony","Franklin","Gabrielle",
               "Hassan","Isabelle","Jamal","Keisha","Liam","Maya","Nathan","Olivia",
               "Patrick","Quincy","Rochelle","Samuel","Tiana","Ulric","Vanessa",
               "Wesley","Xara","Yolanda","Zachary","Amber","Brian","Crystal","Darius"]
last_names  = ["Rolle","Clarke","Knowles","Thompson","Sands","Ferguson","Lightbourn",
               "Williams","Johnson","Brown","Davis","Miller","Wilson","Moore","Taylor"]
parent_firsts = ["David","Jennifer","Michael","Patricia","Robert","Linda","William",
                 "Barbara","Richard","Susan","Charles","Karen","Mary","James","Sarah"]

student_ids = []
for i in range(30):
    fn = first_names[i]
    ln = random.choice(last_names)
    cls = random.choice(class_ids)
    dob = days_ago(random.randint(365*11, 365*15))
    gender = random.choice(["Male","Female"])
    status = random.choices(["Active","Active","Active","Inactive","Graduated"], weights=[70,10,5,10,5])[0]
    p_name = random.choice(parent_firsts) + " " + ln
    p_phone = "242-" + str(random.randint(300,599)) + "-" + str(random.randint(1000,9999))
    p_email = f"{ln.lower()}{random.randint(10,99)}@gmail.com"
    enroll  = days_ago(random.randint(30,800))
    cur = conn.execute("""
        INSERT INTO students
        (first_name,last_name,dob,gender,class_id,enrollment_date,status,
         email,phone,address,parent_name,parent_phone,parent_email,blood_type)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (fn, ln, dob, gender, cls, enroll, status,
          f"{fn.lower()}.{ln.lower()}@student.school.edu",
          "242-" + str(random.randint(300,599)) + "-" + str(random.randint(1000,9999)),
          str(random.randint(1,200)) + " Nassau St, Nassau",
          p_name, p_phone, p_email,
          random.choice(["A+","B+","O+","AB+","A-","O-"])))
    student_ids.append(cur.lastrowid)

# ── 6. Users for parents ─────────────────────────────────────────────────────
for sid in student_ids[:15]:  # give first 15 students a parent login
    s = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    uname = "parent_" + s["last_name"].lower() + str(sid)
    conn.execute(
        "INSERT OR IGNORE INTO users (username,password_hash,full_name,email,role,linked_id,is_active) VALUES (?,?,?,?,?,?,?)",
        (uname, ph("parent123"), s["parent_name"], s["parent_email"], "parent", sid, 1)
    )

# ── 7. Grades ────────────────────────────────────────────────────────────────
terms = ["Term 1","Term 2","Term 3"]
grade_letters = {range(90,101):"A+",range(85,90):"A",range(80,85):"A-",
                 range(75,80):"B+",range(70,75):"B",range(65,70):"B-",
                 range(60,65):"C+",range(55,60):"C",range(50,55):"C-",
                 range(0,50):"F"}

def score_to_grade(sc):
    for r,g in grade_letters.items():
        if sc in r: return g
    return "F"

for sid in student_ids:
    for sub_id in random.sample(subject_ids, 5):
        for term in terms:
            sc = random.randint(45, 100)
            conn.execute("""
                INSERT INTO grades (student_id, subject_id, term, score, grade, comments, recorded_at)
                VALUES (?,?,?,?,?,?,?)
            """, (sid, sub_id, term, sc, score_to_grade(sc),
                  random.choice(["Good effort","Excellent work","Needs improvement",
                                 "Keep it up","Outstanding","Room to grow",""]),
                  days_ago(random.randint(0, 90)) + "T10:00:00"))

# ── 8. Assignments ───────────────────────────────────────────────────────────
assignment_titles = [
    ("Math Quiz – Fractions",         subject_ids[0], class_ids[0], teacher_ids[0], 20),
    ("Science Lab Report",            subject_ids[1], class_ids[1], teacher_ids[1], 30),
    ("Book Report – Island Heritage", subject_ids[2], class_ids[2], teacher_ids[2], 25),
    ("History Essay – Emancipation",  subject_ids[3], class_ids[3], teacher_ids[3], 20),
    ("Art Portfolio Review",          subject_ids[4], class_ids[0], teacher_ids[4], 15),
    ("Mid-Term Math Exam",            subject_ids[0], class_ids[4], teacher_ids[0], 50),
    ("English Grammar Test",          subject_ids[2], class_ids[5], teacher_ids[2], 25),
    ("IT Practical – Spreadsheets",   subject_ids[7], class_ids[1], teacher_ids[3], 20),
]
assign_ids = []
for title, sub_id, cls_id, t_id, pts in assignment_titles:
    due = days_from(random.randint(-10, 30))
    cur = conn.execute("""
        INSERT INTO assignments (title, subject_id, class_id, teacher_id, due_date, max_points, description, status)
        VALUES (?,?,?,?,?,?,?,?)
    """, (title, sub_id, cls_id, t_id, due, pts,
          "Complete and submit by the due date.", "Active"))
    assign_ids.append(cur.lastrowid)

# ── 9. Attendance ────────────────────────────────────────────────────────────
school_days = []
d = today - timedelta(days=60)
while d <= today:
    if d.weekday() < 5:
        school_days.append(d.isoformat())
    d += timedelta(days=1)

for sid in student_ids:
    cls_id = conn.execute("SELECT class_id FROM students WHERE id=?", (sid,)).fetchone()[0]
    for day in random.sample(school_days, min(len(school_days), len(school_days))):
        status = random.choices(["Present","Present","Present","Absent","Late"],
                                weights=[78,5,2,10,5])[0]
        note = "Late arrival" if status == "Late" else ""
        conn.execute(
            "INSERT OR IGNORE INTO attendance (student_id, class_id, date, status, notes) VALUES (?,?,?,?,?)",
            (sid, cls_id, day, status, note)
        )

# ── 10. Fees ──────────────────────────────────────────────────────────────────
fee_types = [
    ("Tuition Fee – Term 1",   2800.00, "Tuition",    days_ago(90),  days_ago(60)),
    ("Tuition Fee – Term 2",   2800.00, "Tuition",    days_ago(30),  days_from(30)),
    ("Tuition Fee – Term 3",   2800.00, "Tuition",    days_from(60), days_from(120)),
    ("School Supplies Fee",     150.00, "Supplies",   days_ago(90),  days_ago(45)),
    ("Technology Fee",          200.00, "Technology", days_ago(90),  days_ago(45)),
    ("Activity Fee",            100.00, "Activity",   days_ago(60),  days_from(10)),
    ("Lunch Program – Term 1",  450.00, "Lunch",      days_ago(90),  days_ago(60)),
    ("Lunch Program – Term 2",  450.00, "Lunch",      days_ago(30),  days_from(30)),
]
for sid in student_ids:
    for desc, amt, ftype, issued, due in random.sample(fee_types, random.randint(3,6)):
        paid = random.choices([amt, 0, round(amt*0.5,2)], weights=[55,30,15])[0]
        status = "Paid" if paid >= amt else ("Partial" if paid > 0 else "Unpaid")
        conn.execute("""
            INSERT INTO fees (student_id, description, amount, amount_paid, fee_type,
                              issue_date, due_date, status)
            VALUES (?,?,?,?,?,?,?,?)
        """, (sid, desc, amt, paid, ftype, issued, due, status))

# ── 11. Announcements ────────────────────────────────────────────────────────
announcements_data = [
    ("Welcome Back — Term 2!",
     "We are thrilled to welcome all students, parents, and staff back for Term 2. Let us continue to strive for excellence together!",
     days_ago(30), "all"),
    ("Sports Day – Save the Date",
     "Annual Sports Day will be held on " + days_from(21) + ". Students are encouraged to participate in track & field, relay, and team sports.",
     days_ago(14), "all"),
    ("Parent-Teacher Conference",
     "Parent-Teacher conferences are scheduled for " + days_from(10) + ". Please contact the front office to book your slot.",
     days_ago(7), "all"),
    ("Library New Arrivals",
     "The school library has received over 200 new books across fiction, non-fiction, and STEM categories. Students may borrow up to 3 books at a time.",
     days_ago(5), "all"),
    ("Uniform Reminder",
     "All students must wear full school uniform including ID badges at all times on campus. Non-compliance will result in a demerit.",
     days_ago(3), "all"),
    ("Science Fair – Call for Projects",
     "The annual Science Fair is approaching! Students in Grades 7-9 are invited to submit project proposals by " + days_from(14) + ".",
     days_ago(2), "all"),
    ("Staff Meeting – Reminder",
     "All teaching staff please note there is a mandatory staff meeting on " + days_from(5) + " at 3:30 PM in the conference room.",
     days_ago(1), "teachers"),
]
for title, body, posted, audience in announcements_data:
    conn.execute("""
        INSERT INTO announcements (title, body, posted_at, audience)
        VALUES (?,?,?,?)
    """, (title, body, posted + "T08:00:00", audience))

# ── 12. Events ───────────────────────────────────────────────────────────────
events_data = [
    ("Sports Day",               "Annual track & field and team sports event.",
     days_from(21), "09:00", "15:00", "Sports",    "all",      "#10b981"),
    ("Parent-Teacher Conference","Book your slot with your child's homeroom teacher.",
     days_from(10), "09:00", "16:00", "Meeting",   "all",      "#4f46e5"),
    ("Science Fair",             "Student project presentations – Grades 7-9.",
     days_from(28), "10:00", "13:00", "Academic",  "all",      "#f59e0b"),
    ("Staff Meeting",            "Mandatory for all teaching staff.",
     days_from(5),  "15:30", "17:00", "Meeting",   "teachers", "#ef4444"),
    ("Mid-Term Exams Begin",     "All students must be present. No late arrivals.",
     days_from(14), "08:00", "12:00", "Exam",      "all",      "#6366f1"),
    ("Graduation Ceremony",      "Grade 9 graduation celebration.",
     days_from(45), "10:00", "13:00", "Ceremony",  "all",      "#ec4899"),
    ("Library Reading Week",     "Special reading activities and author visit.",
     days_from(7),  "08:00", "15:30", "Academic",  "all",      "#0ea5e9"),
    ("Fee Payment Deadline",     "Final day to submit Term 2 tuition without penalty.",
     days_from(3),  "08:00", "16:00", "Finance",   "parents",  "#f97316"),
]
admin_uid = conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()[0]
for title, desc, edate, st, et, etype, aud, color in events_data:
    conn.execute("""
        INSERT INTO events (title, description, event_date, start_time, end_time,
                            event_type, audience, color, created_by, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (title, desc, edate, st, et, etype, aud, color, admin_uid,
          today.isoformat() + "T08:00:00"))

# ── 13. Payment plans ────────────────────────────────────────────────────────
for sid in random.sample(student_ids, 8):
    total = 8400.00
    paid  = round(random.uniform(0, total), 2)
    cur = conn.execute("""
        INSERT INTO payment_plans (student_id, description, total_amount, amount_paid,
                                   start_date, end_date, status, created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (sid, "Annual Tuition Plan 2025-2026", total, paid,
          days_ago(120), days_from(120),
          "Active" if paid < total else "Completed",
          days_ago(120) + "T08:00:00"))
    plan_id = cur.lastrowid
    remaining = total - paid
    for month_offset in range(1, 4):
        inst_due  = days_from(30 * month_offset)
        inst_amt  = round(total / 3, 2)
        inst_paid = round(min(inst_amt, max(0, paid - inst_amt*(month_offset-1))), 2)
        inst_stat = "Paid" if inst_paid >= inst_amt else ("Partial" if inst_paid > 0 else "Pending")
        if inst_paid < inst_amt and inst_due < today.isoformat():
            inst_stat = "Overdue"
        conn.execute("""
            INSERT INTO plan_installments (plan_id, due_date, amount, amount_paid, status)
            VALUES (?,?,?,?,?)
        """, (plan_id, inst_due, inst_amt, inst_paid, inst_stat))

conn.commit()
conn.close()
print("Seed complete.")

# Summary
conn2 = sqlite3.connect(DB)
tables = conn2.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print("\n=== Row counts after seed ===")
for t in tables:
    n = t[0]
    c = conn2.execute("SELECT COUNT(*) FROM " + n).fetchone()[0]
    if c: print(f"  {n}: {c}")
conn2.close()
