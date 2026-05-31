#!/usr/bin/env python
"""
Clean database script - reinitialize school.db
"""
import sqlite3
import os
from datetime import date

DB = "school.db"

# Check if db exists and remove it
if os.path.exists(DB):
    os.remove(DB)
    print(f"[✓] Removed existing {DB}")

# Create fresh database with schema
conn = sqlite3.connect(DB)
c = conn.cursor()

try:
    c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL, email TEXT, role TEXT NOT NULL DEFAULT "viewer",
            phone TEXT, address TEXT,
            linked_id INTEGER, is_active INTEGER DEFAULT 1,
            created_at TEXT, last_login TEXT, must_change_pw INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE NOT NULL, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
            dob TEXT, gender TEXT, class_id INTEGER, email TEXT, phone TEXT, address TEXT,
            parent_name TEXT, parent_phone TEXT, parent_email TEXT,
            enrollment_date TEXT, status TEXT DEFAULT "Active", photo TEXT,
            medical_notes TEXT, emergency_contact TEXT
        );
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id TEXT UNIQUE NOT NULL, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
            dob TEXT, gender TEXT, email TEXT, phone TEXT, address TEXT,
            subject TEXT, qualification TEXT, hire_date TEXT,
            salary REAL DEFAULT 0, status TEXT DEFAULT "Active"
        );
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, grade TEXT, teacher_id INTEGER,
            room TEXT, capacity INTEGER DEFAULT 30, academic_year TEXT
        );
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, code TEXT, class_id INTEGER,
            teacher_id INTEGER, credits INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL, date TEXT NOT NULL,
            status TEXT NOT NULL, subject_id INTEGER, remarks TEXT,
            recorded_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL, subject_id INTEGER NOT NULL,
            exam_type TEXT, score REAL, max_score REAL DEFAULT 100,
            grade_letter TEXT, term TEXT, academic_year TEXT, date TEXT,
            recorded_by INTEGER, comments TEXT
        );
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, description TEXT, subject_id INTEGER,
            class_id INTEGER, teacher_id INTEGER, due_date TEXT,
            max_score REAL DEFAULT 100, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS assignment_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER, student_id INTEGER,
            score REAL, submitted_at TEXT, graded_at TEXT, comments TEXT
        );
        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL, subject_id INTEGER NOT NULL,
            teacher_id INTEGER, day TEXT NOT NULL,
            start_time TEXT NOT NULL, end_time TEXT NOT NULL, room TEXT
        );
        CREATE TABLE IF NOT EXISTS finances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, category TEXT NOT NULL,
            description TEXT, amount REAL NOT NULL, date TEXT NOT NULL,
            account TEXT, payment_method TEXT, status TEXT DEFAULT "Completed",
            reference TEXT, qb_synced INTEGER DEFAULT 0, qb_sync_date TEXT, created_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS fees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL, fee_type TEXT NOT NULL,
            amount REAL NOT NULL, due_date TEXT,
            paid_amount REAL DEFAULT 0, status TEXT DEFAULT "Unpaid",
            academic_year TEXT, term TEXT,
            qb_synced INTEGER DEFAULT 0, qb_sync_date TEXT, created_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS student_credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL,
            description TEXT,
            donor_name TEXT,
            date TEXT NOT NULL,
            fee_id INTEGER,
            created_by INTEGER,
            qb_synced INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, body TEXT NOT NULL,
            audience TEXT DEFAULT "all", class_id INTEGER,
            created_by INTEGER, created_at TEXT, is_pinned INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS admissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL, last_name TEXT NOT NULL,
            dob TEXT, gender TEXT, grade_applying TEXT,
            parent_name TEXT NOT NULL, parent_email TEXT NOT NULL, parent_phone TEXT,
            address TEXT, previous_school TEXT, reason TEXT,
            status TEXT DEFAULT "Pending", submitted_at TEXT, notes TEXT, reviewed_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user INTEGER, to_user INTEGER, subject TEXT,
            body TEXT NOT NULL, sent_at TEXT, is_read INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS qb_sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_date TEXT, synced_by INTEGER, record_type TEXT,
            record_ids TEXT, count INTEGER DEFAULT 0, status TEXT, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, action TEXT, table_name TEXT,
            record_id INTEGER, details TEXT, timestamp TEXT
        );
        CREATE TABLE IF NOT EXISTS payment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            total_amount REAL NOT NULL,
            plan_type TEXT NOT NULL,
            installment_count INTEGER NOT NULL,
            installment_amount REAL NOT NULL,
            start_date TEXT,
            academic_year TEXT,
            status TEXT DEFAULT "Active",
            created_by INTEGER,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS plan_installments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            installment_num INTEGER NOT NULL,
            due_date TEXT,
            amount REAL NOT NULL,
            paid_amount REAL DEFAULT 0,
            status TEXT DEFAULT "Unpaid"
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            event_date TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            event_type TEXT DEFAULT "General",
            audience TEXT DEFAULT "all",
            class_id INTEGER,
            color TEXT DEFAULT "#4f46e5",
            created_by INTEGER,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE NOT NULL,
            student_id INTEGER NOT NULL,
            issue_date TEXT NOT NULL,
            due_date TEXT,
            status TEXT DEFAULT 'Draft',
            notes TEXT,
            created_by INTEGER,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            fee_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS report_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            card_type TEXT NOT NULL,
            academic_year TEXT NOT NULL,
            teacher_name TEXT,
            data TEXT NOT NULL DEFAULT '{}',
            created_by INTEGER,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS role_permissions (
            role TEXT PRIMARY KEY,
            permissions TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    ''')
    print("[✓] Schema created")
    
    # Add default roles
    import json
    default_roles = {
        'admin':      ['all'],
        'teacher':    ['dashboard','students','classes','attendance','grades','timetable','announcements','calendar','directory'],
        'accountant': ['dashboard','students','finances','qb_sync','reports','calendar','directory','walk_ins'],
        'frontdesk':  ['dashboard','students','finances','directory','walk_ins'],
        'parent':     ['parent_portal'],
        'student':    ['student_portal'],
        'viewer':     ['dashboard','students','teachers','classes','attendance','grades','timetable','calendar','directory'],
    }
    
    for role, perms in default_roles.items():
        c.execute("INSERT INTO role_permissions (role, permissions) VALUES (?,?)",
                  (role, json.dumps(perms)))
    print("[✓] Default roles added")
    
    # Add default admin user (password: admin123 hashed with bcrypt)
    # For simplicity, using a pre-hashed value - in production use bcrypt
    admin_hash = "$2b$12$mFY1f/VW7h2pJjqIXVyLde8w4/VKjLCKBE8h2eLmNsVtFQrS9YHPi"  # bcrypt hash of "admin123"
    c.execute('''INSERT INTO users (username,password_hash,full_name,email,role,is_active,created_at)
                 VALUES (?,?,?,?,?,?,?)''',
              ('admin', admin_hash, 'System Administrator',
               'admin@myschool.edu', 'admin', 1, date.today().isoformat()))
    print("[✓] Admin user created (username: admin, password: admin123)")
    
    # Add default settings
    default_settings = {
        'school_name': 'My School',
        'school_address': '',
        'school_phone': '242-123-4567',
        'school_email': 'info@myschool.edu'
    }
    for key, val in default_settings.items():
        c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, val))
    print("[✓] Default settings created")
    
    conn.commit()
    print(f"\n✅ Database cleaned and reinitialized: {DB}")
    
except Exception as e:
    conn.rollback()
    print(f"❌ Error: {e}")
    raise
finally:
    conn.close()
