from flask import Flask, render_template, request, jsonify, redirect, session, send_file, Response, stream_with_context
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bcrypt
import sqlite3, os, hashlib, secrets, json, io, glob, smtplib, uuid, html as html_module, random, sys

# allow importing generate_manual from the project root
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    from generate_manual import build_for_role as _build_manual, _ROLE_LABELS as _MANUAL_ROLE_LABELS
    _MANUAL_AVAILABLE = True
except Exception:
    _MANUAL_AVAILABLE = False
import xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from functools import wraps
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
from dotenv import load_dotenv

load_dotenv()

import license as _lic
from payroll_routes import payroll_bp

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, default_limits=[])
app.config['PERMANENT_SESSION_LIFETIME'] = __import__('datetime').timedelta(hours=8)
app.config['SESSION_PERMANENT'] = True
app.register_blueprint(payroll_bp)
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{os.path.join(_APP_DIR, "school.db")}')
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Strip sqlite:/// prefix to get the absolute file path used by sqlite3
DB_PATH = DATABASE_URL.replace('sqlite:///', '', 1)
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(_APP_DIR, DB_PATH)

_DEFAULT_ROLES = {
    'admin':      ['all'],
    'teacher':    ['dashboard','students','classes','attendance','grades','timetable','announcements','calendar','directory'],
    'accountant': ['dashboard','students','finances','qb_sync','reports','calendar','directory','walk_ins'],
    'frontdesk':  ['dashboard','students','finances','directory','walk_ins'],
    'parent':     ['parent_portal'],
    'student':    ['student_portal'],
    'viewer':     ['dashboard','students','teachers','classes','attendance','grades','timetable','calendar','directory'],
}

ALL_PERMISSIONS = [
    ('dashboard','Dashboard'), ('students','Students'), ('teachers','Teachers'),
    ('classes','Classes'), ('attendance','Attendance'), ('grades','Grades'),
    ('timetable','Timetable'), ('announcements','Announcements'), ('calendar','Calendar'),
    ('directory','Directory'), ('finances','Finances / Fees'), ('qb_sync','QuickBooks Sync'),
    ('reports','Reports'), ('walk_ins','Walk-ins'),
    ('parent_portal','Parent Portal'), ('student_portal','Student Portal'),
]

def _load_roles():
    try:
        conn = get_db()
        rows = conn.execute("SELECT role, permissions FROM role_permissions").fetchall()
        conn.close()
        if rows:
            return {r['role']: json.loads(r['permissions']) for r in rows}
    except Exception:
        pass
    return dict(_DEFAULT_ROLES)

ROLES = _load_roles()

def reload_roles():
    global ROLES
    ROLES = _load_roles()

def get_setting(key, default=None):
    """Get a setting value by key"""
    try:
        conn = get_db()
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row['value'] if row else default
    except Exception:
        return default

def set_setting(key, value):
    """Set a setting value"""
    try:
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def hash_pw(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

# ── Session / Connection-limit helpers ────────────────────────────────────────

import socket as _socket

def get_local_ip():
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def _session_token():
    return session.get('_tok')

def _register_session(user_id):
    tok = secrets.token_hex(24)
    session['_tok'] = tok
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO active_sessions (token,user_id,ip_address,user_agent,last_seen,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (tok, user_id,
         request.remote_addr,
         request.user_agent.string[:200] if request.user_agent else '',
         datetime.now().isoformat(),
         datetime.now().isoformat()))
    conn.commit(); conn.close()
    return tok

def _unregister_session():
    tok = session.get('_tok')
    if tok:
        conn = get_db()
        conn.execute("DELETE FROM active_sessions WHERE token=?", (tok,))
        conn.commit(); conn.close()

def _touch_session():
    tok = session.get('_tok')
    if tok:
        conn = get_db()
        conn.execute("UPDATE active_sessions SET last_seen=? WHERE token=?",
                     (datetime.now().isoformat(), tok))
        conn.commit(); conn.close()

def _prune_stale_sessions():
    timeout_h = int(get_setting('session_timeout_h', '8') or 8)
    cutoff = (datetime.now() - __import__('datetime').timedelta(hours=timeout_h)).isoformat()
    conn = get_db()
    conn.execute("DELETE FROM active_sessions WHERE last_seen < ?", (cutoff,))
    conn.commit(); conn.close()

def _active_session_count():
    _prune_stale_sessions()
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) FROM active_sessions").fetchone()[0]
    conn.close()
    return n

def _connection_limit_reached():
    limit = int(get_setting('max_connections', '0') or 0)
    if limit <= 0:
        return False
    return _active_session_count() >= limit

def _check_pw(pw, stored):
    # Migrate old SHA-256 hashes (64-char hex) to bcrypt on first successful login
    if len(stored) == 64 and all(c in '0123456789abcdef' for c in stored):
        if hashlib.sha256(pw.encode()).hexdigest() == stored:
            return 'migrate'
        return False
    try:
        return bcrypt.checkpw(pw.encode(), stored.encode())
    except Exception:
        return False

def init_db():
    conn = get_db(); c = conn.cursor()
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
            student_id INTEGER, payment_method TEXT, status TEXT DEFAULT "Completed",
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
    ''')
    # Migrations for columns added after initial schema
    for sql in [
        "ALTER TABLE users ADD COLUMN phone TEXT",
        "ALTER TABLE users ADD COLUMN address TEXT",
        "ALTER TABLE students ADD COLUMN student_type TEXT DEFAULT 'Enrolled'",
        "ALTER TABLE students ADD COLUMN graduation_date TEXT",
        "ALTER TABLE students ADD COLUMN report_card_type TEXT DEFAULT 'standard'",
        "ALTER TABLE students ADD COLUMN father_name TEXT",
        "ALTER TABLE students ADD COLUMN father_phone TEXT",
        "ALTER TABLE students ADD COLUMN father_email TEXT",
        "ALTER TABLE payment_plans ADD COLUMN reduce REAL DEFAULT 0",
        "ALTER TABLE payment_plans ADD COLUMN scholarship REAL DEFAULT 0",
    ]:
        try: c.execute(sql)
        except: pass
    # Role permissions table
    c.execute('''CREATE TABLE IF NOT EXISTS role_permissions (
        role TEXT PRIMARY KEY,
        permissions TEXT NOT NULL
    )''')
    # Settings table for customization
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')
    # Active session tracking (for concurrent PC limit)
    c.execute('''CREATE TABLE IF NOT EXISTS active_sessions (
        token      TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        ip_address TEXT,
        user_agent TEXT,
        last_seen  TEXT NOT NULL,
        created_at TEXT NOT NULL
    )''')
    # Seed defaults if empty
    if c.execute("SELECT COUNT(*) FROM role_permissions").fetchone()[0] == 0:
        for role, perms in _DEFAULT_ROLES.items():
            c.execute("INSERT INTO role_permissions (role, permissions) VALUES (?,?)",
                      (role, json.dumps(perms)))
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        c.execute('''INSERT INTO users (username,password_hash,full_name,email,role,is_active,created_at,must_change_pw)
                     VALUES (?,?,?,?,?,?,?,?)''',
                  ('admin', hash_pw('admin123'), 'System Administrator',
                   '', 'admin', 1, date.today().isoformat(), 1))
    # Initialize default settings
    default_settings = {
        'school_name':       'My School',
        'school_address':    '',
        'school_phone':      '',
        'school_email':      '',
        'school_logo':       '/static/images/logo-light.jpg',
        'max_connections':   '0',   # 0 = unlimited
        'session_timeout_h': '8',   # hours before auto-logout
        'server_mode':       'lan',  # lan | online
        'language':          'en',   # en | es
    }
    for key, val in default_settings.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))
    conn.commit(); conn.close()
    auto_graduate_students()

def get_credit_balance(conn, student_id):
    row = conn.execute("SELECT COALESCE(SUM(amount),0) FROM student_credits WHERE student_id=?",
                       (student_id,)).fetchone()
    return round(float(row[0]), 2)

def first_friday_of_june(year):
    d = date(year, 6, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)

def calc_graduation_date(dob_str):
    """First Friday of June in the year the student turns 18."""
    if not dob_str:
        return None
    try:
        dob = datetime.strptime(str(dob_str)[:10], '%Y-%m-%d').date()
        return first_friday_of_june(dob.year + 18).isoformat()
    except Exception:
        return None

def auto_graduate_students():
    conn = get_db()
    # Backfill graduation_date for any student who has a DOB but none set yet
    rows = conn.execute(
        "SELECT id, dob FROM students WHERE dob IS NOT NULL AND graduation_date IS NULL"
    ).fetchall()
    for row in rows:
        gd = calc_graduation_date(row['dob'])
        if gd:
            conn.execute("UPDATE students SET graduation_date=? WHERE id=?", (gd, row['id']))
    # Promote students whose graduation date has passed
    today = date.today().isoformat()
    conn.execute(
        "UPDATE students SET status='Graduated' "
        "WHERE graduation_date IS NOT NULL AND graduation_date <= ? AND status='Active'",
        (today,))
    conn.commit(); conn.close()

# ── Decorators ────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def d(*a,**kw):
        if 'user_id' not in session: return redirect('/home')
        if request.endpoint != 'set_password':
            conn = get_db()
            row = conn.execute("SELECT must_change_pw FROM users WHERE id=?", (session['user_id'],)).fetchone()
            conn.close()
            if row and row['must_change_pw']:
                return redirect('/set-password')
        return f(*a,**kw)
    return d

def role_required(*roles):
    def dec(f):
        @wraps(f)
        def d(*a,**kw):
            if 'user_id' not in session: return redirect('/login')
            r = session.get('role','')
            if r not in roles and r != 'admin':
                return render_template('error.html', message="Access denied."), 403
            return f(*a,**kw)
        return d
    return dec

def can(perm):
    r = session.get('role','')
    if r == 'admin': return True
    return perm in ROLES.get(r,[])
app.jinja_env.globals['can'] = can

def unread_count():
    uid = session.get('user_id')
    if not uid: return 0
    try:
        conn = get_db()
        n = conn.execute("SELECT COUNT(*) FROM messages WHERE to_user=? AND is_read=0", (uid,)).fetchone()[0]
        conn.close(); return n
    except: return 0
app.jinja_env.globals['unread_count'] = unread_count

app.jinja_env.globals['enumerate'] = enumerate

# ── Translations ──────────────────────────────────────────
_TRANSLATIONS: dict[str, dict] = {}

def _load_translations():
    i18n_dir = os.path.join(os.path.dirname(__file__), 'static', 'i18n')
    for lang in ('en', 'es'):
        path = os.path.join(i18n_dir, f'{lang}.json')
        try:
            with open(path, encoding='utf-8') as f:
                _TRANSLATIONS[lang] = json.load(f)
        except Exception:
            _TRANSLATIONS[lang] = {}

_load_translations()

def _t(key: str, **kwargs) -> str:
    lang = session.get('lang') or get_setting('language', 'en')
    text = _TRANSLATIONS.get(lang, {}).get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text

app.jinja_env.globals['_'] = _t

@app.context_processor
def inject_school():
    lang = session.get('lang') or get_setting('language', 'en')
    return {
        'school_name':    get_setting('school_name',    'School Name'),
        'school_address': get_setting('school_address', ''),
        'school_phone':   get_setting('school_phone',   ''),
        'school_email':   get_setting('school_email',   ''),
        'school_logo':    get_setting('school_logo',    '/static/images/logo-light.jpg'),
        'lang':           lang,
        '_':              _t,
    }

@app.route('/set-language/<lang>')
def set_language(lang):
    if lang in ('en', 'es'):
        session['lang'] = lang
    return redirect(request.referrer or '/')


@app.route('/manual')
def serve_manual():
    if not session.get('user_id'):
        return redirect('/login')
    if not _MANUAL_AVAILABLE:
        return 'Manual generator not available.', 503
    role = session.get('role', 'viewer')
    try:
        pdf_bytes = _build_manual(role)
    except Exception as e:
        return f'Could not generate manual: {e}', 500
    label = _MANUAL_ROLE_LABELS.get(role, role.title())
    filename = f'SchoolMS_Manual_{label.replace(" ", "_")}.pdf'
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=False,
        download_name=filename,
    )

_LICENSE_BYPASS = {
    'activate', 'static', 'manifest_json', 'sw_js',
    'login', 'logout', 'home', 'contact', 'admissions',
    'parent_register', 'ping', 'serve_manual',
}

@app.before_request
def license_gate():
    if os.environ.get('LICENSE_DEV', '').strip() == '1':
        return  # dev/review bypass — never set this in production
    ep = request.endpoint or ''
    if ep in _LICENSE_BYPASS or ep.startswith('static'):
        return
    key = get_setting('license_key', '')
    if not key:
        return redirect('/activate')
    ok, _, err = _lic.validate_key(key)
    if not ok:
        return redirect('/activate')

@app.template_filter('money')
def money_fmt(value):
    try:
        return '${:,.2f}'.format(float(value or 0))
    except:
        return '$0.00'

@app.template_filter('fmt_date')
def fmt_date(value):
    if not value:
        return '—'
    try:
        s = str(value)[:10]
        dt = datetime.strptime(s, '%Y-%m-%d')
        return dt.strftime('%b %d, %Y')
    except:
        return str(value)

@app.template_filter('age')
def calc_age(value):
    if not value:
        return '—'
    try:
        dob = datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
        today = date.today()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except:
        return '—'

@app.template_filter('fmt_datetime')
def fmt_datetime(value):
    if not value:
        return '—'
    try:
        s = str(value)[:16]
        dt = datetime.strptime(s, '%Y-%m-%dT%H:%M')
        return dt.strftime('%b %d, %Y %I:%M %p')
    except:
        try:
            return str(value)[:16].replace('T', ' ')
        except:
            return str(value)

def audit(action, table=None, rid=None, details=None):
    try:
        conn = get_db()
        conn.execute('INSERT INTO audit_log (user_id,action,table_name,record_id,details,timestamp) VALUES (?,?,?,?,?,?)',
                     (session.get('user_id'),action,table,rid,json.dumps(details) if details else None,datetime.now().isoformat()))
        conn.commit(); conn.close()
    except: pass

# ── PWA Manifest & Service Worker ────────────────────────────────────────────

@app.route('/manifest.json')
def pwa_manifest():
    name = get_setting('school_name', 'School')
    manifest = {
        "name": name,
        "short_name": name.split()[0] if name else 'School',
        "description": f"{name} — School Management System",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1e1b4b",
        "theme_color": "#4f46e5",
        "orientation": "portrait-primary",
        "icons": [
            {"src": "/static/icons/icon-72.png",  "sizes": "72x72",   "type": "image/png"},
            {"src": "/static/icons/icon-96.png",  "sizes": "96x96",   "type": "image/png"},
            {"src": "/static/icons/icon-128.png", "sizes": "128x128", "type": "image/png"},
            {"src": "/static/icons/icon-144.png", "sizes": "144x144", "type": "image/png"},
            {"src": "/static/icons/icon-152.png", "sizes": "152x152", "type": "image/png"},
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/icons/icon-384.png", "sizes": "384x384", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ]
    }
    from flask import Response
    return Response(json.dumps(manifest), mimetype='application/manifest+json')

@app.route('/sw.js')
def service_worker():
    sw = """const CACHE='sms-v1';
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(
  caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k))))
));
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));
});"""
    from flask import Response
    return Response(sw, mimetype='application/javascript',
                    headers={'Service-Worker-Allowed': '/'})

# ── Public Website ────────────────────────────────────────────────────────────

@app.route('/home')
def public_home():
    conn = get_db()
    news = conn.execute("SELECT * FROM announcements WHERE audience='all' ORDER BY is_pinned DESC, id DESC LIMIT 5").fetchall()
    conn.close()
    return render_template('public/home.html', news=news)

@app.route('/admissions', methods=['GET','POST'])
def public_admissions():
    success = False
    if request.method == 'POST':
        d = request.form
        conn = get_db()
        conn.execute('''INSERT INTO admissions (first_name,last_name,dob,gender,grade_applying,
            parent_name,parent_email,parent_phone,address,previous_school,reason,submitted_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (d['first_name'],d['last_name'],d.get('dob'),d.get('gender'),d.get('grade_applying'),
             d['parent_name'],d['parent_email'],d.get('parent_phone'),d.get('address'),
             d.get('previous_school'),d.get('reason'),date.today().isoformat()))
        conn.commit(); conn.close()
        success = True
    return render_template('public/admissions.html', success=success)

@app.route('/contact')
def public_contact():
    return render_template('public/contact.html')

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/ping')
@login_required
def ping():
    session.modified = True
    _touch_session()
    return ('', 204)


@app.route('/login', methods=['GET','POST'])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,)).fetchone()
        conn.close()
        result = _check_pw(password, user['password_hash']) if user else False
        if result:
            # Check concurrent connection limit (admins always allowed through)
            if user['role'] != 'admin' and _connection_limit_reached():
                error = (f"Connection limit reached. The school has set a maximum of "
                         f"{get_setting('max_connections','?')} simultaneous connections. "
                         f"Please try again later or ask an administrator.")
            else:
                if result == 'migrate':
                    conn2 = get_db()
                    conn2.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(password), user['id']))
                    conn2.commit(); conn2.close()
                session.permanent = True
                session.update({'user_id':user['id'],'username':user['username'],
                                'full_name':user['full_name'],'role':user['role'],
                                'linked_id':user['linked_id']})
                _register_session(user['id'])
                conn2 = get_db()
                conn2.execute("UPDATE users SET last_login=? WHERE id=?", (datetime.now().isoformat(),user['id']))
                conn2.commit(); conn2.close()
                audit('LOGIN')
                if user['must_change_pw']: return redirect('/set-password')
                if user['role'] == 'parent': return redirect('/parent')
                if user['role'] == 'student': return redirect('/student-portal')
                if user['role'] == 'teacher': return redirect('/teacher-home')
                return redirect('/')
        if not error:
            error = 'Invalid username or password.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    audit('LOGOUT')
    _unregister_session()
    session.clear()
    return redirect('/login')

@app.route('/parent/register', methods=['GET','POST'])
def parent_register():
    error = None; success = False
    if request.method == 'POST':
        d = request.form
        sid = d.get('student_id','').strip()
        parent_email = d.get('parent_email','').strip()
        password = d.get('password','')
        conn = get_db()
        student = conn.execute("SELECT * FROM students WHERE student_id=? AND parent_email=?",
                               (sid, parent_email)).fetchone()
        if not student:
            error = 'Student ID or parent email not found. Please contact the school.'
        else:
            existing = conn.execute("SELECT * FROM users WHERE linked_id=? AND role='parent'",
                                    (student['id'],)).fetchone()
            if existing:
                error = 'A parent account already exists for this student. Please login instead.'
            else:
                username = f"parent_{sid.lower()}"
                try:
                    conn.execute('''INSERT INTO users (username,password_hash,full_name,email,role,linked_id,is_active,created_at)
                                    VALUES (?,?,?,?,?,?,?,?)''',
                                 (username, hash_pw(password), student['parent_name'] or 'Parent',
                                  parent_email, 'parent', student['id'], 1, date.today().isoformat()))
                    conn.commit()
                    success = True
                except:
                    error = 'Username already taken. Please contact the school.'
        conn.close()
    return render_template('parent_register.html', error=error, success=success)

@app.route('/set-password', methods=['GET','POST'])
@login_required
def set_password():
    if request.method == 'POST':
        new_pw = request.form.get('new_password','')
        if len(new_pw) >= 6:
            conn = get_db()
            conn.execute("UPDATE users SET password_hash=?, must_change_pw=0 WHERE id=?",
                         (hash_pw(new_pw), session['user_id']))
            conn.commit(); conn.close()
            return redirect('/')
    return render_template('set_password.html')

# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    if session.get('role') == 'parent': return redirect('/parent')
    if session.get('role') == 'student': return redirect('/student-portal')
    if session.get('role') == 'teacher': return redirect('/teacher-home')
    conn = get_db()
    stats = {
        'students': conn.execute("SELECT COUNT(*) FROM students WHERE status='Active'").fetchone()[0],
        'teachers': conn.execute("SELECT COUNT(*) FROM teachers WHERE status='Active'").fetchone()[0],
        'classes':  conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0],
        'pending_admissions': conn.execute("SELECT COUNT(*) FROM admissions WHERE status='Pending'").fetchone()[0],
    }
    total_income  = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finances WHERE type='Income'").fetchone()[0]
    total_expense = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finances WHERE type='Expense'").fetchone()[0]
    unpaid_fees   = conn.execute("SELECT COALESCE(SUM(amount-paid_amount),0) FROM fees WHERE status!='Paid'").fetchone()[0]
    unsynced      = conn.execute("SELECT COUNT(*) FROM finances WHERE qb_synced=0").fetchone()[0]
    recent_students = conn.execute("SELECT * FROM students ORDER BY id DESC LIMIT 5").fetchall()
    recent_finances = conn.execute('''SELECT f.*, s.first_name||' '||s.last_name as student_name
                                      FROM finances f LEFT JOIN students s ON f.student_id=s.id
                                      ORDER BY f.id DESC LIMIT 5''').fetchall()
    announcements   = conn.execute("SELECT * FROM announcements ORDER BY is_pinned DESC, id DESC LIMIT 5").fetchall()
    conn.close()
    return render_template('dashboard.html', stats=stats, total_income=total_income,
                           total_expense=total_expense, unpaid_fees=unpaid_fees,
                           unsynced_count=unsynced, recent_students=recent_students,
                           recent_finances=recent_finances, announcements=announcements)

# ── Teacher Home ──────────────────────────────────────────────────────────────

@app.route('/teacher-home')
@login_required
def teacher_home():
    if session.get('role') not in ('teacher','admin'):
        return redirect('/')
    teacher_db_id = session.get('linked_id')
    conn = get_db()
    # If teacher has no linked record, show all classes (admin/unlinked mode)
    if teacher_db_id:
        my_classes = conn.execute('''SELECT c.*, COUNT(s.id) as student_count
                                      FROM classes c LEFT JOIN students s ON s.class_id=c.id
                                      WHERE c.teacher_id=? GROUP BY c.id ORDER BY c.name''',
                                   (teacher_db_id,)).fetchall()
        my_subjects = conn.execute("SELECT * FROM subjects WHERE teacher_id=? ORDER BY name",
                                    (teacher_db_id,)).fetchall()
        my_assignments = conn.execute('''SELECT a.*, sub.name as subject_name, c.name as class_name
                                         FROM assignments a
                                         LEFT JOIN subjects sub ON a.subject_id=sub.id
                                         LEFT JOIN classes c ON a.class_id=c.id
                                         WHERE a.teacher_id=?
                                         ORDER BY a.due_date DESC''', (teacher_db_id,)).fetchall()
    else:
        my_classes = conn.execute('''SELECT c.*, COUNT(s.id) as student_count
                                      FROM classes c LEFT JOIN students s ON s.class_id=c.id
                                      GROUP BY c.id ORDER BY c.name''').fetchall()
        my_subjects = conn.execute("SELECT * FROM subjects ORDER BY name").fetchall()
        my_assignments = conn.execute('''SELECT a.*, sub.name as subject_name, c.name as class_name
                                         FROM assignments a
                                         LEFT JOIN subjects sub ON a.subject_id=sub.id
                                         LEFT JOIN classes c ON a.class_id=c.id
                                         ORDER BY a.due_date DESC''').fetchall()
    all_classes  = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
    all_subjects = conn.execute("SELECT * FROM subjects WHERE teacher_id=? ORDER BY name",
                                 (teacher_db_id,)).fetchall()
    announcements = conn.execute(
        "SELECT * FROM announcements WHERE audience IN ('all','teachers') ORDER BY is_pinned DESC, id DESC LIMIT 5"
    ).fetchall()
    today_str = date.today().isoformat()
    due_soon = [a for a in my_assignments if a['due_date'] and a['due_date'] >= today_str][:5]
    t_events = _events_for_role(conn, 'teacher')
    t_events_grouped = _events_by_date(t_events)
    upcoming_events = [e for e in t_events if e['event_date'] >= today_str][:10]
    msgs = conn.execute('''SELECT m.*, u.full_name as sender_name FROM messages m
                           LEFT JOIN users u ON m.from_user=u.id
                           WHERE m.to_user=? ORDER BY m.sent_at DESC LIMIT 20''',
                        (session['user_id'],)).fetchall()
    # Students per class for Reports tab
    class_students = {}
    for c in my_classes:
        sts = conn.execute('''
            SELECT s.*,
                (SELECT COUNT(*) FROM attendance a WHERE a.student_id=s.id AND a.status='Present') as present_count,
                (SELECT COUNT(*) FROM attendance a WHERE a.student_id=s.id) as total_att,
                (SELECT ROUND(AVG(g.score),1) FROM grades g WHERE g.student_id=s.id) as avg_score
            FROM students s WHERE s.class_id=? AND s.status='Active'
            ORDER BY s.last_name, s.first_name
        ''', (c['id'],)).fetchall()
        class_students[c['id']] = sts
    # Also fetch students for all classes if admin
    if not my_classes:
        all_students_flat = conn.execute('''
            SELECT s.*, c.name as class_name FROM students s
            LEFT JOIN classes c ON s.class_id=c.id WHERE s.status='Active' ORDER BY s.last_name
        ''').fetchall()
    else:
        all_students_flat = []
    conn.close()
    return render_template('teacher_home.html',
                           my_classes=my_classes, my_subjects=my_subjects,
                           my_assignments=my_assignments, all_classes=all_classes,
                           all_subjects=all_subjects, announcements=announcements,
                           due_soon=due_soon, today=today_str,
                           events_by_date=t_events_grouped, upcoming_events=upcoming_events,
                           messages=msgs, class_students=class_students,
                           all_students_flat=all_students_flat)

# ── Parent Portal ─────────────────────────────────────────────────────────────

@app.route('/parent')
@login_required
def parent_portal():
    if session.get('role') != 'parent' and session.get('role') != 'admin':
        return redirect('/')
    student_id = session.get('linked_id')
    conn = get_db()
    student = conn.execute('''SELECT s.*, c.name as class_name FROM students s
                              LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=?''', (student_id,)).fetchone()
    grades = conn.execute('''SELECT g.*, sub.name as subject_name FROM grades g
                             LEFT JOIN subjects sub ON g.subject_id=sub.id
                             WHERE g.student_id=? ORDER BY g.date DESC LIMIT 20''', (student_id,)).fetchall()
    attendance = conn.execute('''SELECT a.*, sub.name as subject_name FROM attendance a
                                 LEFT JOIN subjects sub ON a.subject_id=sub.id
                                 WHERE a.student_id=? ORDER BY a.date DESC LIMIT 30''', (student_id,)).fetchall()
    fees = conn.execute("SELECT * FROM fees WHERE student_id=? ORDER BY due_date DESC", (student_id,)).fetchall()
    announcements = conn.execute("""SELECT * FROM announcements
                                    WHERE audience IN ('all','parents')
                                    AND (class_id IS NULL OR class_id = ?)
                                    ORDER BY is_pinned DESC, id DESC LIMIT 10""",
                                 (student['class_id'],)).fetchall()
    present = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='Present'", (student_id,)).fetchone()[0]
    absent  = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='Absent'", (student_id,)).fetchone()[0]
    plans_raw = conn.execute(
        "SELECT * FROM payment_plans WHERE student_id=? ORDER BY created_at DESC", (student_id,)).fetchall()
    payment_plans = []
    for p in plans_raw:
        installments = conn.execute(
            "SELECT * FROM plan_installments WHERE plan_id=? ORDER BY installment_num", (p['id'],)).fetchall()
        payment_plans.append({'plan': p, 'installments': installments})
    today_str = date.today().isoformat()
    p_events = _events_for_role(conn, 'parent')
    p_events_grouped = _events_by_date(p_events)
    upcoming_events = [e for e in p_events if e['event_date'] >= today_str][:10]
    msgs = conn.execute('''SELECT m.*, u.full_name as sender_name FROM messages m
                           LEFT JOIN users u ON m.from_user=u.id
                           WHERE m.to_user=? ORDER BY m.sent_at DESC LIMIT 20''',
                        (session['user_id'],)).fetchall()
    conn.close()
    return render_template('parent_portal.html', student=student, grades=grades,
                           attendance=attendance, fees=fees, announcements=announcements,
                           present=present, absent=absent, payment_plans=payment_plans,
                           today=today_str, events_by_date=p_events_grouped,
                           upcoming_events=upcoming_events, messages=msgs)


@app.route('/parent/fee-statement')
@login_required
def parent_fee_statement():
    if session.get('role') not in ('parent', 'admin', 'accountant'):
        return redirect('/')

    # Admins/staff can pass ?student_id=; parents always use their linked student
    if session.get('role') == 'parent':
        student_id = session.get('linked_id')
    else:
        student_id = request.args.get('student_id', session.get('linked_id'))

    conn = get_db()
    student = conn.execute('''SELECT s.*, c.name as class_name FROM students s
                              LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=?''',
                           (student_id,)).fetchone()
    if not student:
        conn.close()
        return 'Student not found', 404

    fees = conn.execute(
        "SELECT * FROM fees WHERE student_id=? ORDER BY due_date DESC", (student_id,)).fetchall()
    plans_raw = conn.execute(
        "SELECT * FROM payment_plans WHERE student_id=? ORDER BY created_at DESC", (student_id,)).fetchall()
    payment_plans = []
    for p in plans_raw:
        insts = conn.execute(
            "SELECT * FROM plan_installments WHERE plan_id=? ORDER BY installment_num",
            (p['id'],)).fetchall()
        payment_plans.append({'plan': p, 'installments': insts})
    conn.close()

    total_charged = sum(f['amount'] for f in fees)
    total_paid    = sum(f['paid_amount'] for f in fees)
    balance_due   = total_charged - total_paid

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            topMargin=0.5*inch, bottomMargin=0.5*inch,
                            leftMargin=0.75*inch, rightMargin=0.75*inch)
    styles = getSampleStyleSheet()
    story  = []

    INDIGO  = colors.HexColor('#4f46e5')
    DARK    = colors.HexColor('#0f172a')
    LIGHT   = colors.HexColor('#f8fafc')
    BORDER  = colors.HexColor('#e2e8f0')
    MUTED   = colors.HexColor('#64748b')
    GREEN   = colors.HexColor('#16a34a')
    RED     = colors.HexColor('#dc2626')

    title_style = ParagraphStyle('T', fontSize=22, fontName='Helvetica-Bold', textColor=DARK, spaceAfter=3)
    sub_style   = ParagraphStyle('S', fontSize=10, textColor=MUTED, spaceAfter=2)
    h2_style    = ParagraphStyle('H2', fontSize=12, fontName='Helvetica-Bold', textColor=DARK, spaceAfter=6, spaceBefore=14)
    note_style  = ParagraphStyle('N', fontSize=8, textColor=MUTED)

    _sname = get_setting('school_name', 'School').upper()
    _saddr = get_setting('school_address', '')
    _semail = get_setting('school_email', '')
    _scontact = ' | '.join(filter(None, [_saddr, _semail]))
    story.append(Paragraph(_sname, title_style))
    if _scontact:
        story.append(Paragraph(_scontact, sub_style))
    story.append(Spacer(1, 0.08*inch))
    story.append(Table([['']], colWidths=[7*inch],
                       style=[('LINEBELOW', (0,0), (0,0), 2, INDIGO)]))
    story.append(Spacer(1, 0.12*inch))

    story.append(Paragraph("Student Fee Statement",
                            ParagraphStyle('RC', fontSize=15, fontName='Helvetica-Bold',
                                           textColor=INDIGO, spaceAfter=10)))

    info_data = [
        ['Student Name:', f"{student['first_name']} {student['last_name']}",
         'Student ID:', student['student_id']],
        ['Class:', student['class_name'] or '—',
         'Date Issued:', date.today().strftime('%B %d, %Y')],
        ['Status:', student['status'] or '—', 'Parent / Guardian:', student['parent_name'] or '—'],
    ]
    info_table = Table(info_data, colWidths=[1.3*inch, 2.2*inch, 1.3*inch, 2.2*inch])
    info_table.setStyle(TableStyle([
        ('FONTNAME',   (0,0), (-1,-1), 'Helvetica'),
        ('FONTNAME',   (0,0), (0,-1),  'Helvetica-Bold'),
        ('FONTNAME',   (2,0), (2,-1),  'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 10),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [LIGHT, colors.white]),
        ('GRID',       (0,0), (-1,-1), 0.5, BORDER),
        ('PADDING',    (0,0), (-1,-1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.18*inch))

    # Summary box
    summary_data = [
        ['Total Charged', 'Total Paid', 'Balance Due'],
        [f"${total_charged:,.2f}", f"${total_paid:,.2f}", f"${balance_due:,.2f}"],
    ]
    bal_color = RED if balance_due > 0 else GREEN
    sum_table = Table(summary_data, colWidths=[2.33*inch, 2.33*inch, 2.33*inch])
    sum_table.setStyle(TableStyle([
        ('BACKGROUND',  (0,0), (-1,0), INDIGO),
        ('TEXTCOLOR',   (0,0), (-1,0), colors.white),
        ('FONTNAME',    (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',    (0,0), (-1,-1), 11),
        ('ALIGN',       (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME',    (0,1), (-1,1), 'Helvetica-Bold'),
        ('TEXTCOLOR',   (2,1), (2,1),  bal_color),
        ('GRID',        (0,0), (-1,-1), 0.5, BORDER),
        ('PADDING',     (0,0), (-1,-1), 8),
        ('BACKGROUND',  (0,1), (-1,1), LIGHT),
    ]))
    story.append(sum_table)

    # Direct fees table
    story.append(Paragraph("Direct Fees", h2_style))
    if fees:
        f_data = [['Fee Type', 'Amount', 'Paid', 'Balance', 'Due Date', 'Term', 'Status']]
        for f in fees:
            bal = f['amount'] - f['paid_amount']
            f_data.append([
                f['fee_type'],
                f"${f['amount']:,.2f}",
                f"${f['paid_amount']:,.2f}",
                f"${bal:,.2f}",
                f['due_date'] or '—',
                f['term'] or '—',
                f['status'],
            ])
        ft = Table(f_data, colWidths=[1.6*inch, 0.9*inch, 0.9*inch, 0.9*inch, 0.9*inch, 0.7*inch, 0.8*inch])
        row_colors = [colors.white, LIGHT]
        ft.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0), INDIGO),
            ('TEXTCOLOR',     (0,0), (-1,0), colors.white),
            ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 9),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), row_colors),
            ('GRID',          (0,0), (-1,-1), 0.5, BORDER),
            ('ALIGN',         (1,0), (-1,-1), 'CENTER'),
            ('PADDING',       (0,0), (-1,-1), 6),
        ]))
        story.append(ft)
    else:
        story.append(Paragraph("No direct fees on record.", styles['Normal']))

    # Payment plans
    if payment_plans:
        story.append(Paragraph("Payment Plans", h2_style))
        for entry in payment_plans:
            p    = entry['plan']
            insts = entry['installments']
            paid_insts = sum(1 for i in insts if i['status'] == 'Paid')
            plan_paid    = sum(i['paid_amount'] for i in insts)
            reduce_val   = p['reduce'] or 0
            scholar_val  = p['scholarship'] or 0
            net_val      = p['total_amount'] - reduce_val - scholar_val
            plan_bal     = net_val - plan_paid
            summary_parts = [f"Total: ${p['total_amount']:,.2f}"]
            if reduce_val > 0:
                summary_parts.append(f"Reduction: -${reduce_val:,.2f}")
            if scholar_val > 0:
                summary_parts.append(f"Scholarship: -${scholar_val:,.2f}")
            if reduce_val > 0 or scholar_val > 0:
                summary_parts.append(f"Net: ${net_val:,.2f}")
            summary_parts += [f"Paid: ${plan_paid:,.2f}", f"Balance: ${plan_bal:,.2f}"]

            plan_hdr = Table(
                [[f"{p['description']}",
                  "  |  ".join(summary_parts),
                  p['status']]],
                colWidths=[2.5*inch, 3.2*inch, 1.3*inch])
            plan_hdr.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#ede9fe')),
                ('FONTNAME',   (0,0), (0,0),   'Helvetica-Bold'),
                ('FONTSIZE',   (0,0), (-1,-1),  9),
                ('ALIGN',      (2,0), (2,0),    'CENTER'),
                ('PADDING',    (0,0), (-1,-1),  6),
                ('GRID',       (0,0), (-1,-1),  0.5, BORDER),
            ]))
            story.append(plan_hdr)

            inst_data = [['#', 'Due Date', 'Amount', 'Paid', 'Status']]
            for i in insts:
                inst_data.append([
                    str(i['installment_num']),
                    i['due_date'] or '—',
                    f"${i['amount']:,.2f}",
                    f"${i['paid_amount']:,.2f}",
                    i['status'],
                ])
            it = Table(inst_data, colWidths=[0.4*inch, 1.5*inch, 1.5*inch, 1.5*inch, 2.1*inch])
            it.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,0), colors.HexColor('#c7d2fe')),
                ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE',      (0,0), (-1,-1), 9),
                ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, LIGHT]),
                ('GRID',          (0,0), (-1,-1), 0.5, BORDER),
                ('ALIGN',         (0,0), (-1,-1), 'CENTER'),
                ('PADDING',       (0,0), (-1,-1), 5),
            ]))
            story.append(it)
            story.append(Spacer(1, 0.1*inch))

    story.append(Spacer(1, 0.3*inch))
    story.append(Table([['']], colWidths=[7*inch],
                       style=[('LINEABOVE', (0,0), (0,0), 1, BORDER)]))
    story.append(Paragraph(
        f"{get_setting('school_name','School')} | {get_setting('school_address','')} | This document is generated electronically.",
        ParagraphStyle('footer', fontSize=8, textColor=MUTED, alignment=1)))

    doc.build(story)
    buf.seek(0)
    fname = f"FeeStatement_{student['student_id']}_{date.today().isoformat()}.pdf"
    return send_file(buf, download_name=fname, as_attachment=True, mimetype='application/pdf')


# ── Student Portal ────────────────────────────────────────────────────────────

@app.route('/student-portal')
@login_required
def student_portal():
    if session.get('role') not in ('student','admin'):
        return redirect('/')
    student_id = session.get('linked_id')
    conn = get_db()
    today_str = date.today().isoformat()
    student = conn.execute('''SELECT s.*, c.name as class_name FROM students s
                              LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=?''', (student_id,)).fetchone()
    grades = conn.execute('''SELECT g.*, sub.name as subject_name FROM grades g
                             LEFT JOIN subjects sub ON g.subject_id=sub.id
                             WHERE g.student_id=? ORDER BY g.date DESC''', (student_id,)).fetchall()
    assignments = conn.execute('''
        SELECT a.*,
               sub.name  AS subject_name,
               t.first_name || ' ' || t.last_name AS teacher_name,
               asub.score        AS my_score,
               asub.comments     AS feedback,
               asub.submitted_at AS submitted_at
        FROM assignments a
        LEFT JOIN subjects sub ON a.subject_id = sub.id
        LEFT JOIN teachers  t  ON a.teacher_id  = t.id
        LEFT JOIN assignment_submissions asub
               ON asub.assignment_id = a.id AND asub.student_id = ?
        WHERE a.class_id = (SELECT class_id FROM students WHERE id = ?)
        ORDER BY
            CASE WHEN asub.score IS NOT NULL   THEN 2
                 WHEN a.due_date < ?           THEN 1
                 ELSE 0 END ASC,
            a.due_date ASC
    ''', (student_id, student_id, today_str)).fetchall()
    attendance = conn.execute('''SELECT a.*, sub.name as subject_name FROM attendance a
                                 LEFT JOIN subjects sub ON a.subject_id=sub.id
                                 WHERE a.student_id=? ORDER BY a.date DESC LIMIT 20''', (student_id,)).fetchall()
    announcements = conn.execute("SELECT * FROM announcements WHERE audience IN ('all','students') ORDER BY is_pinned DESC, id DESC LIMIT 10").fetchall()
    s_events = _events_for_role(conn, 'student')
    s_events_grouped = _events_by_date(s_events)
    upcoming_events = [e for e in s_events if e['event_date'] >= today_str][:10]
    conn.close()
    return render_template('student_portal.html', student=student, grades=grades,
                           assignments=assignments, attendance=attendance, announcements=announcements,
                           today=today_str, events_by_date=s_events_grouped,
                           upcoming_events=upcoming_events)

# ── Students ──────────────────────────────────────────────────────────────────

@app.route('/students')
@login_required
def students():
    auto_graduate_students()
    conn = get_db()
    role = session.get('role')
    if role == 'teacher':
        tid = session.get('linked_id')
        rows = conn.execute('''SELECT s.*, c.name as class_name FROM students s
                               LEFT JOIN classes c ON s.class_id=c.id
                               WHERE (s.student_type IS NULL OR s.student_type = 'Enrolled')
                               AND s.class_id IN (SELECT id FROM classes WHERE teacher_id=?)
                               ORDER BY s.first_name, s.last_name''', (tid,)).fetchall()
        classes = conn.execute("SELECT * FROM classes WHERE teacher_id=? ORDER BY name", (tid,)).fetchall()
    else:
        rows = conn.execute('''SELECT s.*, c.name as class_name FROM students s
                               LEFT JOIN classes c ON s.class_id=c.id
                               WHERE s.student_type IS NULL OR s.student_type = 'Enrolled'
                               ORDER BY s.first_name, s.last_name''').fetchall()
        classes = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
    stats = {
        'total':     len(rows),
        'active':    sum(1 for s in rows if s['status'] == 'Active'),
        'inactive':  sum(1 for s in rows if s['status'] == 'Inactive'),
        'graduated': sum(1 for s in rows if s['status'] == 'Graduated'),
    }
    conn.close()
    return render_template('students.html', students=rows, classes=classes, stats=stats)

def generate_unique_id(conn=None):
    """Generate a random unique 10-digit ID shared across students and teachers."""
    close = conn is None
    if close:
        conn = get_db()
    while True:
        new_id = str(random.randint(1000000000, 9999999999))
        exists = conn.execute(
            "SELECT 1 FROM students WHERE student_id=? UNION SELECT 1 FROM teachers WHERE teacher_id=?",
            (new_id, new_id)
        ).fetchone()
        if not exists:
            break
    if close:
        conn.close()
    return new_id

def next_student_id(conn=None):
    return generate_unique_id(conn)

def next_teacher_id(conn=None):
    return generate_unique_id(conn)

@app.route('/students/next-id')
@role_required('admin', 'teacher')
def student_next_id():
    return jsonify(id=next_student_id())

@app.route('/teachers/next-id')
@role_required('admin')
def teacher_next_id_route():
    return jsonify(id=next_teacher_id())

@app.route('/students/add', methods=['POST'])
@role_required('admin','teacher')
def add_student():
    d = request.form
    conn = get_db()
    grad_date = calc_graduation_date(d.get('dob'))
    sid = d.get('student_id', '').strip() or next_student_id(conn)
    conn.execute('''INSERT INTO students (student_id,first_name,last_name,dob,gender,class_id,
        email,phone,address,parent_name,parent_phone,parent_email,father_name,father_phone,father_email,
        enrollment_date,status,medical_notes,emergency_contact,graduation_date,report_card_type)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (sid,d['first_name'],d['last_name'],d.get('dob'),d.get('gender'),
         d.get('class_id') or None,d.get('email'),d.get('phone'),d.get('address'),
         d.get('parent_name'),d.get('parent_phone'),d.get('parent_email'),
         d.get('father_name'),d.get('father_phone'),d.get('father_email'),
         d.get('enrollment_date',date.today().isoformat()),d.get('status','Active'),
         d.get('medical_notes'),d.get('emergency_contact'),grad_date,
         d.get('report_card_type','standard')))
    conn.commit(); conn.close()
    return redirect('/students')

@app.route('/students/edit/<int:id>', methods=['POST'])
@role_required('admin','teacher')
def edit_student(id):
    d = request.form
    grad_date = d.get('graduation_date') or calc_graduation_date(d.get('dob'))
    conn = get_db()
    conn.execute('''UPDATE students SET student_id=?,first_name=?,last_name=?,dob=?,gender=?,
        class_id=?,email=?,phone=?,address=?,parent_name=?,parent_phone=?,parent_email=?,
        father_name=?,father_phone=?,father_email=?,
        status=?,medical_notes=?,emergency_contact=?,graduation_date=?,report_card_type=? WHERE id=?''',
        (d['student_id'],d['first_name'],d['last_name'],d.get('dob'),d.get('gender'),
         d.get('class_id') or None,d.get('email'),d.get('phone'),d.get('address'),
         d.get('parent_name'),d.get('parent_phone'),d.get('parent_email'),
         d.get('father_name'),d.get('father_phone'),d.get('father_email'),
         d.get('status','Active'),d.get('medical_notes'),d.get('emergency_contact'),
         grad_date,d.get('report_card_type','standard'),id))
    conn.commit(); conn.close()
    return redirect('/students')

@app.route('/students/delete/<int:id>', methods=['POST'])
@role_required('admin')
def delete_student(id):
    conn = get_db(); conn.execute("DELETE FROM students WHERE id=?", (id,)); conn.commit(); conn.close()
    return redirect('/students')


_ALLOWED_PHOTO_EXTS = {'jpg', 'jpeg', 'png', 'webp', 'gif'}

@app.route('/students/<int:id>/upload-photo', methods=['POST'])
@role_required('admin', 'teacher')
def upload_student_photo(id):
    f = request.files.get('photo')
    if not f or not f.filename:
        return redirect(f'/students/{id}')
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in _ALLOWED_PHOTO_EXTS:
        return redirect(f'/students/{id}')

    photo_dir = os.path.join(app.root_path, 'static', 'student_photos')
    os.makedirs(photo_dir, exist_ok=True)

    # Remove any previous photo for this student before saving the new one
    for old in glob.glob(os.path.join(photo_dir, f'student_{id}.*')):
        os.remove(old)

    filename = f'student_{id}.{ext}'
    f.save(os.path.join(photo_dir, filename))

    conn = get_db()
    conn.execute("UPDATE students SET photo=? WHERE id=?",
                 (f'/static/student_photos/{filename}', id))
    conn.commit()
    conn.close()
    return redirect(f'/students/{id}')


# ── Walk-in Clients ──────────────────────────────────────────────────────────

@app.route('/walk-ins')
@login_required
def walk_ins():
    conn = get_db()
    clients = conn.execute('''
        SELECT s.*,
               COALESCE(SUM(f.amount),0)      AS total_charged,
               COALESCE(SUM(f.paid_amount),0) AS total_paid,
               COALESCE(SUM(f.amount),0) - COALESCE(SUM(f.paid_amount),0) AS balance
        FROM students s
        LEFT JOIN fees f ON f.student_id = s.id
        WHERE s.student_type = 'Walk-in'
        GROUP BY s.id
        ORDER BY s.first_name, s.last_name''').fetchall()
    stats = {
        'total':   len(clients),
        'active':  sum(1 for c in clients if c['status'] == 'Active'),
        'balance': sum(c['balance'] for c in clients),
    }
    conn.close()
    return render_template('walk_ins.html', clients=clients, stats=stats)

@app.route('/walk-ins/add', methods=['POST'])
@role_required('admin','accountant','frontdesk')
def add_walk_in():
    d = request.form
    conn = get_db()
    new_id = generate_unique_id(conn)
    conn.execute('''INSERT INTO students
        (student_id, first_name, last_name, phone, email, address,
         enrollment_date, status, student_type, medical_notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (new_id, d['first_name'], d['last_name'],
         d.get('phone'), d.get('email'), d.get('address'),
         date.today().isoformat(), 'Active', 'Walk-in',
         d.get('notes')))
    conn.commit(); conn.close()
    return redirect('/walk-ins')

@app.route('/walk-ins/delete/<int:id>', methods=['POST'])
@role_required('admin')
def delete_walk_in(id):
    conn = get_db()
    conn.execute("DELETE FROM fees WHERE student_id=?", (id,))
    conn.execute("DELETE FROM students WHERE id=? AND student_type='Walk-in'", (id,))
    conn.commit(); conn.close()
    return redirect('/walk-ins')


@app.route('/students/<int:id>')
@login_required
def student_detail(id):
    conn = get_db()
    role = session.get('role')
    if role == 'teacher':
        tid = session.get('linked_id')
        in_class = conn.execute(
            "SELECT 1 FROM students WHERE id=? AND class_id IN (SELECT id FROM classes WHERE teacher_id=?)",
            (id, tid)).fetchone()
        if not in_class:
            conn.close()
            return redirect('/students')
    student = conn.execute('''SELECT s.*, c.name as class_name FROM students s
                              LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=?''', (id,)).fetchone()
    grades = conn.execute('''SELECT g.*, sub.name as subject_name FROM grades g
                             LEFT JOIN subjects sub ON g.subject_id=sub.id
                             WHERE g.student_id=? ORDER BY g.date DESC''', (id,)).fetchall()
    att = conn.execute('''SELECT a.*, sub.name as subject_name FROM attendance a
                          LEFT JOIN subjects sub ON a.subject_id=sub.id
                          WHERE a.student_id=? ORDER BY a.date DESC LIMIT 30''', (id,)).fetchall()
    fees = conn.execute("SELECT * FROM fees WHERE student_id=? ORDER BY due_date DESC", (id,)).fetchall()
    plans_raw = conn.execute(
        "SELECT * FROM payment_plans WHERE student_id=? ORDER BY created_at DESC", (id,)).fetchall()
    plans = []
    for p in plans_raw:
        installments = conn.execute(
            "SELECT * FROM plan_installments WHERE plan_id=? ORDER BY installment_num", (p['id'],)).fetchall()
        plans.append({'plan': p, 'installments': installments})
    credit_balance  = get_credit_balance(conn, id)
    credit_history  = conn.execute(
        "SELECT sc.*, u.full_name as added_by FROM student_credits sc"
        " LEFT JOIN users u ON sc.created_by=u.id"
        " WHERE sc.student_id=? ORDER BY sc.date DESC", (id,)).fetchall()
    if role == 'teacher':
        classes = conn.execute("SELECT * FROM classes WHERE teacher_id=? ORDER BY name", (tid,)).fetchall()
    else:
        classes = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
    saved_rcs = conn.execute(
        "SELECT id, card_type, academic_year, teacher_name, updated_at FROM report_cards"
        " WHERE student_id=? ORDER BY academic_year DESC, card_type", (id,)).fetchall()
    conn.close()
    return render_template('student_detail.html', student=student, grades=grades,
                           attendance=att, fees=fees, plans=plans,
                           credit_balance=credit_balance, credit_history=credit_history,
                           classes=classes, saved_rcs=saved_rcs, now_date=date.today().isoformat())

@app.route('/students/<int:id>/add-credit', methods=['POST'])
@role_required('admin','accountant')
def add_student_credit(id):
    d = request.form
    amount      = float(d['amount'])
    credit_type = d['credit_type']
    description = d.get('description','').strip()
    donor_name  = d.get('donor_name','').strip()
    credit_date = d.get('credit_date') or date.today().isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO student_credits (student_id,amount,type,description,donor_name,date,created_by)"
        " VALUES (?,?,?,?,?,?,?)",
        (id, amount, credit_type, description, donor_name, credit_date, session.get('user_id')))
    # Also record as a finance income entry
    label = donor_name or credit_type
    conn.execute(
        "INSERT INTO finances (type,category,description,amount,date,student_id,status,created_by)"
        " VALUES (?,?,?,?,?,?,?,?)",
        ('Income', credit_type, description or f"{credit_type} — {label}", amount,
         credit_date, id, 'Completed', session.get('user_id')))
    conn.commit(); conn.close()
    return redirect(f'/students/{id}')

@app.route('/students/credit/<int:credit_id>/edit', methods=['POST'])
@role_required('admin','accountant')
def edit_student_credit(credit_id):
    d = request.form
    amount      = float(d['amount'])
    credit_type = d['credit_type']
    description = d.get('description','').strip()
    donor_name  = d.get('donor_name','').strip()
    credit_date = d.get('credit_date') or date.today().isoformat()
    conn = get_db()
    conn.execute(
        "UPDATE student_credits SET amount=?,type=?,description=?,donor_name=?,date=? WHERE id=?",
        (amount, credit_type, description, donor_name, credit_date, credit_id))
    conn.commit(); conn.close()
    return redirect(d.get('next', '/'))

@app.route('/students/<int:id>/credit-balance')
@role_required('admin','accountant')
def student_credit_balance(id):
    conn = get_db()
    balance = get_credit_balance(conn, id)
    conn.close()
    return jsonify({'balance': balance})

# ── Report Card PDF ───────────────────────────────────────────────────────────

@app.route('/students/<int:id>/report-card')
@login_required
def report_card(id):
    conn = get_db()
    student = conn.execute('''SELECT s.*, c.name as class_name FROM students s
                              LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=?''', (id,)).fetchone()
    term    = request.args.get('term', 'Term 1')
    year    = request.args.get('year', str(date.today().year))
    grades  = conn.execute('''SELECT g.*, sub.name as subject_name FROM grades g
                              LEFT JOIN subjects sub ON g.subject_id=sub.id
                              WHERE g.student_id=? AND g.term=? AND g.academic_year=?
                              ORDER BY sub.name''', (id, term, year)).fetchall()
    present = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='Present'", (id,)).fetchone()[0]
    absent  = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='Absent'", (id,)).fetchone()[0]
    conn.close()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    story  = []

    # Header
    title_style = ParagraphStyle('title', fontSize=22, fontName='Helvetica-Bold',
                                  textColor=colors.HexColor('#1e1b4b'), spaceAfter=4)
    sub_style   = ParagraphStyle('sub', fontSize=11, textColor=colors.HexColor('#64748b'), spaceAfter=2)
    story.append(Paragraph(get_setting('school_name', 'School').upper(), title_style))
    _sa = ' | '.join(filter(None, [get_setting('school_address',''), get_setting('school_email','')]))
    if _sa: story.append(Paragraph(_sa, sub_style))
    story.append(Spacer(1, 0.1*inch))

    # Divider line
    story.append(Table([['']], colWidths=[7*inch],
                        style=[('LINEBELOW',(0,0),(0,0),2,colors.HexColor('#4f46e5'))]))
    story.append(Spacer(1, 0.15*inch))

    # Report card title
    story.append(Paragraph(f"Student Report Card - {term} {year}",
                            ParagraphStyle('rc', fontSize=15, fontName='Helvetica-Bold',
                                           textColor=colors.HexColor('#4f46e5'), spaceAfter=12)))

    # Student info table
    info_data = [
        ['Student Name:', f"{student['first_name']} {student['last_name']}", 'Student ID:', student['student_id']],
        ['Class:', student['class_name'] or '—', 'Date Issued:', date.today().strftime('%B %d, %Y')],
        ['Attendance:', f"Present: {present}  |  Absent: {absent}", 'Status:', student['status']],
    ]
    info_table = Table(info_data, colWidths=[1.3*inch, 2.2*inch, 1.3*inch, 2.2*inch])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0,0),(-1,-1), 'Helvetica'),
        ('FONTNAME', (0,0),(0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (2,0),(2,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0),(-1,-1), 10),
        ('BACKGROUND',(0,0),(-1,-1), colors.HexColor('#f8fafc')),
        ('ROWBACKGROUNDS',(0,0),(-1,-1),[colors.HexColor('#f8fafc'),colors.white]),
        ('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#e2e8f0')),
        ('PADDING',(0,0),(-1,-1),6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.25*inch))

    # Grades table
    story.append(Paragraph("Academic Performance", ParagraphStyle('h2', fontSize=13,
                            fontName='Helvetica-Bold', textColor=colors.HexColor('#1e293b'), spaceAfter=8)))
    if grades:
        g_data = [['Subject', 'Exam Type', 'Score', 'Max', 'Grade', 'Comments']]
        total_score = 0; count = 0
        for g in grades:
            g_data.append([g['subject_name'] or '-', g['exam_type'] or '-',
                           str(g['score']), str(g['max_score']), g['grade_letter'] or '-',
                           g['comments'] or '-'])
            if g['score']: total_score += g['score']; count += 1
        avg = total_score/count if count else 0
        g_data.append(['', '', f'Avg: {avg:.1f}', '', get_grade_letter(avg), ''])
        gt = Table(g_data, colWidths=[2*inch, 1.2*inch, 0.7*inch, 0.7*inch, 0.7*inch, 1.7*inch])
        gt.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), colors.HexColor('#4f46e5')),
            ('TEXTCOLOR',(0,0),(-1,0), colors.white),
            ('FONTNAME',(0,0),(-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',(0,0),(-1,-1), 10),
            ('ROWBACKGROUNDS',(0,1),(-1,-2),[colors.white, colors.HexColor('#f8fafc')]),
            ('BACKGROUND',(0,-1),(-1,-1), colors.HexColor('#e0e7ff')),
            ('FONTNAME',(0,-1),(-1,-1), 'Helvetica-Bold'),
            ('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#e2e8f0')),
            ('ALIGN',(2,0),(4,-1),'CENTER'),
            ('PADDING',(0,0),(-1,-1),7),
        ]))
        story.append(gt)
    else:
        story.append(Paragraph("No grades recorded for this term.", styles['Normal']))

    story.append(Spacer(1, 0.4*inch))
    story.append(Paragraph("Grade Scale: A+ (96-100) · A (92-95) · A- (89-91) · B+ (86-88) · B (82-85) · B- (79-81) · C+ (76-78) · C (72-75) · C- (69-71) · D (60-68) · F (50-59)",
                            ParagraphStyle('note', fontSize=8, textColor=colors.HexColor('#94a3b8'))))
    story.append(Spacer(1, 0.3*inch))
    story.append(Table([['']], colWidths=[7*inch],
                        style=[('LINEABOVE',(0,0),(0,0),1,colors.HexColor('#e2e8f0'))]))
    story.append(Paragraph(f"{get_setting('school_name','School')} | {get_setting('school_address','')} | This document is generated electronically.",
                            ParagraphStyle('footer', fontSize=8, textColor=colors.HexColor('#94a3b8'), alignment=1)))

    doc.build(story)
    buf.seek(0)
    fname = f"ReportCard_{student['student_id']}_{term}_{year}.pdf".replace(' ','_')
    return send_file(buf, download_name=fname, as_attachment=True, mimetype='application/pdf')


# ── Fillable Report Card Forms ────────────────────────────────────────────────

@app.route('/students/<int:id>/report-card-form', methods=['GET', 'POST'])
@login_required
def report_card_form(id):
    role = session.get('role')
    conn = get_db()
    student = conn.execute(
        'SELECT s.*, c.name as class_name FROM students s'
        ' LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=?', (id,)).fetchone()
    if not student:
        conn.close()
        return redirect('/students')
    if role == 'teacher':
        tid = session.get('linked_id')
        in_class = conn.execute(
            'SELECT 1 FROM students WHERE id=? AND class_id IN'
            ' (SELECT id FROM classes WHERE teacher_id=?)', (id, tid)).fetchone()
        if not in_class:
            conn.close()
            return redirect('/students')

    if request.method == 'POST':
        card_type    = request.form.get('card_type', 'standard')
        year         = request.form.get('academic_year', '2025-2026').strip()
        teacher_name = request.form.get('teacher_name', '').strip()
        skip = {'card_type', 'academic_year', 'teacher_name'}
        data = {k: v for k, v in request.form.to_dict(flat=True).items() if k not in skip}
        existing = conn.execute(
            'SELECT id FROM report_cards WHERE student_id=? AND card_type=? AND academic_year=?',
            (id, card_type, year)).fetchone()
        now = datetime.now().isoformat()
        if existing:
            conn.execute(
                'UPDATE report_cards SET teacher_name=?, data=?, updated_at=? WHERE id=?',
                (teacher_name, json.dumps(data), now, existing['id']))
        else:
            conn.execute(
                'INSERT INTO report_cards'
                ' (student_id, card_type, academic_year, teacher_name, data, created_by, created_at, updated_at)'
                ' VALUES (?,?,?,?,?,?,?,?)',
                (id, card_type, year, teacher_name, json.dumps(data),
                 session.get('user_id'), now, now))
        conn.commit()
        conn.close()
        return redirect(f'/students/{id}')

    # GET
    card_type = request.args.get('type', 'standard')
    year      = request.args.get('year', '2025-2026')
    existing  = conn.execute(
        'SELECT * FROM report_cards WHERE student_id=? AND card_type=? AND academic_year=?',
        (id, card_type, year)).fetchone()
    teacher_name = ''
    if role == 'teacher' and session.get('linked_id'):
        t = conn.execute('SELECT first_name, last_name FROM teachers WHERE id=?',
                         (session['linked_id'],)).fetchone()
        if t:
            teacher_name = f"{t['first_name']} {t['last_name']}"
    conn.close()
    existing_data = json.loads(existing['data']) if existing else {}
    tpl = 'report_card_iep.html' if card_type == 'iep' else 'report_card_standard.html'
    return render_template(tpl, student=student, year=year, card_type=card_type,
                           teacher_name=teacher_name, existing=existing_data,
                           rc_id=existing['id'] if existing else None)


@app.route('/students/<int:id>/report-card-form/<int:rc_id>/delete', methods=['POST'])
@role_required('admin', 'teacher')
def delete_report_card(id, rc_id):
    conn = get_db()
    conn.execute('DELETE FROM report_cards WHERE id=? AND student_id=?', (rc_id, id))
    conn.commit(); conn.close()
    return redirect(f'/students/{id}')


@app.route('/students/<int:id>/progress-report')
@login_required
def progress_report(id):
    conn = get_db()
    student = conn.execute('''SELECT s.*, c.name as class_name FROM students s
                              LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=?''', (id,)).fetchone()
    if not student:
        conn.close(); return 'Student not found', 404

    # Teacher info
    teacher = conn.execute('''SELECT t.first_name||' '||t.last_name as name
                               FROM classes c JOIN teachers t ON c.teacher_id=t.id
                               WHERE c.id=?''', (student['class_id'],)).fetchone()
    teacher_name = teacher['name'] if teacher else '—'

    # All grades for this student, latest per subject+term
    all_grades = conn.execute('''
        SELECT g.*, sub.name as subject_name, sub.id as sid
        FROM grades g LEFT JOIN subjects sub ON g.subject_id=sub.id
        WHERE g.student_id=? ORDER BY g.subject_id, g.term, g.date DESC
    ''', (id,)).fetchall()

    # All subjects in the student's class (ordered)
    subjects = conn.execute('''SELECT * FROM subjects WHERE class_id=? ORDER BY id''',
                             (student['class_id'],)).fetchall()

    # Build grid: {subject_id: {term: grade_letter}}
    grade_grid = {}
    seen = set()
    for g in all_grades:
        key = (g['sid'], g['term'] or '')
        if key not in seen:
            seen.add(key)
            grade_grid.setdefault(g['sid'], {})[g['term'] or ''] = {
                'letter': g['grade_letter'] or '—',
                'score':  g['score'],
                'max':    g['max_score'],
                'comments': g['comments'] or '',
            }

    # Attendance
    present = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='Present'", (id,)).fetchone()[0]
    absent  = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='Absent'",  (id,)).fetchone()[0]
    late    = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='Late'",    (id,)).fetchone()[0]
    term_filter = request.args.get('term', '')
    academic_year = request.args.get('year', '2025-2026')
    conn.close()

    # GPA per term
    def calc_gpa(term):
        pts = [GRADE_GPA.get(grade_grid.get(s['id'], {}).get(term, {}).get('letter', ''), None)
               for s in subjects if grade_grid.get(s['id'], {}).get(term)]
        pts = [p for p in pts if p is not None]
        return round(sum(pts)/len(pts), 2) if pts else None

    TERMS = ['Term 1', 'Term 2', 'Term 3']

    # ── PDF ───────────────────────────────────────────────────────────────────
    INDIGO  = colors.HexColor('#1e1b4b')
    INDIGO2 = colors.HexColor('#4f46e5')
    LIGHT   = colors.HexColor('#f8fafc')
    BORDER  = colors.HexColor('#e2e8f0')
    MUTED   = colors.HexColor('#64748b')
    WHITE   = colors.white

    def PS(name, **kw):
        defaults = dict(fontName='Helvetica', fontSize=9, textColor=colors.HexColor('#334155'), leading=13)
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)

    def P(txt, s='body', **kw):
        return Paragraph(txt, PS(s, **kw))

    def grade_color(letter):
        if letter in ('A+','A','A-'):  return colors.HexColor('#166534'), colors.HexColor('#dcfce7')
        if letter in ('B+','B','B-'):  return colors.HexColor('#1e40af'), colors.HexColor('#dbeafe')
        if letter in ('C+','C','C-'):  return colors.HexColor('#92400e'), colors.HexColor('#fef9c3')
        if letter in ('D',):           return colors.HexColor('#6b21a8'), colors.HexColor('#f3e8ff')
        if letter in ('F',):           return colors.HexColor('#991b1b'), colors.HexColor('#fee2e2')
        return MUTED, LIGHT

    def grade_cell(letter):
        if not letter or letter == '—':
            return P('—', 'gc', textColor=MUTED, alignment=1, fontSize=9)
        fg, bg = grade_color(letter)
        t = Table([[P(f'<b>{letter}</b>', 'gl', textColor=fg, alignment=1, fontSize=9)]],
                  colWidths=[0.55*inch])
        t.setStyle(TableStyle([
            ('BACKGROUND',   (0,0),(-1,-1), bg),
            ('TOPPADDING',   (0,0),(-1,-1), 3),
            ('BOTTOMPADDING',(0,0),(-1,-1), 3),
            ('LEFTPADDING',  (0,0),(-1,-1), 2),
            ('RIGHTPADDING', (0,0),(-1,-1), 2),
        ]))
        return t

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            topMargin=0.55*inch, bottomMargin=0.55*inch,
                            leftMargin=0.65*inch, rightMargin=0.65*inch)
    story = []
    PW = 7.2 * inch

    # ── Header ────────────────────────────────────────────────────────────────
    hdr = Table([
        [P(get_setting('school_name','School').upper(), 'h', fontName='Helvetica-Bold', fontSize=18,
           textColor=WHITE, alignment=1),
         P('STUDENT PROGRESS REPORT', 'hs', fontName='Helvetica-Bold', fontSize=13,
           textColor=colors.HexColor('#c7d2fe'), alignment=1)],
        [P(get_setting('school_address',''), 'hm', fontSize=8, textColor=colors.HexColor('#a5b4fc'), alignment=1),
         P(f'Academic Year: {academic_year}', 'hy', fontSize=9,
           textColor=colors.HexColor('#e0e7ff'), alignment=1)],
    ], colWidths=[PW*0.5, PW*0.5])
    hdr.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), INDIGO),
        ('TOPPADDING',    (0,0),(-1,-1), 14),
        ('BOTTOMPADDING', (0,0),(-1,-1), 14),
        ('LEFTPADDING',   (0,0),(-1,-1), 16),
        ('RIGHTPADDING',  (0,0),(-1,-1), 16),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 0.12*inch))

    # ── Student info ──────────────────────────────────────────────────────────
    total_att = present + absent + late
    att_pct = f"{round(present/total_att*100,1)}%" if total_att else "N/A"
    info = Table([
        [P("<b>Student's Name:</b>", fontSize=9),
         P(f"{student['first_name']} {student['last_name']}", fontSize=9, fontName='Helvetica-Bold'),
         P("<b>Teacher's Name:</b>", fontSize=9),
         P(f"Mrs./Mr. {teacher_name}", fontSize=9)],
        [P("<b>School Year:</b>", fontSize=9),
         P(academic_year, fontSize=9),
         P("<b>Date:</b>", fontSize=9),
         P(date.today().strftime('%B %d, %Y'), fontSize=9)],
        [P("<b>Classroom:</b>", fontSize=9),
         P(student['class_name'] or '—', fontSize=9),
         P("<b>Student ID:</b>", fontSize=9),
         P(student['student_id'], fontSize=9)],
    ], colWidths=[1.3*inch, 2.3*inch, 1.3*inch, 2.3*inch])
    info.setStyle(TableStyle([
        ('FONTNAME',      (0,0),(-1,-1), 'Helvetica'),
        ('FONTSIZE',      (0,0),(-1,-1), 9),
        ('ROWBACKGROUNDS',(0,0),(-1,-1), [LIGHT, WHITE, LIGHT]),
        ('GRID',          (0,0),(-1,-1), 0.4, BORDER),
        ('TOPPADDING',    (0,0),(-1,-1), 5),
        ('BOTTOMPADDING', (0,0),(-1,-1), 5),
        ('LEFTPADDING',   (0,0),(-1,-1), 7),
        ('RIGHTPADDING',  (0,0),(-1,-1), 7),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
    ]))
    story.append(info)
    story.append(Spacer(1, 0.1*inch))

    # ── Grading scale ─────────────────────────────────────────────────────────
    scale_txt = (
        f'<b>{get_setting("school_name","School")}\'s Grading Scale:</b>    '
        'A+: 96-100 (4.5)    A: 92-95 (4.0)    A-: 89-91 (3.8)    '
        'B+: 86-88 (3.5)    B: 82-85 (3.0)    B-: 79-81 (2.8)    '
        'C+: 76-78 (2.5)    C: 72-75 (2.0)    C-: 69-71 (1.8)    '
        'D: 60-68 (1.0)    F: 50-59 (0.0)'
    )
    scale = Table([[P(scale_txt, 'sc', fontSize=7.5, textColor=colors.HexColor('#1e3a5f'), leading=11)]],
                  colWidths=[PW])
    scale.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), colors.HexColor('#eff6ff')),
        ('TOPPADDING',    (0,0),(-1,-1), 6),
        ('BOTTOMPADDING', (0,0),(-1,-1), 6),
        ('LEFTPADDING',   (0,0),(-1,-1), 10),
        ('RIGHTPADDING',  (0,0),(-1,-1), 10),
        ('LINEBEFORE',    (0,0),(0,-1),  3, INDIGO2),
    ]))
    story.append(scale)
    story.append(Spacer(1, 0.12*inch))

    # ── Grades table ──────────────────────────────────────────────────────────
    if subjects:
        # Header row
        hdr_style = PS('th', fontName='Helvetica-Bold', fontSize=9, textColor=WHITE, alignment=1)
        g_data = [[
            Paragraph('Subject', hdr_style),
            Paragraph('Term 1', hdr_style),
            Paragraph('Term 2', hdr_style),
            Paragraph('Term 3', hdr_style),
            Paragraph('Comments', hdr_style),
        ]]
        col_w = [2.8*inch, 0.65*inch, 0.65*inch, 0.65*inch, 2.35*inch]

        for s in subjects:
            sg = grade_grid.get(s['id'], {})
            t1 = sg.get('Term 1', {}).get('letter', '—')
            t2 = sg.get('Term 2', {}).get('letter', '—')
            t3 = sg.get('Term 3', {}).get('letter', '—')
            # Take first non-empty comment
            comment = next((sg[t]['comments'] for t in ('Term 1','Term 2','Term 3')
                            if sg.get(t,{}).get('comments')), '')
            g_data.append([
                P(s['name'].upper(), 'sn', fontName='Helvetica-Bold', fontSize=9,
                  textColor=INDIGO),
                grade_cell(t1),
                grade_cell(t2),
                grade_cell(t3),
                P(comment[:80], 'cm', fontSize=8, textColor=MUTED),
            ])

        # GPA row
        gpa_row = ['']
        for term in TERMS:
            gpa = calc_gpa(term)
            gpa_row.append(P(f'GPA\n{gpa}' if gpa else '—', 'gp',
                              fontName='Helvetica-Bold', fontSize=8,
                              textColor=INDIGO2, alignment=1))
        gpa_row.append('')
        g_data.append(gpa_row)

        gt = Table(g_data, colWidths=col_w, repeatRows=1)
        n = len(g_data)
        gt.setStyle(TableStyle([
            # Header
            ('BACKGROUND',    (0,0),(-1,0),  INDIGO),
            ('FONTNAME',      (0,0),(-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0,0),(-1,0),  9),
            ('ALIGN',         (0,0),(-1,0),  'CENTER'),
            # Body rows
            ('ROWBACKGROUNDS',(0,1),(-1,n-2),[LIGHT, WHITE]),
            ('GRID',          (0,0),(-1,n-2), 0.4, BORDER),
            ('TOPPADDING',    (0,0),(-1,-1),  5),
            ('BOTTOMPADDING', (0,0),(-1,-1),  5),
            ('LEFTPADDING',   (0,0),(-1,-1),  7),
            ('RIGHTPADDING',  (0,0),(-1,-1),  7),
            ('VALIGN',        (0,0),(-1,-1),  'MIDDLE'),
            ('ALIGN',         (1,1),(3,-1),   'CENTER'),
            # GPA row
            ('BACKGROUND',    (0,n-1),(-1,n-1), colors.HexColor('#eef2ff')),
            ('LINEABOVE',     (0,n-1),(-1,n-1), 1, INDIGO2),
        ]))
        story.append(gt)
    else:
        story.append(P('No subjects configured for this classroom.', 'ns', textColor=MUTED))

    story.append(Spacer(1, 0.14*inch))

    # ── Attendance ────────────────────────────────────────────────────────────
    att = Table([[
        P('<b>ATTENDANCE SUMMARY</b>', 'at', fontSize=8, textColor=INDIGO, fontName='Helvetica-Bold'),
        P(f'Present: <b>{present}</b>', 'a1', fontSize=9, textColor=colors.HexColor('#166534')),
        P(f'Absent: <b>{absent}</b>',   'a2', fontSize=9, textColor=colors.HexColor('#991b1b')),
        P(f'Late: <b>{late}</b>',       'a3', fontSize=9, textColor=colors.HexColor('#92400e')),
        P(f'Attendance Rate: <b>{att_pct}</b>', 'a4', fontSize=9, textColor=INDIGO),
    ]], colWidths=[1.5*inch, 1.1*inch, 1.1*inch, 1.0*inch, 2.5*inch])
    att.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), colors.HexColor('#f0f9ff')),
        ('LINEBEFORE',    (0,0),(0,-1),  3, colors.HexColor('#0369a1')),
        ('GRID',          (0,0),(-1,-1), 0.4, BORDER),
        ('TOPPADDING',    (0,0),(-1,-1), 7),
        ('BOTTOMPADDING', (0,0),(-1,-1), 7),
        ('LEFTPADDING',   (0,0),(-1,-1), 8),
        ('RIGHTPADDING',  (0,0),(-1,-1), 8),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
    ]))
    story.append(att)
    story.append(Spacer(1, 0.14*inch))

    # ── Teacher comments ──────────────────────────────────────────────────────
    story.append(P('<b>TEACHER\'S COMMENTS</b>', 'tc', fontSize=9, textColor=INDIGO,
                   fontName='Helvetica-Bold', spaceAfter=4))
    comment_box = Table(
        [[P('', 'cb')]],
        colWidths=[PW], rowHeights=[0.7*inch]
    )
    comment_box.setStyle(TableStyle([
        ('GRID',          (0,0),(-1,-1), 0.5, BORDER),
        ('BACKGROUND',    (0,0),(-1,-1), WHITE),
        ('TOPPADDING',    (0,0),(-1,-1), 6),
        ('LEFTPADDING',   (0,0),(-1,-1), 8),
    ]))
    story.append(comment_box)
    story.append(Spacer(1, 0.18*inch))

    # ── Signature lines ───────────────────────────────────────────────────────
    sig_data = [[
        P("Teacher's Signature: ________________________", 'sg', fontSize=9),
        P("Principal's Signature: ________________________", 'sg', fontSize=9),
        P("Parent's Signature: ________________________", 'sg', fontSize=9),
    ]]
    sig = Table(sig_data, colWidths=[PW/3, PW/3, PW/3])
    sig.setStyle(TableStyle([
        ('TOPPADDING',    (0,0),(-1,-1), 4),
        ('BOTTOMPADDING', (0,0),(-1,-1), 4),
        ('LEFTPADDING',   (0,0),(-1,-1), 4),
        ('VALIGN',        (0,0),(-1,-1), 'BOTTOM'),
    ]))
    story.append(sig)
    story.append(Spacer(1, 0.1*inch))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Table([['']], colWidths=[PW],
                        style=[('LINEABOVE',(0,0),(0,0),0.5,BORDER)]))
    story.append(Spacer(1, 0.04*inch))
    story.append(P(f'{get_setting("school_name","School")}  ·  {get_setting("school_address","")}  ·  This document is generated electronically.',
                   'ft', fontSize=7.5, textColor=MUTED, alignment=1))

    doc.build(story)
    buf.seek(0)
    fname = f"ProgressReport_{student['student_id']}_{date.today().isoformat()}.pdf"
    return send_file(buf, download_name=fname, as_attachment=True, mimetype='application/pdf')


@app.route('/students/<int:id>/monthly-statement')
@role_required('admin','accountant')
def monthly_statement(id):
    conn = get_db()
    student = conn.execute(
        "SELECT s.*, c.name as class_name FROM students s "
        "LEFT JOIN classes c ON s.class_id=c.id WHERE s.id=?", (id,)).fetchone()
    if not student:
        conn.close(); return 'Student not found', 404

    # Period — default last month
    today_d = date.today()
    first_this = today_d.replace(day=1)
    last_month_end = first_this - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    from_date = request.args.get('from_date') or last_month_start.isoformat()
    to_date   = request.args.get('to_date')   or last_month_end.isoformat()

    # Opening balance = total fees charged BEFORE period minus total paid BEFORE period
    open_charged = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM fees WHERE student_id=? AND (due_date < ? OR due_date IS NULL)",
        (id, from_date)).fetchone()[0]
    open_paid = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM finances "
        "WHERE student_id=? AND type='Income' AND date < ?",
        (id, from_date)).fetchone()[0]
    open_credits = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM student_credits WHERE student_id=? AND date < ?",
        (id, from_date)).fetchone()[0]
    opening_balance = round(float(open_charged) - float(open_paid) + float(open_credits), 2)

    # Transactions IN the period
    charges = conn.execute(
        "SELECT due_date as txn_date, fee_type as description, amount, 'Charge' as txn_type "
        "FROM fees WHERE student_id=? AND due_date BETWEEN ? AND ? ORDER BY due_date",
        (id, from_date, to_date)).fetchall()
    payments = conn.execute(
        "SELECT date as txn_date, description, amount, 'Payment' as txn_type, payment_method "
        "FROM finances WHERE student_id=? AND type='Income' AND date BETWEEN ? AND ? ORDER BY date",
        (id, from_date, to_date)).fetchall()
    credits = conn.execute(
        "SELECT date as txn_date, description, amount, "
        "CASE WHEN amount > 0 THEN 'Credit Added' ELSE 'Credit Applied' END as txn_type "
        "FROM student_credits WHERE student_id=? AND date BETWEEN ? AND ? ORDER BY date",
        (id, from_date, to_date)).fetchall()
    conn.close()

    # Combine and sort all transactions by date
    all_txns = []
    for r in charges:
        all_txns.append({'date': r['txn_date'], 'desc': r['description'],
                         'type': 'Charge', 'debit': float(r['amount']), 'credit': 0})
    for r in payments:
        desc = r['description'] or 'Payment received'
        method = r['payment_method'] or ''
        all_txns.append({'date': r['txn_date'], 'desc': f"{desc}{' — '+method if method else ''}",
                         'type': 'Payment', 'debit': 0, 'credit': float(r['amount'])})
    for r in credits:
        amt = float(r['amount'])
        all_txns.append({'date': r['txn_date'], 'desc': r['description'] or r['type'],
                         'type': r['type'],
                         'debit': abs(amt) if amt < 0 else 0,
                         'credit': amt if amt > 0 else 0})
    all_txns.sort(key=lambda x: x['date'] or '')

    # Running balance and period totals
    total_charges  = sum(t['debit']  for t in all_txns)
    total_payments = sum(t['credit'] for t in all_txns)
    closing_balance = round(opening_balance + total_charges - total_payments, 2)

    # Build PDF
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            topMargin=0.5*inch, bottomMargin=0.6*inch,
                            leftMargin=0.75*inch, rightMargin=0.75*inch)
    styles = getSampleStyleSheet()
    story  = []

    INDIGO = colors.HexColor('#4f46e5')
    DARK   = colors.HexColor('#0f172a')
    LIGHT  = colors.HexColor('#f8fafc')
    BORDER = colors.HexColor('#e2e8f0')
    MUTED  = colors.HexColor('#64748b')
    GREEN  = colors.HexColor('#16a34a')
    RED    = colors.HexColor('#dc2626')
    AMBER  = colors.HexColor('#d97706')

    title_s = ParagraphStyle('T', fontSize=20, fontName='Helvetica-Bold', textColor=DARK, spaceAfter=2)
    sub_s   = ParagraphStyle('S', fontSize=9,  textColor=MUTED, spaceAfter=2)
    h2_s    = ParagraphStyle('H', fontSize=11, fontName='Helvetica-Bold', textColor=DARK, spaceBefore=12, spaceAfter=6)
    foot_s  = ParagraphStyle('F', fontSize=8,  textColor=MUTED, alignment=1)

    # Header
    story.append(Paragraph(get_setting('school_name','School').upper(), title_s))
    _sc = ' | '.join(filter(None,[get_setting('school_address',''),get_setting('school_email','')]))
    if _sc: story.append(Paragraph(_sc, sub_s))
    story.append(Spacer(1, 0.06*inch))
    story.append(Table([['']], colWidths=[7*inch],
                       style=[('LINEBELOW', (0,0), (0,0), 2, INDIGO)]))
    story.append(Spacer(1, 0.1*inch))

    from datetime import datetime as dt
    try:
        fd_fmt = dt.strptime(from_date, '%Y-%m-%d').strftime('%B %d, %Y')
        td_fmt = dt.strptime(to_date,   '%Y-%m-%d').strftime('%B %d, %Y')
    except:
        fd_fmt, td_fmt = from_date, to_date

    story.append(Paragraph("Account Statement",
        ParagraphStyle('RC', fontSize=14, fontName='Helvetica-Bold', textColor=INDIGO, spaceAfter=8)))

    info_data = [
        ['Student Name:', f"{student['first_name']} {student['last_name']}",
         'Student ID:', student['student_id']],
        ['Class:', student['class_name'] or '—',
         'Statement Date:', date.today().strftime('%B %d, %Y')],
        ['Period:', f"{fd_fmt}  →  {td_fmt}",
         'Parent / Guardian:', student['parent_name'] or '—'],
    ]
    it = Table(info_data, colWidths=[1.3*inch, 2.2*inch, 1.3*inch, 2.2*inch])
    it.setStyle(TableStyle([
        ('FONTNAME',   (0,0), (-1,-1), 'Helvetica'),
        ('FONTNAME',   (0,0), (0,-1),  'Helvetica-Bold'),
        ('FONTNAME',   (2,0), (2,-1),  'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 9),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [LIGHT, colors.white]),
        ('GRID',       (0,0), (-1,-1), 0.5, BORDER),
        ('PADDING',    (0,0), (-1,-1), 6),
    ]))
    story.append(it)
    story.append(Spacer(1, 0.15*inch))

    # Opening balance row
    story.append(Paragraph("Transaction Detail", h2_s))
    txn_data = [['Date', 'Description', 'Type', 'Charges', 'Payments', 'Balance']]

    bal = opening_balance
    txn_data.append(['', 'Opening Balance', '', '', '', f"${bal:,.2f}"])

    type_colors = {'Charge': RED, 'Payment': GREEN, 'Credit Added': GREEN, 'Credit Applied': AMBER}
    row_styles = [
        ('BACKGROUND',  (0,0), (-1,0), INDIGO),
        ('TEXTCOLOR',   (0,0), (-1,0), colors.white),
        ('FONTNAME',    (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',    (0,0), (-1,-1), 9),
        ('GRID',        (0,0), (-1,-1), 0.5, BORDER),
        ('ALIGN',       (3,0), (5,-1), 'RIGHT'),
        ('PADDING',     (0,0), (-1,-1), 5),
        ('BACKGROUND',  (0,1), (-1,1), colors.HexColor('#ede9fe')),
        ('FONTNAME',    (0,1), (-1,1), 'Helvetica-Bold'),
    ]

    for i, t in enumerate(all_txns):
        if t['debit']:
            bal = round(bal + t['debit'], 2)
            dr_str = f"${t['debit']:,.2f}"
            cr_str = ''
        else:
            bal = round(bal - t['credit'], 2)
            dr_str = ''
            cr_str = f"${t['credit']:,.2f}"
        row_idx = len(txn_data)
        txn_data.append([
            t['date'] or '—',
            t['desc'] or '—',
            t['type'],
            dr_str,
            cr_str,
            f"${bal:,.2f}",
        ])
        bg = LIGHT if row_idx % 2 == 0 else colors.white
        row_styles.append(('BACKGROUND', (0, row_idx), (-1, row_idx), bg))
        c = type_colors.get(t['type'], MUTED)
        row_styles.append(('TEXTCOLOR', (2, row_idx), (2, row_idx), c))
        row_styles.append(('FONTNAME',  (2, row_idx), (2, row_idx), 'Helvetica-Bold'))

    # Closing balance row
    last_row = len(txn_data)
    txn_data.append(['', 'Closing Balance', '', f"${total_charges:,.2f}", f"${total_payments:,.2f}",
                     f"${closing_balance:,.2f}"])
    cb_color = RED if closing_balance > 0 else GREEN
    row_styles += [
        ('BACKGROUND', (0, last_row), (-1, last_row), colors.HexColor('#ede9fe')),
        ('FONTNAME',   (0, last_row), (-1, last_row), 'Helvetica-Bold'),
        ('TEXTCOLOR',  (5, last_row), (5, last_row),  cb_color),
    ]

    txn_table = Table(txn_data, colWidths=[0.85*inch, 2.5*inch, 1.05*inch, 0.9*inch, 0.9*inch, 0.8*inch])
    txn_table.setStyle(TableStyle(row_styles))
    story.append(txn_table)

    # Summary box
    story.append(Spacer(1, 0.2*inch))
    sum_data = [
        ['Period Charges', 'Period Payments', 'Closing Balance'],
        [f"${total_charges:,.2f}", f"${total_payments:,.2f}", f"${closing_balance:,.2f}"],
    ]
    st = Table(sum_data, colWidths=[2.33*inch, 2.33*inch, 2.33*inch])
    st.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), INDIGO),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 11),
        ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME',   (0,1), (-1,1), 'Helvetica-Bold'),
        ('TEXTCOLOR',  (2,1), (2,1),  RED if closing_balance > 0 else GREEN),
        ('GRID',       (0,0), (-1,-1), 0.5, BORDER),
        ('PADDING',    (0,0), (-1,-1), 8),
        ('BACKGROUND', (0,1), (-1,1), LIGHT),
    ]))
    story.append(st)

    if closing_balance > 0:
        story.append(Spacer(1, 0.1*inch))
        story.append(Paragraph(
            f"Amount Due: ${closing_balance:,.2f}  —  Please remit payment at your earliest convenience.",
            ParagraphStyle('due', fontSize=9, textColor=RED, fontName='Helvetica-Bold')))

    story.append(Spacer(1, 0.3*inch))
    story.append(Table([['']], colWidths=[7*inch],
                       style=[('LINEABOVE', (0,0), (0,0), 1, BORDER)]))
    story.append(Paragraph(
        f"{get_setting('school_name','School')} | {get_setting('school_address','')} | This statement is generated electronically.",
        foot_s))

    doc.build(story)
    buf.seek(0)
    month_str = from_date[:7].replace('-', '_')
    fname = f"Statement_{student['student_id']}_{month_str}.pdf"
    return send_file(buf, download_name=fname, as_attachment=True, mimetype='application/pdf')


# ── Teachers ──────────────────────────────────────────────────────────────────

@app.route('/teachers')
@login_required
def teachers():
    conn = get_db()
    if session.get('role') == 'admin':
        rows = conn.execute("SELECT * FROM teachers ORDER BY first_name").fetchall()
    else:
        rows = conn.execute(
            "SELECT id, teacher_id, first_name, last_name, dob, gender, email, "
            "phone, address, subject, qualification, hire_date, status "
            "FROM teachers ORDER BY first_name"
        ).fetchall()
    conn.close()
    return render_template('teachers.html', teachers=rows)

@app.route('/teachers/add', methods=['POST'])
@role_required('admin')
def add_teacher():
    d = request.form; conn = get_db()
    tid = d.get('teacher_id', '').strip() or next_teacher_id(conn)
    conn.execute('''INSERT INTO teachers (teacher_id,first_name,last_name,dob,gender,email,
        phone,address,subject,qualification,hire_date,salary,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (tid,d['first_name'],d['last_name'],d.get('dob'),d.get('gender'),
         d.get('email'),d.get('phone'),d.get('address'),d.get('subject'),
         d.get('qualification'),d.get('hire_date',date.today().isoformat()),
         float(d.get('salary') or 0),d.get('status','Active')))
    conn.commit(); conn.close()
    return redirect('/teachers')

@app.route('/teachers/edit/<int:id>', methods=['POST'])
@role_required('admin')
def edit_teacher(id):
    d = request.form; conn = get_db()
    conn.execute('''UPDATE teachers SET teacher_id=?,first_name=?,last_name=?,dob=?,gender=?,
        email=?,phone=?,address=?,subject=?,qualification=?,salary=?,status=? WHERE id=?''',
        (d['teacher_id'],d['first_name'],d['last_name'],d.get('dob'),d.get('gender'),
         d.get('email'),d.get('phone'),d.get('address'),d.get('subject'),
         d.get('qualification'),float(d.get('salary') or 0),d.get('status','Active'),id))
    conn.commit(); conn.close()
    return redirect('/teachers')

@app.route('/teachers/delete/<int:id>', methods=['POST'])
@role_required('admin')
def delete_teacher(id):
    conn = get_db(); conn.execute("DELETE FROM teachers WHERE id=?", (id,)); conn.commit(); conn.close()
    return redirect('/teachers')

# ── Classes & Subjects ────────────────────────────────────────────────────────

@app.route('/classes')
@login_required
def classes():
    conn = get_db()
    role = session.get('role')
    if role == 'teacher':
        tid = session.get('linked_id')
        cr = conn.execute('''SELECT c.*, t.first_name||' '||t.last_name as teacher_name,
            (SELECT COUNT(*) FROM students s WHERE s.class_id=c.id) as student_count
            FROM classes c LEFT JOIN teachers t ON c.teacher_id=t.id
            WHERE c.teacher_id=? ORDER BY c.name''', (tid,)).fetchall()
        subjects = conn.execute('''SELECT sub.*, c.name as class_name,
            t.first_name||' '||t.last_name as teacher_name
            FROM subjects sub LEFT JOIN classes c ON sub.class_id=c.id
            LEFT JOIN teachers t ON sub.teacher_id=t.id
            WHERE c.teacher_id=? ORDER BY sub.name''', (tid,)).fetchall()
        classes_list = conn.execute("SELECT * FROM classes WHERE teacher_id=? ORDER BY name", (tid,)).fetchall()
    else:
        cr = conn.execute('''SELECT c.*, t.first_name||' '||t.last_name as teacher_name,
            (SELECT COUNT(*) FROM students s WHERE s.class_id=c.id) as student_count
            FROM classes c LEFT JOIN teachers t ON c.teacher_id=t.id ORDER BY c.name''').fetchall()
        subjects = conn.execute('''SELECT sub.*, c.name as class_name,
            t.first_name||' '||t.last_name as teacher_name
            FROM subjects sub LEFT JOIN classes c ON sub.class_id=c.id
            LEFT JOIN teachers t ON sub.teacher_id=t.id ORDER BY sub.name''').fetchall()
        classes_list = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
    teachers = conn.execute("SELECT * FROM teachers WHERE status='Active' ORDER BY first_name").fetchall()
    conn.close()
    return render_template('classes.html', classes=cr, teachers=teachers,
                           subjects=subjects, classes_list=classes_list)

@app.route('/classes/<int:id>')
@login_required
def class_detail(id):
    conn = get_db()
    role = session.get('role')
    if role == 'teacher':
        tid = session.get('linked_id')
        owns = conn.execute("SELECT 1 FROM classes WHERE id=? AND teacher_id=?", (id, tid)).fetchone()
        if not owns:
            conn.close()
            return redirect('/classes')
    cls = conn.execute('''SELECT c.*, t.first_name||' '||t.last_name as teacher_name
                          FROM classes c LEFT JOIN teachers t ON c.teacher_id=t.id
                          WHERE c.id=?''', (id,)).fetchone()
    students = conn.execute('''SELECT s.* FROM students s WHERE s.class_id=? AND s.status='Active'
                               ORDER BY s.last_name, s.first_name''', (id,)).fetchall()
    subjects = conn.execute('''SELECT sub.*, t.first_name||' '||t.last_name as teacher_name
                               FROM subjects sub LEFT JOIN teachers t ON sub.teacher_id=t.id
                               WHERE sub.class_id=? ORDER BY sub.name''', (id,)).fetchall()
    conn.close()
    return render_template('class_detail.html', cls=cls, students=students, subjects=subjects)


@app.route('/classes/<int:id>/send-curriculum', methods=['POST'])
@role_required('admin', 'teacher')
def send_curriculum(id):
    d    = request.form
    conn = get_db()
    cls  = conn.execute("SELECT * FROM classes WHERE id=?", (id,)).fetchone()
    if not cls:
        conn.close()
        return redirect('/classes')

    term    = d.get('term', '').strip()
    subject = d.get('subject', '').strip()
    body    = d.get('body', '').strip()

    parts = [f"{cls['name']} — Upcoming Curriculum"]
    if subject: parts.append(subject)
    if term:    parts.append(term)
    title = ' | '.join(parts)

    # Post as an announcement visible in every parent portal for this class
    conn.execute('''INSERT INTO announcements (title, body, audience, class_id, created_by, created_at, is_pinned)
                    VALUES (?, ?, 'parents', ?, ?, ?, 0)''',
                 (title, body, id, session.get('user_id'), date.today().isoformat()))

    # Send a direct inbox message to each registered parent of a student in this class
    parent_users = conn.execute('''
        SELECT u.id FROM users u
        JOIN students s ON u.linked_id = s.id
        WHERE s.class_id = ? AND u.role = 'parent' AND u.is_active = 1
    ''', (id,)).fetchall()

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for pu in parent_users:
        conn.execute('''INSERT INTO messages (from_user, to_user, subject, body, sent_at, is_read)
                        VALUES (?, ?, ?, ?, ?, 0)''',
                     (session.get('user_id'), pu['id'], title, body, now))

    conn.commit()
    conn.close()
    return redirect(f'/classes/{id}')


@app.route('/classes/add', methods=['POST'])
@role_required('admin')
def add_class():
    d = request.form; conn = get_db()
    conn.execute("INSERT INTO classes (name,grade,teacher_id,room,capacity,academic_year) VALUES (?,?,?,?,?,?)",
        (d['name'],d.get('grade'),d.get('teacher_id') or None,
         d.get('room'),int(d.get('capacity') or 30),d.get('academic_year')))
    conn.commit(); conn.close(); return redirect('/classes')

@app.route('/classes/delete/<int:id>', methods=['POST'])
@role_required('admin')
def delete_class(id):
    conn = get_db(); conn.execute("DELETE FROM classes WHERE id=?", (id,)); conn.commit(); conn.close()
    return redirect('/classes')

@app.route('/subjects/add', methods=['POST'])
@role_required('admin','teacher')
def add_subject():
    d = request.form; conn = get_db()
    conn.execute("INSERT INTO subjects (name,code,class_id,teacher_id,credits) VALUES (?,?,?,?,?)",
        (d['name'],d.get('code'),d.get('class_id') or None,d.get('teacher_id') or None,int(d.get('credits') or 1)))
    conn.commit(); conn.close(); return redirect('/classes')

@app.route('/subjects/bulk-add', methods=['POST'])
@role_required('admin','teacher')
def bulk_add_subject():
    d = request.form
    name      = d['name']
    code      = d.get('code') or None
    override_tid = d.get('teacher_id') or None
    credits   = int(d.get('credits') or 1)
    class_ids = request.form.getlist('class_ids')
    if not class_ids:
        return redirect('/classes?tab=subjects')
    conn = get_db()
    for cid in class_ids:
        if override_tid:
            t_id = override_tid
        else:
            cls = conn.execute("SELECT teacher_id FROM classes WHERE id=?", (cid,)).fetchone()
            t_id = cls['teacher_id'] if cls else None
        conn.execute("INSERT INTO subjects (name,code,class_id,teacher_id,credits) VALUES (?,?,?,?,?)",
                     (name, code, cid, t_id, credits))
    conn.commit(); conn.close()
    return redirect('/classes?tab=subjects')

@app.route('/subjects/delete/<int:id>', methods=['POST'])
@role_required('admin')
def delete_subject(id):
    conn = get_db(); conn.execute("DELETE FROM subjects WHERE id=?", (id,)); conn.commit(); conn.close()
    return redirect('/classes')

# ── Attendance ────────────────────────────────────────────────────────────────

@app.route('/attendance')
@login_required
def attendance():
    conn = get_db()
    role = session.get('role')
    if role == 'teacher':
        tid = session.get('linked_id')
        classes = conn.execute("SELECT * FROM classes WHERE teacher_id=? ORDER BY name", (tid,)).fetchall()
        # Auto-select the teacher's classroom if none chosen
        if not request.args.get('class_id') and classes:
            conn.close()
            return redirect(f"/attendance?class_id={classes[0]['id']}&date={request.args.get('date', date.today().isoformat())}")
    else:
        classes  = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
    sel_class = request.args.get('class_id')
    sel_date  = request.args.get('date', date.today().isoformat())
    subjects = conn.execute("SELECT * FROM subjects WHERE class_id=? ORDER BY name", (sel_class,)).fetchall() if sel_class else []
    students  = []; att_map = {}
    if sel_class:
        students = conn.execute("SELECT * FROM students WHERE class_id=? AND status='Active' ORDER BY first_name", (sel_class,)).fetchall()
        records  = conn.execute("SELECT * FROM attendance WHERE date=?", (sel_date,)).fetchall()
        att_map  = {r['student_id']: r['status'] for r in records}
    if role == 'teacher':
        recent = conn.execute('''SELECT a.*, s.first_name||' '||s.last_name as student_name
                                 FROM attendance a JOIN students s ON a.student_id=s.id
                                 WHERE s.class_id IN (SELECT id FROM classes WHERE teacher_id=?)
                                 ORDER BY a.date DESC, a.id DESC LIMIT 50''', (tid,)).fetchall()
    else:
        recent = conn.execute('''SELECT a.*, s.first_name||' '||s.last_name as student_name
                                 FROM attendance a JOIN students s ON a.student_id=s.id
                                 ORDER BY a.date DESC, a.id DESC LIMIT 50''').fetchall()
    conn.close()
    return render_template('attendance.html', classes=classes, subjects=subjects,
                           students=students, selected_class=sel_class,
                           selected_date=sel_date, attendance_map=att_map, recent=recent)

@app.route('/attendance/save', methods=['POST'])
@role_required('admin','teacher')
def save_attendance():
    d = request.form; att_date = d['date']; subject_id = d.get('subject_id') or None
    conn = get_db()
    conn.execute("DELETE FROM attendance WHERE date=? AND student_id IN (SELECT id FROM students WHERE class_id=?)",
                 (att_date, d['class_id']))
    for key, val in d.items():
        if key.startswith('att_'):
            conn.execute("INSERT INTO attendance (student_id,date,status,subject_id,recorded_by) VALUES (?,?,?,?,?)",
                         (key.replace('att_',''), att_date, val, subject_id, session.get('user_id')))
    conn.commit(); conn.close()
    return redirect(f"/attendance?class_id={d['class_id']}&date={att_date}")

# ── Grades ────────────────────────────────────────────────────────────────────

@app.route('/grades')
@login_required
def grades():
    conn = get_db()
    role = session.get('role')
    if role == 'teacher':
        tid = session.get('linked_id')
        classes = conn.execute("SELECT * FROM classes WHERE teacher_id=? ORDER BY name", (tid,)).fetchall()
        # Auto-select the teacher's classroom if none chosen
        if not request.args.get('class_id') and classes:
            conn.close()
            return redirect(f"/grades?class_id={classes[0]['id']}")
    else:
        classes  = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
        subjects = conn.execute("SELECT * FROM subjects ORDER BY name").fetchall()
    sel_cls  = request.args.get('class_id',''); sel_sub = request.args.get('subject_id','')
    # Only show subjects for the selected classroom (or teacher's classes if none selected)
    if sel_cls:
        subjects = conn.execute("SELECT * FROM subjects WHERE class_id=? ORDER BY name", (sel_cls,)).fetchall()
    sg_list  = []
    if sel_cls and sel_sub:
        sts = conn.execute("SELECT * FROM students WHERE class_id=? AND status='Active' ORDER BY first_name", (sel_cls,)).fetchall()
        for s in sts:
            g = conn.execute("SELECT * FROM grades WHERE student_id=? AND subject_id=? ORDER BY date DESC LIMIT 1", (s['id'],sel_sub)).fetchone()
            sg_list.append({'student': s, 'grade': g})
    if role == 'teacher':
        all_g = conn.execute('''SELECT g.*, s.first_name||' '||s.last_name as student_name, sub.name as subject_name
                                 FROM grades g JOIN students s ON g.student_id=s.id
                                 JOIN subjects sub ON g.subject_id=sub.id
                                 WHERE s.class_id IN (SELECT id FROM classes WHERE teacher_id=?)
                                 ORDER BY g.date DESC LIMIT 50''', (tid,)).fetchall()
    else:
        all_g = conn.execute('''SELECT g.*, s.first_name||' '||s.last_name as student_name, sub.name as subject_name
                                 FROM grades g JOIN students s ON g.student_id=s.id
                                 JOIN subjects sub ON g.subject_id=sub.id
                                 ORDER BY g.date DESC LIMIT 50''').fetchall()
    conn.close()
    return render_template('grades.html', classes=classes, subjects=subjects,
                           students_grades=sg_list, selected_class=sel_cls,
                           selected_subject=sel_sub, all_grades=all_g)

@app.route('/grades/save', methods=['POST'])
@role_required('admin','teacher')
def save_grades():
    d = request.form; conn = get_db()
    for key, val in d.items():
        if key.startswith('score_') and val:
            sid = key.replace('score_',''); score = float(val)
            conn.execute('''INSERT INTO grades (student_id,subject_id,exam_type,score,max_score,
                grade_letter,term,academic_year,date,recorded_by,comments) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (sid,d['subject_id'],d.get('exam_type','Test'),score,float(d.get('max_score',100)),
                 get_grade_letter(score),d.get('term'),d.get('academic_year'),
                 date.today().isoformat(),session.get('user_id'),d.get('comment_'+sid,'')))
    conn.commit(); conn.close()
    return redirect(f"/grades?class_id={d.get('class_id','')}&subject_id={d.get('subject_id','')}")

def get_grade_letter(s):
    if s >= 96: return 'A+'
    if s >= 92: return 'A'
    if s >= 89: return 'A-'
    if s >= 86: return 'B+'
    if s >= 82: return 'B'
    if s >= 79: return 'B-'
    if s >= 76: return 'C+'
    if s >= 72: return 'C'
    if s >= 69: return 'C-'
    if s >= 60: return 'D'
    if s >= 50: return 'F'
    return 'F'

GRADE_GPA = {'A+':4.5,'A':4.0,'A-':3.8,'B+':3.5,'B':3.0,'B-':2.8,
             'C+':2.5,'C':2.0,'C-':1.8,'D':1.0,'F':0.0}

# ── Assignments ───────────────────────────────────────────────────────────────

@app.route('/assignments')
@login_required
def assignments():
    conn = get_db()
    role = session.get('role')
    if role == 'teacher':
        tid = session.get('linked_id')
        classes  = conn.execute("SELECT * FROM classes WHERE teacher_id=? ORDER BY name", (tid,)).fetchall()
        subjects = [dict(r) for r in conn.execute('''SELECT sub.id, sub.name, sub.class_id FROM subjects sub
                                   JOIN classes c ON sub.class_id=c.id
                                   WHERE c.teacher_id=? ORDER BY sub.name''', (tid,)).fetchall()]
        rows = conn.execute('''SELECT a.*, sub.name as subject_name, c.name as class_name
                               FROM assignments a LEFT JOIN subjects sub ON a.subject_id=sub.id
                               LEFT JOIN classes c ON a.class_id=c.id
                               WHERE a.class_id IN (SELECT id FROM classes WHERE teacher_id=?)
                               ORDER BY a.due_date DESC''', (tid,)).fetchall()
    else:
        classes  = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
        subjects = [dict(r) for r in conn.execute("SELECT id, name, class_id FROM subjects ORDER BY name").fetchall()]
        rows = conn.execute('''SELECT a.*, sub.name as subject_name, c.name as class_name
                               FROM assignments a LEFT JOIN subjects sub ON a.subject_id=sub.id
                               LEFT JOIN classes c ON a.class_id=c.id
                               ORDER BY a.due_date DESC''').fetchall()
    conn.close()
    return render_template('assignments.html', assignments=rows, classes=classes, subjects=subjects, today=date.today().isoformat())

@app.route('/assignments/add', methods=['POST'])
@role_required('admin','teacher')
def add_assignment():
    d = request.form; conn = get_db()
    teacher_id = session.get('linked_id') or conn.execute(
        "SELECT id FROM teachers WHERE first_name||' '||last_name LIKE ?",
        (f"%{session.get('full_name','').split()[-1]}%",)
    ).fetchone()
    if hasattr(teacher_id, '__getitem__'): teacher_id = teacher_id['id']
    conn.execute('''INSERT INTO assignments (title,description,subject_id,class_id,teacher_id,due_date,max_score,created_at)
                    VALUES (?,?,?,?,?,?,?,?)''',
                 (d['title'],d.get('description'),d.get('subject_id') or None,d.get('class_id') or None,
                  teacher_id,d.get('due_date'),float(d.get('max_score',100)),date.today().isoformat()))
    conn.commit(); conn.close()
    back = d.get('_next', '/assignments')
    return redirect(back)

@app.route('/assignments/delete/<int:id>', methods=['POST'])
@role_required('admin','teacher')
def delete_assignment(id):
    conn = get_db(); conn.execute("DELETE FROM assignments WHERE id=?", (id,)); conn.commit(); conn.close()
    return redirect('/assignments')

# ── Timetable ─────────────────────────────────────────────────────────────────

@app.route('/timetable')
@login_required
def timetable():
    conn = get_db()
    role = session.get('role')
    if role == 'teacher':
        tid = session.get('linked_id')
        classes = conn.execute("SELECT * FROM classes WHERE teacher_id=? ORDER BY name", (tid,)).fetchall()
        if not request.args.get('class_id') and classes:
            conn.close()
            return redirect(f"/timetable?class_id={classes[0]['id']}")
    else:
        classes = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
    teachers = conn.execute("SELECT * FROM teachers WHERE status='Active' ORDER BY first_name").fetchall()
    sel_cls  = request.args.get('class_id','')
    subjects = conn.execute("SELECT * FROM subjects WHERE class_id=? ORDER BY name", (sel_cls,)).fetchall() if sel_cls else []
    schedule = {}; days = ['Monday','Tuesday','Wednesday','Thursday','Friday']
    if sel_cls:
        rows = conn.execute('''SELECT t.*, sub.name as subject_name,
                                      teach.first_name||' '||teach.last_name as teacher_name
                               FROM timetable t LEFT JOIN subjects sub ON t.subject_id=sub.id
                               LEFT JOIN teachers teach ON t.teacher_id=teach.id
                               WHERE t.class_id=? ORDER BY t.start_time''', (sel_cls,)).fetchall()
        for day in days: schedule[day] = [r for r in rows if r['day']==day]
    conn.close()
    return render_template('timetable.html', classes=classes, subjects=subjects,
                           teachers=teachers, selected_class=sel_cls, schedule=schedule, days=days)

@app.route('/timetable/add', methods=['POST'])
@role_required('admin','teacher')
def add_timetable():
    d = request.form; conn = get_db()
    conn.execute("INSERT INTO timetable (class_id,subject_id,teacher_id,day,start_time,end_time,room) VALUES (?,?,?,?,?,?,?)",
        (d['class_id'],d['subject_id'],d.get('teacher_id') or None,d['day'],d['start_time'],d['end_time'],d.get('room')))
    conn.commit(); conn.close(); return redirect('/timetable?class_id='+d['class_id'])

@app.route('/timetable/delete/<int:id>', methods=['POST'])
@role_required('admin','teacher')
def delete_timetable(id):
    cls = request.form.get('class_id','')
    conn = get_db(); conn.execute("DELETE FROM timetable WHERE id=?", (id,)); conn.commit(); conn.close()
    return redirect('/timetable?class_id='+cls)

# ── Announcements ─────────────────────────────────────────────────────────────

@app.route('/announcements')
@login_required
def announcements():
    conn = get_db()
    rows = conn.execute('''SELECT a.*, u.full_name as author FROM announcements a
                           LEFT JOIN users u ON a.created_by=u.id
                           ORDER BY a.is_pinned DESC, a.id DESC''').fetchall()
    classes = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
    conn.close()
    return render_template('announcements.html', announcements=rows, classes=classes)

@app.route('/announcements/add', methods=['POST'])
@role_required('admin','teacher')
def add_announcement():
    d = request.form; conn = get_db()
    conn.execute('''INSERT INTO announcements (title,body,audience,class_id,created_by,created_at,is_pinned)
                    VALUES (?,?,?,?,?,?,?)''',
                 (d['title'],d['body'],d.get('audience','all'),d.get('class_id') or None,
                  session.get('user_id'),date.today().isoformat(),int(d.get('is_pinned',0))))
    conn.commit(); conn.close(); return redirect('/announcements')

@app.route('/announcements/delete/<int:id>', methods=['POST'])
@role_required('admin')
def delete_announcement(id):
    conn = get_db(); conn.execute("DELETE FROM announcements WHERE id=?", (id,)); conn.commit(); conn.close()
    return redirect('/announcements')

# ── Calendar ──────────────────────────────────────────────────────────────────

def _events_for_role(conn, role):
    if role == 'admin':
        return conn.execute("SELECT * FROM events ORDER BY event_date, start_time").fetchall()
    audience_map = {'teacher': "('all','teachers')", 'parent': "('all','parents')",
                    'student': "('all','students')", 'accountant': "('all','teachers')"}
    aud = audience_map.get(role, "('all')")
    return conn.execute(f"SELECT * FROM events WHERE audience IN {aud} ORDER BY event_date, start_time").fetchall()

def _events_by_date(events):
    grouped = {}
    for e in events:
        key = e['event_date']
        if key not in grouped:
            grouped[key] = []
        grouped[key].append({'id': e['id'], 'title': e['title'],
                              'description': e['description'] or '',
                              'start_time': e['start_time'] or '',
                              'end_time': e['end_time'] or '',
                              'event_type': e['event_type'],
                              'color': e['color'], 'audience': e['audience']})
    return grouped

@app.route('/calendar')
@login_required
def calendar_view():
    conn = get_db()
    role = session.get('role', '')
    events = _events_for_role(conn, role)
    grouped = _events_by_date(events)
    classes = conn.execute("SELECT * FROM classes ORDER BY name").fetchall()
    conn.close()
    return render_template('calendar.html', events_by_date=grouped, events=events,
                           classes=classes, today=date.today().isoformat())

@app.route('/calendar/add', methods=['POST'])
@role_required('admin', 'teacher')
def add_event():
    d = request.form
    conn = get_db()
    conn.execute('''INSERT INTO events (title,description,event_date,start_time,end_time,
                    event_type,audience,class_id,color,created_by,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                 (d['title'], d.get('description'), d['event_date'],
                  d.get('start_time') or None, d.get('end_time') or None,
                  d.get('event_type','General'), d.get('audience','all'),
                  d.get('class_id') or None, d.get('color','#4f46e5'),
                  session['user_id'], datetime.now().isoformat()))
    conn.commit()
    audience = d.get('audience','all')
    title    = d['title']
    ev_date  = d['event_date']
    body     = f"A new event has been scheduled: \"{title}\" on {ev_date}."
    if d.get('description'):
        body += f"\n{d['description']}"
    role_map = {'all': ['parent','teacher','student'],
                'parents':   ['parent'],
                'teachers':  ['teacher'],
                'students':  ['student'],
                'staff':     ['teacher','accountant']}
    notify_roles = role_map.get(audience, ['parent','teacher','student'])
    placeholders = ','.join(['?'] * len(notify_roles))
    users = conn.execute(f"SELECT id FROM users WHERE role IN ({placeholders}) AND is_active=1",
                         notify_roles).fetchall()
    for u in users:
        conn.execute('''INSERT INTO messages (from_user,to_user,subject,body,sent_at,is_read)
                        VALUES (?,?,?,?,?,0)''',
                     (session['user_id'], u['id'], f"New Event: {title}",
                      body, datetime.now().isoformat()))
    conn.commit(); conn.close()
    audit('ADD_EVENT', 'events', details={'title': title})
    return redirect(d.get('next') or '/calendar')

@app.route('/calendar/delete/<int:id>', methods=['POST'])
@role_required('admin')
def delete_event(id):
    conn = get_db(); conn.execute("DELETE FROM events WHERE id=?", (id,)); conn.commit(); conn.close()
    return redirect('/calendar')

@app.route('/calendar/print')
@login_required
def calendar_print_view():
    from calendar import monthcalendar
    month_str = request.args.get('month', date.today().strftime('%Y-%m'))
    try:
        year, month = int(month_str[:4]), int(month_str[5:7])
    except:
        year, month = date.today().year, date.today().month
    conn = get_db()
    role = session.get('role', '')
    start = f"{year}-{month:02d}-01"
    import calendar as cal_mod
    last_day = cal_mod.monthrange(year, month)[1]
    end = f"{year}-{month:02d}-{last_day:02d}"
    if role == 'admin':
        events = conn.execute(
            "SELECT * FROM events WHERE event_date BETWEEN ? AND ? ORDER BY event_date, start_time",
            (start, end)).fetchall()
    else:
        audience_map = {'teacher': "('all','teachers')", 'parent': "('all','parents')",
                        'student': "('all','students')", 'accountant': "('all','teachers')"}
        aud = audience_map.get(role, "('all')")
        events = conn.execute(
            f"SELECT * FROM events WHERE event_date BETWEEN ? AND ? AND audience IN {aud} ORDER BY event_date, start_time",
            (start, end)).fetchall()
    conn.close()
    grouped = {}
    for e in events:
        grouped.setdefault(e['event_date'], []).append(e)
    weeks = monthcalendar(year, month)
    month_name = datetime(year, month, 1).strftime('%B %Y')
    return render_template('calendar_print.html', weeks=weeks, year=year, month=month,
                           month_name=month_name, grouped=grouped,
                           today=date.today().isoformat())


# ── Telephone Directory ───────────────────────────────────────────────────────

@app.route('/directory')
@login_required
def directory():
    if not can('directory'):
        return render_template('error.html', message='Access denied.'), 403
    role = session.get('role', '')
    conn = get_db()

    staff = conn.execute('''
        SELECT t.*, t.first_name || ' ' || t.last_name AS full_name,
               GROUP_CONCAT(DISTINCT sub.name) AS subjects
        FROM teachers t
        LEFT JOIN subjects sub ON sub.teacher_id = t.id
        WHERE t.status = 'Active'
        GROUP BY t.id
        ORDER BY t.first_name, t.last_name
    ''').fetchall()

    parents = []
    if role in ('admin', 'teacher', 'accountant', 'frontdesk'):
        parents = conn.execute('''
            SELECT s.parent_name, s.parent_phone, s.parent_email,
                   s.father_name, s.father_phone, s.father_email,
                   s.first_name || ' ' || s.last_name AS student_name,
                   s.photo, c.name AS class_name
            FROM students s
            LEFT JOIN classes c ON s.class_id = c.id
            WHERE s.status = 'Active'
              AND ((s.parent_name IS NOT NULL AND s.parent_name != '')
                OR (s.father_name IS NOT NULL AND s.father_name != ''))
            ORDER BY s.first_name, s.last_name
        ''').fetchall()

    students = []
    if role in ('admin', 'teacher'):
        students = conn.execute('''
            SELECT s.*, s.first_name || ' ' || s.last_name AS full_name,
                   c.name AS class_name
            FROM students s
            LEFT JOIN classes c ON s.class_id = c.id
            WHERE s.status = 'Active'
            ORDER BY s.first_name, s.last_name
        ''').fetchall()

    conn.close()
    return render_template('directory.html',
                           staff=staff, parents=parents, students=students)


@app.route('/messages')
@login_required
def messages_view():
    conn = get_db()
    msgs = conn.execute('''SELECT m.*, u.full_name as sender_name FROM messages m
                           LEFT JOIN users u ON m.from_user=u.id
                           WHERE m.to_user=? ORDER BY m.sent_at DESC LIMIT 50''',
                        (session['user_id'],)).fetchall()
    conn.execute("UPDATE messages SET is_read=1 WHERE to_user=?", (session['user_id'],))
    conn.commit(); conn.close()
    return render_template('messages.html', messages=msgs)

@app.route('/messages/mark-read', methods=['POST'])
@login_required
def mark_messages_read():
    conn = get_db()
    conn.execute("UPDATE messages SET is_read=1 WHERE to_user=?", (session['user_id'],))
    conn.commit(); conn.close()
    return ('', 204)

# ── Admissions ────────────────────────────────────────────────────────────────

@app.route('/admin/admissions')
@role_required('admin')
def admin_admissions():
    conn = get_db()
    rows = conn.execute("SELECT * FROM admissions ORDER BY submitted_at DESC").fetchall()
    conn.close()
    return render_template('admin_admissions.html', admissions=rows)

@app.route('/admin/admissions/review/<int:id>', methods=['POST'])
@role_required('admin')
def review_admission(id):
    d = request.form; conn = get_db()
    conn.execute("UPDATE admissions SET status=?,notes=?,reviewed_by=? WHERE id=?",
                 (d['status'],d.get('notes'),session.get('user_id'),id))
    conn.commit(); conn.close()
    return redirect('/admin/admissions')

# ── Finances ──────────────────────────────────────────────────────────────────

@app.route('/reports')
@role_required('admin','accountant')
def reports():
    conn = get_db()
    from_date = request.args.get('from_date', '')
    to_date   = request.args.get('to_date',   '')
    # Default: current academic year (Sept–Aug)
    today = date.today()
    year_start = f"{today.year if today.month >= 9 else today.year-1}-09-01"
    year_end   = f"{today.year+1 if today.month >= 9 else today.year}-08-31"
    fd = from_date or year_start
    td = to_date   or year_end

    # ── Financial summary ──────────────────────────────────────────────────────
    income_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM finances WHERE type='Income' AND date BETWEEN ? AND ?",
        (fd, td)).fetchone()[0]
    expense_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM finances WHERE type='Expense' AND date BETWEEN ? AND ?",
        (fd, td)).fetchone()[0]
    fees_collected = conn.execute(
        "SELECT COALESCE(SUM(f.paid_amount),0) FROM fees f "
        "JOIN students s ON f.student_id=s.id", ()).fetchone()[0]
    fees_outstanding = conn.execute(
        "SELECT COALESCE(SUM(amount-paid_amount),0) FROM fees WHERE status != 'Paid'", ()).fetchone()[0]

    # Income by category
    income_by_cat = conn.execute(
        "SELECT category, COALESCE(SUM(amount),0) as total FROM finances "
        "WHERE type='Income' AND date BETWEEN ? AND ? GROUP BY category ORDER BY total DESC",
        (fd, td)).fetchall()

    # Monthly income for the period
    monthly_income = conn.execute(
        "SELECT strftime('%Y-%m', date) as month, COALESCE(SUM(amount),0) as total "
        "FROM finances WHERE type='Income' AND date BETWEEN ? AND ? "
        "GROUP BY month ORDER BY month", (fd, td)).fetchall()

    # Outstanding fees by student
    outstanding_students = conn.execute(
        "SELECT s.first_name||' '||s.last_name as name, s.student_id as sid, "
        "c.name as class_name, COALESCE(SUM(f.amount-f.paid_amount),0) as owed "
        "FROM fees f JOIN students s ON f.student_id=s.id "
        "LEFT JOIN classes c ON s.class_id=c.id "
        "WHERE f.status != 'Paid' GROUP BY f.student_id ORDER BY owed DESC LIMIT 25",
        ()).fetchall()

    # ── Student summary ────────────────────────────────────────────────────────
    student_stats = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM students "
        "WHERE student_type IS NULL OR student_type='Enrolled' GROUP BY status"
    ).fetchall()
    students_by_class = conn.execute(
        "SELECT c.name as class_name, COUNT(s.id) as cnt "
        "FROM students s LEFT JOIN classes c ON s.class_id=c.id "
        "WHERE s.status='Active' AND (s.student_type IS NULL OR s.student_type='Enrolled') "
        "GROUP BY c.name ORDER BY cnt DESC"
    ).fetchall()

    # ── Attendance summary ─────────────────────────────────────────────────────
    att_summary = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM attendance "
        "WHERE date BETWEEN ? AND ? GROUP BY status", (fd, td)).fetchall()
    low_attendance = conn.execute(
        "SELECT s.first_name||' '||s.last_name as name, s.student_id as sid, "
        "c.name as class_name, "
        "COUNT(*) as total_days, "
        "SUM(CASE WHEN a.status='Present' THEN 1 ELSE 0 END) as present_days "
        "FROM attendance a JOIN students s ON a.student_id=s.id "
        "LEFT JOIN classes c ON s.class_id=c.id "
        "WHERE a.date BETWEEN ? AND ? "
        "GROUP BY a.student_id HAVING total_days > 0 "
        "ORDER BY (present_days*1.0/total_days) ASC LIMIT 10",
        (fd, td)).fetchall()

    conn.close()

    # ── Payroll report (reads from separate payroll DB) ────────────────────────
    _payroll_db = os.path.join(_APP_DIR, 'payroll_app', 'payroll.db')
    pay_year = request.args.get('pay_year', str(today.year))
    payroll_by_emp = []; payroll_totals = {}; payroll_grand_total = 0
    payroll_years = [today.year, today.year - 1]
    if os.path.exists(_payroll_db):
        try:
            pc = sqlite3.connect(_payroll_db)
            pc.row_factory = sqlite3.Row
            _yrs = pc.execute("SELECT DISTINCT year FROM payments ORDER BY year DESC").fetchall()
            if _yrs:
                payroll_years = [r['year'] for r in _yrs]
            payroll_by_emp = pc.execute("""
                SELECT name,
                       SUM(amount)                                              AS total_paid,
                       COUNT(*)                                                 AS num_payments,
                       SUM(CASE WHEN period='W'  THEN amount ELSE 0 END)       AS weekly_total,
                       SUM(CASE WHEN period='BW' THEN amount ELSE 0 END)       AS biweekly_total,
                       SUM(CASE WHEN period='M'  THEN amount ELSE 0 END)       AS monthly_total
                FROM payments WHERE year=?
                GROUP BY name ORDER BY total_paid DESC
            """, (pay_year,)).fetchall()
            payroll_grand_total = sum(r['total_paid'] for r in payroll_by_emp)
            payroll_totals = {
                'W':  sum(r['weekly_total']   for r in payroll_by_emp),
                'BW': sum(r['biweekly_total'] for r in payroll_by_emp),
                'M':  sum(r['monthly_total']  for r in payroll_by_emp),
            }
            pc.close()
        except Exception:
            pass

    return render_template('reports.html',
        from_date=fd, to_date=td,
        income_total=income_total, expense_total=expense_total,
        fees_collected=fees_collected, fees_outstanding=fees_outstanding,
        income_by_cat=income_by_cat, monthly_income=monthly_income,
        outstanding_students=outstanding_students,
        student_stats=student_stats, students_by_class=students_by_class,
        att_summary=att_summary, low_attendance=low_attendance,
        payroll_by_emp=payroll_by_emp, payroll_totals=payroll_totals,
        payroll_grand_total=payroll_grand_total,
        payroll_years=payroll_years, pay_year=pay_year)


@app.route('/reports/export/<report_type>')
@role_required('admin','accountant')
def export_report(report_type):
    import csv, io
    from_date = request.args.get('from_date', '')
    to_date   = request.args.get('to_date',   '')
    today = date.today()
    fd = from_date or f"{today.year if today.month >= 9 else today.year-1}-09-01"
    td = to_date   or f"{today.year+1 if today.month >= 9 else today.year}-08-31"
    conn = get_db()
    output = io.StringIO()
    writer = csv.writer(output)

    if report_type == 'students':
        writer.writerow(['Student ID','First Name','Last Name','Class','Status','Enrollment Date','Graduation Date','Parent','Parent Phone','Email'])
        rows = conn.execute(
            "SELECT s.student_id,s.first_name,s.last_name,c.name,s.status,"
            "s.enrollment_date,s.graduation_date,s.parent_name,s.parent_phone,s.email "
            "FROM students s LEFT JOIN classes c ON s.class_id=c.id "
            "WHERE s.student_type IS NULL OR s.student_type='Enrolled' "
            "ORDER BY s.first_name").fetchall()
        for r in rows: writer.writerow(list(r))
        fname = f"Students_{date.today()}.csv"

    elif report_type == 'outstanding':
        writer.writerow(['Student ID','Student Name','Class','Fee Type','Amount','Paid','Balance','Due Date','Status'])
        rows = conn.execute(
            "SELECT s.student_id, s.first_name||' '||s.last_name, c.name, "
            "f.fee_type, f.amount, f.paid_amount, f.amount-f.paid_amount, f.due_date, f.status "
            "FROM fees f JOIN students s ON f.student_id=s.id "
            "LEFT JOIN classes c ON s.class_id=c.id "
            "WHERE f.status != 'Paid' ORDER BY f.amount-f.paid_amount DESC").fetchall()
        for r in rows: writer.writerow(list(r))
        fname = f"OutstandingFees_{date.today()}.csv"

    elif report_type == 'income':
        writer.writerow(['Date','Type','Category','Description','Amount','Payment Method','Student','Created By'])
        rows = conn.execute(
            "SELECT f.date,f.type,f.category,f.description,f.amount,f.payment_method,"
            "s.first_name||' '||s.last_name, u.full_name "
            "FROM finances f LEFT JOIN students s ON f.student_id=s.id "
            "LEFT JOIN users u ON f.created_by=u.id "
            "WHERE f.date BETWEEN ? AND ? ORDER BY f.date DESC", (fd, td)).fetchall()
        for r in rows: writer.writerow(list(r))
        fname = f"Income_{fd}_to_{td}.csv"

    elif report_type == 'attendance':
        writer.writerow(['Date','Student ID','Student Name','Class','Subject','Status','Remarks'])
        rows = conn.execute(
            "SELECT a.date, s.student_id, s.first_name||' '||s.last_name, c.name, "
            "sub.name, a.status, a.remarks "
            "FROM attendance a JOIN students s ON a.student_id=s.id "
            "LEFT JOIN classes c ON s.class_id=c.id "
            "LEFT JOIN subjects sub ON a.subject_id=sub.id "
            "WHERE a.date BETWEEN ? AND ? ORDER BY a.date DESC", (fd, td)).fetchall()
        for r in rows: writer.writerow(list(r))
        fname = f"Attendance_{fd}_to_{td}.csv"

    elif report_type == 'pl':
        # Profit & Loss summary export (QuickBooks-friendly)
        pay_year = request.args.get('pay_year', str(today.year))
        income = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finances WHERE type='Income' AND date BETWEEN ? AND ?", (fd,td)).fetchone()[0]
        fees_c = conn.execute("SELECT COALESCE(SUM(f.paid_amount),0) FROM fees f JOIN students s ON f.student_id=s.id").fetchone()[0]
        expenses = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finances WHERE type='Expense' AND date BETWEEN ? AND ?", (fd,td)).fetchone()[0]
        payroll = 0.0
        _payroll_db = os.path.join(_APP_DIR, 'payroll_app', 'payroll.db')
        if os.path.exists(_payroll_db):
            pc = sqlite3.connect(_payroll_db)
            payroll = pc.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE year=?", (pay_year,)).fetchone()[0]
            pc.close()
        writer.writerow([f"{get_setting('school_name','School')} — Profit & Loss Statement"])
        writer.writerow(['Period', f'{fd} to {td}', '', 'Payroll Year', pay_year])
        writer.writerow([])
        writer.writerow(['REVENUE', '', 'AMOUNT'])
        writer.writerow(['Income (Finance Records)', '', f'{income:.2f}'])
        writer.writerow(['Student Fees Collected', '', f'{fees_c:.2f}'])
        writer.writerow(['Total Revenue', '', f'{income + fees_c:.2f}'])
        writer.writerow([])
        writer.writerow(['EXPENSES', '', 'AMOUNT'])
        writer.writerow(['Operating Expenses', '', f'{expenses:.2f}'])
        writer.writerow([f'Payroll ({pay_year})', '', f'{payroll:.2f}'])
        writer.writerow(['Total Expenses', '', f'{expenses + payroll:.2f}'])
        writer.writerow([])
        net = (income + fees_c) - (expenses + payroll)
        writer.writerow(['NET PROFIT / (LOSS)', '', f'{net:.2f}'])
        # Category breakdown
        writer.writerow([])
        writer.writerow(['INCOME BY CATEGORY'])
        cats = conn.execute("SELECT category, COALESCE(SUM(amount),0) as total FROM finances WHERE type='Income' AND date BETWEEN ? AND ? GROUP BY category ORDER BY total DESC", (fd,td)).fetchall()
        for c in cats: writer.writerow([c['category'] or 'Uncategorized', '', f'{c["total"]:.2f}'])
        fname = f"ProfitLoss_{fd}_to_{td}.csv"

    elif report_type == 'payroll':
        pay_year = request.args.get('pay_year', str(today.year))
        _payroll_db = os.path.join(_APP_DIR, 'payroll_app', 'payroll.db')
        writer.writerow(['Employee','Pay Type','Weekly Paid','Bi-Weekly Paid','Monthly Paid','# Payments','Total Paid'])
        if os.path.exists(_payroll_db):
            pc = sqlite3.connect(_payroll_db)
            pc.row_factory = sqlite3.Row
            rows = pc.execute("""
                SELECT name,
                       SUM(CASE WHEN period='W'  THEN amount ELSE 0 END) as w,
                       SUM(CASE WHEN period='BW' THEN amount ELSE 0 END) as bw,
                       SUM(CASE WHEN period='M'  THEN amount ELSE 0 END) as m,
                       COUNT(*) as n, SUM(amount) as total
                FROM payments WHERE year=? GROUP BY name ORDER BY total DESC
            """, (pay_year,)).fetchall()
            for r in rows:
                pt = ('Weekly' if r['w'] > 0 and r['bw'] == 0 and r['m'] == 0 else
                      'Bi-Weekly' if r['bw'] > 0 and r['w'] == 0 and r['m'] == 0 else
                      'Monthly' if r['m'] > 0 and r['w'] == 0 and r['bw'] == 0 else 'Mixed')
                writer.writerow([r['name'], pt, f"{r['w']:.2f}", f"{r['bw']:.2f}", f"{r['m']:.2f}", r['n'], f"{r['total']:.2f}"])
            pc.close()
        fname = f"Payroll_{pay_year}.csv"

    else:
        conn.close()
        return "Unknown report type", 404

    conn.close()
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=fname)


@app.route('/finances')
@role_required('admin','accountant')
def finances():
    conn = get_db()
    transactions = conn.execute('''SELECT f.*, s.first_name||' '||s.last_name as student_name,
                                          u.full_name as created_by_name
                                   FROM finances f LEFT JOIN students s ON f.student_id=s.id
                                   LEFT JOIN users u ON f.created_by=u.id
                                   ORDER BY f.date DESC, f.id DESC''').fetchall()
    fees = conn.execute('''SELECT fe.*, s.first_name||' '||s.last_name as student_name
                           FROM fees fe JOIN students s ON fe.student_id=s.id
                           ORDER BY fe.due_date DESC''').fetchall()
    students = conn.execute("SELECT * FROM students WHERE status='Active' ORDER BY first_name").fetchall()
    total_income  = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finances WHERE type='Income'").fetchone()[0]
    total_expense = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finances WHERE type='Expense'").fetchone()[0]
    total_fees_due= conn.execute("SELECT COALESCE(SUM(amount),0) FROM fees WHERE status!='Paid'").fetchone()[0]
    total_fees_col= conn.execute("SELECT COALESCE(SUM(paid_amount),0) FROM fees").fetchone()[0]
    unsynced      = conn.execute("SELECT COUNT(*) FROM finances WHERE qb_synced=0").fetchone()[0]
    qb_logs       = conn.execute('''SELECT q.*, u.full_name as synced_by_name
                                    FROM qb_sync_log q LEFT JOIN users u ON q.synced_by=u.id
                                    ORDER BY q.id DESC LIMIT 10''').fetchall()
    invoices      = conn.execute('''SELECT i.*, s.first_name||' '||s.last_name AS student_name,
                                           (SELECT COALESCE(SUM(amount),0) FROM invoice_items WHERE invoice_id=i.id) AS total
                                    FROM invoices i JOIN students s ON i.student_id=s.id
                                    ORDER BY i.id DESC''').fetchall()
    # Chart data: monthly income vs expense for current calendar year
    cur_year = date.today().year
    monthly_chart = conn.execute(
        "SELECT strftime('%m', date) as m, type, COALESCE(SUM(amount),0) as total "
        "FROM finances WHERE strftime('%Y', date)=? GROUP BY m, type ORDER BY m",
        (str(cur_year),)).fetchall()
    # Build 12-slot arrays
    inc_by_month  = [0.0] * 12
    exp_by_month  = [0.0] * 12
    for row in monthly_chart:
        idx = int(row['m']) - 1
        if row['type'] == 'Income':
            inc_by_month[idx] = round(float(row['total']), 2)
        else:
            exp_by_month[idx] = round(float(row['total']), 2)
    # Income by category (top 6)
    cat_chart = conn.execute(
        "SELECT category, COALESCE(SUM(amount),0) as total FROM finances "
        "WHERE type='Income' GROUP BY category ORDER BY total DESC LIMIT 6").fetchall()
    # Fee status breakdown
    fee_status = conn.execute(
        "SELECT status, COALESCE(SUM(amount),0) as total FROM fees GROUP BY status").fetchall()
    conn.close()
    return render_template('finances.html', transactions=transactions, fees=fees,
                           students=students, total_income=total_income, total_expense=total_expense,
                           total_fees_due=total_fees_due, total_fees_collected=total_fees_col,
                           unsynced=unsynced, qb_logs=qb_logs, invoices=invoices,
                           inc_by_month=inc_by_month, exp_by_month=exp_by_month,
                           cat_chart=cat_chart, fee_status=fee_status, cur_year=cur_year)

@app.route('/finances/add', methods=['POST'])
@role_required('admin','accountant')
def add_finance():
    d = request.form; conn = get_db()
    conn.execute('''INSERT INTO finances (type,category,description,amount,date,student_id,
        payment_method,status,reference,created_by) VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (d['type'],d['category'],d.get('description'),float(d['amount']),
         d.get('date',date.today().isoformat()),d.get('student_id') or None,
         d.get('payment_method'),d.get('status','Completed'),d.get('reference'),session.get('user_id')))
    conn.commit(); conn.close(); return redirect('/finances')

@app.route('/finances/delete/<int:id>', methods=['POST'])
@role_required('admin')
def delete_finance(id):
    conn = get_db(); conn.execute("DELETE FROM finances WHERE id=?", (id,)); conn.commit(); conn.close()
    return redirect('/finances')

@app.route('/fees/add', methods=['POST'])
@role_required('admin','accountant')
def add_fee():
    d = request.form; conn = get_db()
    conn.execute('''INSERT INTO fees (student_id,fee_type,amount,due_date,paid_amount,
        status,academic_year,term,created_by) VALUES (?,?,?,?,?,?,?,?,?)''',
        (d['student_id'],d['fee_type'],float(d['amount']),d.get('due_date'),
         float(d.get('paid_amount') or 0),d.get('status','Unpaid'),
         d.get('academic_year'),d.get('term'),session.get('user_id')))
    conn.commit(); conn.close()
    return redirect(d.get('next') or '/finances')

@app.route('/fees/pay/<int:id>', methods=['POST'])
@role_required('admin','accountant','frontdesk')
def pay_fee(id):
    d = request.form; conn = get_db()
    fee           = conn.execute("SELECT * FROM fees WHERE id=?", (id,)).fetchone()
    pay_amount    = float(d.get('pay_amount') or 0)
    credit_amount = float(d.get('credit_amount') or 0)
    method        = d.get('payment_method', 'Cash')
    # Validate credit against actual balance
    if credit_amount > 0:
        available = get_credit_balance(conn, fee['student_id'])
        credit_amount = min(credit_amount, available,
                            float(fee['amount']) - float(fee['paid_amount']))
        credit_amount = round(credit_amount, 2)
    total_applied = round(pay_amount + credit_amount, 2)
    new_paid      = round(float(fee['paid_amount']) + total_applied, 2)
    fee_status    = 'Paid' if new_paid >= float(fee['amount']) else 'Partial'
    conn.execute("UPDATE fees SET paid_amount=?,status=? WHERE id=?", (new_paid, fee_status, id))
    txn_id = None
    if pay_amount > 0:
        cur = conn.execute(
            "INSERT INTO finances (type,category,description,amount,date,"
            "student_id,payment_method,status,created_by) VALUES (?,?,?,?,?,?,?,?,?)",
            ('Income','Fee Payment', f"Fee: {fee['fee_type']}", pay_amount,
             date.today().isoformat(), fee['student_id'], method, 'Completed', session.get('user_id')))
        txn_id = cur.lastrowid
    if credit_amount > 0:
        conn.execute(
            "INSERT INTO student_credits (student_id,amount,type,description,date,fee_id,created_by)"
            " VALUES (?,?,?,?,?,?,?)",
            (fee['student_id'], -credit_amount, 'Applied',
             f"Applied to fee: {fee['fee_type']}", date.today().isoformat(),
             id, session.get('user_id')))
    conn.commit(); conn.close()
    back = d.get('next') or '/finances'
    if txn_id:
        return redirect(f'/fees/receipt/{id}?txn={txn_id}&back={back}')
    return redirect(back)

@app.route('/fees/receipt/<int:fee_id>')
@login_required
def fee_receipt(fee_id):
    txn_id = request.args.get('txn', type=int)
    back   = request.args.get('back', '/finances')
    conn   = get_db()
    fee = conn.execute('''SELECT f.*, s.first_name||' '||s.last_name AS student_name,
                                  s.student_id AS student_code, s.student_type,
                                  s.parent_name, s.phone, s.email
                           FROM fees f JOIN students s ON f.student_id=s.id
                           WHERE f.id=?''', (fee_id,)).fetchone()
    if not fee:
        conn.close()
        return redirect(back)
    txn = None
    if txn_id:
        txn = conn.execute('''SELECT f.*, u.full_name as processed_by
                               FROM finances f LEFT JOIN users u ON f.created_by=u.id
                               WHERE f.id=?''', (txn_id,)).fetchone()
    all_fees = conn.execute(
        "SELECT * FROM fees WHERE student_id=?", (fee['student_id'],)).fetchall()
    conn.close()
    total_charged = sum(f['amount'] for f in all_fees)
    total_paid    = sum(f['paid_amount'] for f in all_fees)
    receipt_num   = f"RCP-{fee['student_id']}-{txn_id or fee_id:05d}"
    return render_template('receipt.html', fee=fee, txn=txn, back=back,
                           receipt_num=receipt_num,
                           total_charged=total_charged, total_paid=total_paid,
                           balance=total_charged - total_paid,
                           today=date.today().strftime('%B %d, %Y'))

# ── Payment Plans ────────────────────────────────────────────────────────────

PLAN_SCHEDULE = {
    'Monthly':   {'count': 10, 'months': 1},
    'BiMonthly': {'count': 5,  'months': 2},
    'Term':      {'count': 3,  'months': 4},
}

@app.route('/payment-plans/add', methods=['POST'])
@role_required('admin','accountant')
def add_payment_plan():
    d = request.form
    student_id  = int(d['student_id'])
    total       = float(d['total_amount'])
    plan_type   = d['plan_type']
    description = d['description']
    start_date  = d.get('start_date') or date.today().replace(day=1).isoformat()
    acad_year   = d.get('academic_year', '')
    reduce_amt  = float(d.get('reduce', 0) or 0)
    scholarship = float(d.get('scholarship', 0) or 0)
    net         = max(round(total - reduce_amt - scholarship, 2), 0)
    cfg         = PLAN_SCHEDULE[plan_type]
    count       = cfg['count']
    per_install = round(net / count, 2)
    # adjust last installment to absorb rounding difference
    last_install = round(net - per_install * (count - 1), 2)

    conn = get_db()
    cur = conn.execute(
        '''INSERT INTO payment_plans
           (student_id,description,total_amount,plan_type,installment_count,
            installment_amount,start_date,academic_year,status,created_by,created_at,
            reduce,scholarship)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (student_id, description, total, plan_type, count, per_install,
         start_date, acad_year, 'Active', session.get('user_id'), date.today().isoformat(),
         reduce_amt, scholarship))
    plan_id = cur.lastrowid

    base = date.fromisoformat(start_date)
    for i in range(count):
        due = (base + relativedelta(months=cfg['months'] * i)).isoformat()
        amt = last_install if i == count - 1 else per_install
        conn.execute(
            '''INSERT INTO plan_installments (plan_id,installment_num,due_date,amount,paid_amount,status)
               VALUES (?,?,?,?,?,?)''',
            (plan_id, i + 1, due, amt, 0, 'Unpaid'))

    conn.commit(); conn.close()
    return redirect(d.get('next') or f'/students/{student_id}')


@app.route('/payment-plans/pay/<int:inst_id>', methods=['POST'])
@role_required('admin','accountant','frontdesk')
def pay_installment(inst_id):
    d = request.form
    conn = get_db()
    inst = conn.execute("SELECT * FROM plan_installments WHERE id=?", (inst_id,)).fetchone()
    plan = conn.execute("SELECT * FROM payment_plans WHERE id=?", (inst['plan_id'],)).fetchone()
    pay_amount = float(d['pay_amount'])
    late_fee   = float(d.get('late_fee', 0) or 0)
    today_str  = date.today().isoformat()
    method     = d.get('payment_method', 'Cash')

    new_paid = round(inst['paid_amount'] + pay_amount, 2)
    status = 'Paid' if new_paid >= inst['amount'] else 'Partial'
    conn.execute("UPDATE plan_installments SET paid_amount=?, status=? WHERE id=?",
                 (new_paid, status, inst_id))
    conn.execute(
        '''INSERT INTO finances (type,category,description,amount,date,
           student_id,payment_method,status,created_by) VALUES (?,?,?,?,?,?,?,?,?)''',
        ('Income', 'Plan Payment',
         f"{plan['description']} - Installment {inst['installment_num']}",
         pay_amount, today_str, plan['student_id'], method, 'Completed', session.get('user_id')))
    if late_fee > 0:
        conn.execute(
            '''INSERT INTO finances (type,category,description,amount,date,
               student_id,payment_method,status,created_by) VALUES (?,?,?,?,?,?,?,?,?)''',
            ('Income', 'Late Fee',
             f"Late fee — {plan['description']} Installment {inst['installment_num']}",
             late_fee, today_str, plan['student_id'], method, 'Completed', session.get('user_id')))
    conn.commit(); conn.close()
    return redirect(d.get('next') or f'/students/{plan["student_id"]}')


@app.route('/payment-plans/remind/<int:inst_id>', methods=['POST'])
@role_required('admin','accountant','frontdesk')
def remind_installment(inst_id):
    conn = get_db()
    inst = conn.execute("SELECT * FROM plan_installments WHERE id=?", (inst_id,)).fetchone()
    plan = conn.execute("SELECT * FROM payment_plans WHERE id=?", (inst['plan_id'],)).fetchone()
    student = conn.execute("SELECT * FROM students WHERE id=?", (plan['student_id'],)).fetchone()

    parent_users = conn.execute(
        "SELECT id FROM users WHERE linked_id=? AND role='parent' AND is_active=1",
        (student['id'],)).fetchall()

    if parent_users:
        due_str  = inst['due_date'] or 'N/A'
        balance  = round(inst['amount'] - inst['paid_amount'], 2)
        subject  = f"Payment Reminder — {plan['description']}"
        body = (
            f"Dear Parent/Guardian of {student['first_name']} {student['last_name']},\n\n"
            f"This is a friendly reminder that Installment #{inst['installment_num']} "
            f"for {plan['description']} is due on {due_str}.\n\n"
            f"Amount Due: ${balance:,.2f}\n\n"
            f"Please ensure payment is made on time to avoid a $50 late fee.\n\n"
            f"Thank you,\n{get_setting('school_name','School')}"
        )
        now = datetime.now().isoformat()
        for pu in parent_users:
            conn.execute(
                "INSERT INTO messages (from_user,to_user,subject,body,sent_at,is_read) VALUES (?,?,?,?,?,0)",
                (session.get('user_id'), pu['id'], subject, body, now))
        conn.commit()

    conn.close()
    return redirect(request.referrer or f'/students/{plan["student_id"]}')


@app.route('/payment-plans/edit/<int:plan_id>', methods=['POST'])
@role_required('admin','accountant')
def edit_payment_plan(plan_id):
    d = request.form
    conn = get_db()
    plan = conn.execute("SELECT * FROM payment_plans WHERE id=?", (plan_id,)).fetchone()
    if not plan:
        conn.close()
        return redirect('/')

    new_total      = float(d.get('total_amount') or plan['total_amount'])
    new_reduce     = float(d.get('reduce', 0) or 0)
    new_scholarship= float(d.get('scholarship', 0) or 0)
    new_net        = max(round(new_total - new_reduce - new_scholarship, 2), 0)
    description    = d.get('description') or plan['description']
    acad_year      = d.get('academic_year', plan['academic_year'] or '')

    # Update plan header
    conn.execute(
        '''UPDATE payment_plans
           SET description=?, total_amount=?, reduce=?, scholarship=?, academic_year=?
           WHERE id=?''',
        (description, new_total, new_reduce, new_scholarship, acad_year, plan_id))

    # Recalculate only unpaid installments
    unpaid = conn.execute(
        "SELECT * FROM plan_installments WHERE plan_id=? AND status != 'Paid' ORDER BY installment_num",
        (plan_id,)).fetchall()
    already_paid = conn.execute(
        "SELECT COALESCE(SUM(paid_amount),0) FROM plan_installments WHERE plan_id=?",
        (plan_id,)).fetchone()[0]
    remaining_net = max(round(new_net - already_paid, 2), 0)
    n = len(unpaid)
    if n > 0:
        per = round(remaining_net / n, 2)
        last = round(remaining_net - per * (n - 1), 2)
        for i, inst in enumerate(unpaid):
            amt = last if i == n - 1 else per
            new_status = 'Paid' if inst['paid_amount'] >= amt else ('Partial' if inst['paid_amount'] > 0 else 'Unpaid')
            conn.execute(
                "UPDATE plan_installments SET amount=?, status=? WHERE id=?",
                (amt, new_status, inst['id']))
        # Update stored installment_amount on plan header
        conn.execute("UPDATE payment_plans SET installment_amount=? WHERE id=?", (per, plan_id))

    conn.commit(); conn.close()
    return redirect(d.get('next') or f'/students/{plan["student_id"]}')


@app.route('/payment-plans/delete/<int:plan_id>', methods=['POST'])
@role_required('admin')
def delete_payment_plan(plan_id):
    conn = get_db()
    plan = conn.execute("SELECT student_id FROM payment_plans WHERE id=?", (plan_id,)).fetchone()
    conn.execute("DELETE FROM plan_installments WHERE plan_id=?", (plan_id,))
    conn.execute("DELETE FROM payment_plans WHERE id=?", (plan_id,))
    conn.commit(); conn.close()
    student_id = plan['student_id'] if plan else ''
    return redirect(f'/students/{student_id}')


# ── Invoices ──────────────────────────────────────────────────────────────────

@app.route('/invoices/create', methods=['POST'])
@role_required('admin','accountant','frontdesk')
def create_invoice():
    d = request.form; conn = get_db()
    last = conn.execute("SELECT id FROM invoices ORDER BY id DESC LIMIT 1").fetchone()
    next_id = (last['id'] + 1) if last else 1
    inv_num = f"INV-{date.today().year}-{next_id:05d}"
    cur = conn.execute(
        '''INSERT INTO invoices (invoice_number,student_id,issue_date,due_date,status,notes,created_by,created_at)
           VALUES (?,?,?,?,?,?,?,?)''',
        (inv_num, int(d['student_id']),
         d.get('issue_date') or date.today().isoformat(),
         d.get('due_date') or None,
         'Draft', d.get('notes',''),
         session.get('user_id'), datetime.now().isoformat()))
    inv_id = cur.lastrowid
    descs   = request.form.getlist('item_desc[]')
    amounts = request.form.getlist('item_amount[]')
    for desc, amt in zip(descs, amounts):
        desc = desc.strip(); amt = amt.strip()
        if desc and amt:
            conn.execute('INSERT INTO invoice_items (invoice_id,description,amount) VALUES (?,?,?)',
                         (inv_id, desc, float(amt)))
    conn.commit(); conn.close()
    return redirect(f'/invoices/{inv_id}')


@app.route('/invoices/<int:inv_id>')
@login_required
def view_invoice(inv_id):
    conn = get_db()
    inv = conn.execute(
        '''SELECT i.*, s.first_name||' '||s.last_name AS student_name,
                  s.student_id AS student_code, s.parent_name, s.parent_email, s.parent_phone,
                  s.address, u.full_name AS created_by_name
           FROM invoices i
           JOIN students s ON i.student_id=s.id
           LEFT JOIN users u ON i.created_by=u.id
           WHERE i.id=?''', (inv_id,)).fetchone()
    if not inv:
        return redirect('/finances')
    items = conn.execute(
        'SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY id', (inv_id,)).fetchall()
    conn.close()
    total = sum(item['amount'] for item in items)
    return render_template('invoice.html', inv=inv, items=items, total=total,
                           today=date.today().strftime('%B %d, %Y'))


def _send_invoice_email(inv, items, total):
    """Send invoice HTML email to parent. Returns 'ok', 'no_email', or 'error'."""
    recipient = inv['parent_email']
    if not recipient:
        return 'no_email'

    mail_server   = os.environ.get('MAIL_SERVER', '')
    mail_port     = int(os.environ.get('MAIL_PORT', 587))
    mail_username = os.environ.get('MAIL_USERNAME', '')
    mail_password = os.environ.get('MAIL_PASSWORD', '')
    mail_from     = os.environ.get('MAIL_FROM', mail_username)
    use_tls       = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'

    if not mail_server or not mail_username or not mail_password:
        return 'error'

    rows_html = ''.join(
        f'<tr><td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;">{item["description"]}</td>'
        f'<td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;text-align:right;">${item["amount"]:.2f}</td></tr>'
        for item in items
    )

    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;color:#0f172a;">
      <div style="background:#4f46e5;padding:24px 32px;border-radius:12px 12px 0 0;">
        <h2 style="margin:0;color:#fff;font-size:1.2rem;">{get_setting('school_name','School')}</h2>
        <p style="margin:4px 0 0;color:#c7d2fe;font-size:.85rem;">Invoice {inv['invoice_number']}</p>
      </div>
      <div style="background:#fff;padding:32px;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 12px 12px;">
        <p style="margin:0 0 16px;">Dear <strong>{inv['parent_name'] or inv['student_name']}</strong>,</p>
        <p style="margin:0 0 20px;color:#64748b;font-size:.9rem;">
          Please find below the invoice for <strong>{inv['student_name']}</strong>.
        </p>

        <table style="width:100%;border-collapse:collapse;font-size:.875rem;margin-bottom:16px;">
          <thead>
            <tr style="background:#f8faff;">
              <th style="padding:8px 12px;text-align:left;font-size:.75rem;color:#64748b;text-transform:uppercase;letter-spacing:.5px;">Description</th>
              <th style="padding:8px 12px;text-align:right;font-size:.75rem;color:#64748b;text-transform:uppercase;letter-spacing:.5px;">Amount</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
          <tfoot>
            <tr>
              <td style="padding:12px;text-align:right;font-weight:700;border-top:2px solid #e2e8f0;">Total Due</td>
              <td style="padding:12px;text-align:right;font-weight:700;color:#4f46e5;border-top:2px solid #e2e8f0;">${total:.2f}</td>
            </tr>
          </tfoot>
        </table>

        <div style="background:#f8faff;border-radius:8px;padding:12px 16px;font-size:.82rem;color:#64748b;margin-bottom:20px;">
          <strong>Invoice #:</strong> {inv['invoice_number']}<br>
          <strong>Issue Date:</strong> {inv['issue_date']}<br>
          {"<strong>Due Date:</strong> " + inv['due_date'] + "<br>" if inv['due_date'] else ""}
        </div>

        {('<p style="font-size:.85rem;color:#64748b;"><strong>Notes:</strong> ' + inv['notes'] + '</p>') if inv['notes'] else ''}

        <p style="font-size:.82rem;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:16px;margin:0;">
          Please contact us if you have any questions. Thank you.<br>
          <strong>{get_setting('school_name','School')}</strong>
        </p>
      </div>
    </div>
    """

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"Invoice {inv['invoice_number']} from {get_setting('school_name','School')}"
    msg['From']    = mail_from
    msg['To']      = recipient
    msg.attach(MIMEText(html, 'html'))

    try:
        with smtplib.SMTP(mail_server, mail_port) as smtp:
            if use_tls:
                smtp.starttls()
            smtp.login(mail_username, mail_password)
            smtp.sendmail(mail_username, recipient, msg.as_string())
        return 'ok'
    except Exception:
        return 'error'


@app.route('/invoices/<int:inv_id>/send', methods=['POST'])
@role_required('admin','accountant','frontdesk')
def send_invoice(inv_id):
    conn = get_db()
    inv = conn.execute(
        '''SELECT i.*, s.first_name||' '||s.last_name AS student_name,
                  s.parent_name, s.parent_email
           FROM invoices i JOIN students s ON i.student_id=s.id
           WHERE i.id=?''', (inv_id,)).fetchone()
    if not inv:
        conn.close(); return redirect('/finances')

    conn.execute("UPDATE invoices SET status='Sent' WHERE id=?", (inv_id,))
    conn.commit()

    items = conn.execute(
        'SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY id', (inv_id,)).fetchall()
    conn.close()
    total = sum(item['amount'] for item in items)

    result = _send_invoice_email(inv, items, total)
    return redirect(f'/invoices/{inv_id}?sent={result}')


@app.route('/invoices/<int:inv_id>/pay', methods=['POST'])
@role_required('admin','accountant','frontdesk')
def pay_invoice(inv_id):
    d = request.form; conn = get_db()
    inv = conn.execute(
        '''SELECT i.*, s.first_name||' '||s.last_name AS student_name
           FROM invoices i JOIN students s ON i.student_id=s.id
           WHERE i.id=?''', (inv_id,)).fetchone()
    if not inv or inv['status'] in ('Paid', 'Void'):
        conn.close(); return redirect(f'/invoices/{inv_id}')
    row = conn.execute(
        'SELECT COALESCE(SUM(amount),0) AS total FROM invoice_items WHERE invoice_id=?',
        (inv_id,)).fetchone()
    total = row['total']
    conn.execute("UPDATE invoices SET status='Paid' WHERE id=?", (inv_id,))
    conn.execute(
        '''INSERT INTO finances (type,category,description,amount,date,
           student_id,payment_method,status,created_by) VALUES (?,?,?,?,?,?,?,?,?)''',
        ('Income', 'Invoice Payment',
         f"Invoice {inv['invoice_number']} – {inv['student_name']}",
         total, date.today().isoformat(), inv['student_id'],
         d.get('payment_method', 'Cash'), 'Completed', session.get('user_id')))
    conn.commit(); conn.close()
    return redirect(f'/invoices/{inv_id}')


@app.route('/invoices/<int:inv_id>/void', methods=['POST'])
@role_required('admin','accountant')
def void_invoice(inv_id):
    conn = get_db()
    conn.execute("UPDATE invoices SET status='Void' WHERE id=?", (inv_id,))
    conn.commit(); conn.close()
    return redirect(f'/invoices/{inv_id}')


@app.route('/invoices/<int:inv_id>/delete', methods=['POST'])
@role_required('admin')
def delete_invoice(inv_id):
    conn = get_db()
    conn.execute("DELETE FROM invoice_items WHERE invoice_id=?", (inv_id,))
    conn.execute("DELETE FROM invoices WHERE id=?", (inv_id,))
    conn.commit(); conn.close()
    return redirect('/finances')


# ── QuickBooks Web Connector (QBWC) ──────────────────────────────────────────

_qbwc_sessions = {}   # {ticket: {'pending_ids': [...]}}
_QBWC_NS       = 'http://developer.intuit.com/'
QBWC_USER      = os.environ.get('QBWC_USER', 'qbadmin')
QBWC_PASS      = os.environ.get('QBWC_PASS', '')

def _soap_resp(method, result_xml):
    body = (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            f'<soap:Body>'
            f'<{method}Response xmlns="{_QBWC_NS}">'
            f'<{method}Result>{result_xml}</{method}Result>'
            f'</{method}Response>'
            f'</soap:Body>'
            f'</soap:Envelope>')
    return body, 200, {'Content-Type': 'text/xml; charset=utf-8'}

def _parse_soap(raw):
    try:
        root = ET.fromstring(raw)
        body = root.find('.//{http://schemas.xmlsoap.org/soap/envelope/}Body')
        if body is None:
            return None, {}
        child = list(body)[0]
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        params = {(p.tag.split('}')[-1] if '}' in p.tag else p.tag): (p.text or '')
                  for p in child}
        return tag, params
    except Exception:
        return None, {}

def _build_qbxml(rows):
    parts = []
    for r in rows:
        memo  = html_module.escape((r['description'] or r['category'])[:99])
        amt   = abs(float(r['amount']))
        ref   = html_module.escape(r['reference'] or str(r['id']))
        if r['type'] == 'Income':
            dr, cr = 'Undeposited Funds', html_module.escape(r['category'])
        else:
            dr, cr = html_module.escape(r['category']), 'Checking'
        parts.append(
            f'<JournalEntryAddRq requestID="{r["id"]}">'
            f'<JournalEntryAdd>'
            f'<TxnDate>{r["date"]}</TxnDate>'
            f'<RefNumber>{ref}</RefNumber>'
            f'<Memo>{memo}</Memo>'
            f'<JournalDebitLine><AccountRef><FullName>{dr}</FullName></AccountRef>'
            f'<Amount>{amt:.2f}</Amount><Memo>{memo}</Memo></JournalDebitLine>'
            f'<JournalCreditLine><AccountRef><FullName>{cr}</FullName></AccountRef>'
            f'<Amount>{amt:.2f}</Amount><Memo>{memo}</Memo></JournalCreditLine>'
            f'</JournalEntryAdd></JournalEntryAddRq>'
        )
    return ('<?xml version="1.0" encoding="utf-8"?><?qbxml version="13.0"?>'
            '<QBXML><QBXMLMsgsRq onError="continueOnError">'
            + ''.join(parts) +
            '</QBXMLMsgsRq></QBXML>')

@app.route('/qbwc', methods=['GET', 'POST'])
def qbwc_endpoint():
    if request.method == 'GET':
        wsdl = (f'<?xml version="1.0" encoding="utf-8"?>'
                f'<definitions xmlns="http://schemas.xmlsoap.org/wsdl/"'
                f' xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"'
                f' targetNamespace="{_QBWC_NS}" name="QBWebConnectorSvc">'
                f'<service name="QBWebConnectorSvc">'
                f'<port name="QBWebConnectorSvcSoap" binding="QBWebConnectorSvcSoap">'
                f'<soap:address location="{request.url_root.rstrip("/")}/qbwc"/>'
                f'</port></service></definitions>')
        return wsdl, 200, {'Content-Type': 'text/xml'}

    method, params = _parse_soap(request.data)

    if method == 'serverVersion':
        return _soap_resp('serverVersion', '<string>1.0</string>')

    if method == 'clientVersion':
        return _soap_resp('clientVersion', '<string></string>')

    if method == 'authenticate':
        ticket = str(uuid.uuid4())
        if params.get('strUserName') == QBWC_USER and params.get('strPassword') == QBWC_PASS:
            conn  = get_db()
            count = conn.execute("SELECT COUNT(*) FROM finances WHERE qb_synced=0").fetchone()[0]
            conn.close()
            if count > 0:
                _qbwc_sessions[ticket] = {'pending_ids': None}
                status = ''
            else:
                status = 'none'
        else:
            status = 'nvu'
        return _soap_resp('authenticate', f'<string>{ticket}</string><string>{status}</string>')

    if method == 'sendRequestXML':
        ticket = params.get('ticket', '')
        sess   = _qbwc_sessions.get(ticket)
        if not sess:
            return _soap_resp('sendRequestXML', '<string></string>')
        conn = get_db()
        rows = [dict(r) for r in conn.execute(
            "SELECT f.*, s.first_name||' '||s.last_name as student_name "
            "FROM finances f LEFT JOIN students s ON f.student_id=s.id "
            "WHERE f.qb_synced=0 ORDER BY f.date").fetchall()]
        conn.close()
        if not rows:
            return _soap_resp('sendRequestXML', '<string></string>')
        sess['pending_ids'] = [r['id'] for r in rows]
        xml_str = html_module.escape(_build_qbxml(rows))
        return _soap_resp('sendRequestXML', f'<string>{xml_str}</string>')

    if method == 'receiveResponseXML':
        ticket   = params.get('ticket', '')
        response = params.get('response', '')
        hresult  = params.get('hresult', '')
        sess     = _qbwc_sessions.pop(ticket, None)
        if hresult:
            app.logger.error(f'QBWC error {hresult}: {params.get("message","")}')
            return _soap_resp('receiveResponseXML', '<int>-1</int>')
        succeeded = []
        if response:
            try:
                for node in ET.fromstring(response).iter():
                    rid = node.get('requestID')
                    if rid and node.get('statusCode') == '0':
                        succeeded.append(int(rid))
            except Exception:
                pass
        if not succeeded and sess:
            succeeded = sess.get('pending_ids') or []
        if succeeded:
            conn = get_db()
            conn.execute(
                f"UPDATE finances SET qb_synced=1, qb_sync_date=? WHERE id IN ({','.join(['?']*len(succeeded))})",
                [date.today().isoformat()] + succeeded)
            conn.execute(
                "INSERT INTO qb_sync_log (sync_date,synced_by,record_type,record_ids,count,status,notes)"
                " VALUES (?,?,?,?,?,?,?)",
                (date.today().isoformat(), None, 'finances', json.dumps(succeeded),
                 len(succeeded), 'Success', 'QBWC auto-sync'))
            conn.commit(); conn.close()
        return _soap_resp('receiveResponseXML', '<int>100</int>')

    if method == 'connectionError':
        _qbwc_sessions.pop(params.get('ticket', ''), None)
        app.logger.error(f'QBWC connectionError: {params.get("hresult")} {params.get("message","")}')
        return _soap_resp('connectionError', '<string>done</string>')

    if method == 'getLastError':
        return _soap_resp('getLastError', '<string>No error</string>')

    if method == 'closeConnection':
        _qbwc_sessions.pop(params.get('ticket', ''), None)
        return _soap_resp('closeConnection', '<string>OK</string>')

    return '', 400

@app.route('/qbwc.qwc')
@role_required('admin', 'accountant')
def qbwc_config_download():
    server_url = request.url_root.rstrip('/')
    _sn = get_setting('school_name', 'School')
    qwc = (f'<?xml version="1.0"?><QBWCXML>'
           f'<AppName>{_sn}</AppName>'
           f'<AppID></AppID>'
           f'<AppURL>{server_url}/qbwc</AppURL>'
           f'<AppDescription>{_sn} Finance Sync</AppDescription>'
           f'<AppSupport>{server_url}</AppSupport>'
           f'<UserName>{QBWC_USER}</UserName>'
           f'<OwnerID>{{57F3B9B1-86F1-4FCC-B1EE-566DE1813D20}}</OwnerID>'
           f'<FileID>{{90A44FB5-33D9-4815-AC85-BC87A7E7D1EB}}</FileID>'
           f'<QBType>QBFS</QBType>'
           f'<Scheduler><RunEveryNMinutes>60</RunEveryNMinutes></Scheduler>'
           f'</QBWCXML>')
    safe_name = ''.join(c for c in _sn if c.isalnum() or c in ' _-').replace(' ','_').lower()
    buf = io.BytesIO(qwc.encode('utf-8'))
    return send_file(buf, mimetype='text/xml', as_attachment=True,
                     download_name=f'{safe_name}_qbwc.qwc')

# ── QuickBooks Sync ───────────────────────────────────────────────────────────

@app.route('/finances/qb-sync-data')
@role_required('admin','accountant')
def qb_sync_data():
    conn = get_db()
    rows = conn.execute('''SELECT f.*, s.first_name||' '||s.last_name as student_name
                           FROM finances f LEFT JOIN students s ON f.student_id=s.id
                           WHERE f.qb_synced=0 ORDER BY f.date''').fetchall()
    conn.close()
    result = []
    for r in rows:
        desc = f"[{r['type']}] {r['category']}"
        if r['student_name']: desc += f" – {r['student_name']}"
        if r['description']:  desc += f" | {r['description']}"
        result.append({'id':r['id'],'description':desc,
                       'amount':r['amount'] if r['type']=='Income' else -r['amount'],
                       'date':r['date'],'category':r['category'],'type':r['type']})
    return jsonify(result)

@app.route('/finances/qb-mark-synced', methods=['POST'])
@role_required('admin','accountant')
def qb_mark_synced():
    data = request.json; ids = data.get('ids',[]); notes = data.get('notes','')
    if not ids: return jsonify({'error':'No IDs'}), 400
    conn = get_db()
    conn.execute(f"UPDATE finances SET qb_synced=1,qb_sync_date=? WHERE id IN ({','.join(['?']*len(ids))})",
                 [date.today().isoformat()]+ids)
    conn.execute('''INSERT INTO qb_sync_log (sync_date,synced_by,record_type,record_ids,count,status,notes)
                    VALUES (?,?,?,?,?,?,?)''',
                 (date.today().isoformat(),session.get('user_id'),'finances',json.dumps(ids),len(ids),'Success',notes))
    conn.commit(); conn.close()
    return jsonify({'success':True,'count':len(ids)})

@app.route('/finances/qb-export-iif')
@role_required('admin','accountant')
def qb_export_iif():
    conn = get_db()
    rows = conn.execute('''SELECT f.*, s.first_name||' '||s.last_name as student_name
                           FROM finances f LEFT JOIN students s ON f.student_id=s.id
                           WHERE f.qb_synced=0 ORDER BY f.date''').fetchall()
    conn.close()
    if not rows:
        return 'No unsynced transactions to export.', 404

    lines = [
        '!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tMEMO',
        '!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO',
        '!ENDTRNS',
    ]
    for r in rows:
        try:
            d = datetime.strptime(r['date'], '%Y-%m-%d').strftime('%m/%d/%Y')
        except Exception:
            d = r['date']
        name    = (r['student_name'] or '').replace('\t', ' ')
        memo    = (r['description'] or r['category']).replace('\t', ' ')
        docnum  = r['reference'] or str(r['id'])
        amount  = float(r['amount'])
        if r['type'] == 'Income':
            trns_type  = 'CASH SALE'
            trns_acct  = 'Undeposited Funds'
            spl_acct   = r['category']
            trns_amt   =  amount
            spl_amt    = -amount
        else:
            trns_type  = 'CHECK'
            trns_acct  = 'Checking'
            spl_acct   = r['category']
            trns_amt   = -amount
            spl_amt    =  amount
        lines.append(f'TRNS\t{trns_type}\t{d}\t{trns_acct}\t{name}\t{trns_amt:.2f}\t{docnum}\t{memo}')
        lines.append(f'SPL\t{trns_type}\t{d}\t{spl_acct}\t{name}\t{spl_amt:.2f}\t{memo}')
        lines.append('ENDTRNS')

    buf = io.BytesIO('\n'.join(lines).encode('utf-8'))
    _sn_safe = ''.join(c for c in get_setting('school_name','school') if c.isalnum() or c in ' _-').replace(' ','_').lower()
    filename = f'{_sn_safe}_{date.today().isoformat()}.iif'
    return send_file(buf, mimetype='text/plain', as_attachment=True, download_name=filename)

@app.route('/qb-sync')
@role_required('admin','accountant')
def qb_sync_page():
    conn = get_db()
    unsynced_count = conn.execute("SELECT COUNT(*) FROM finances WHERE qb_synced=0").fetchone()[0]
    qb_logs = conn.execute('''SELECT q.*, u.full_name as synced_by_name
                               FROM qb_sync_log q LEFT JOIN users u ON q.synced_by=u.id
                               ORDER BY q.id DESC LIMIT 20''').fetchall()
    conn.close()
    return render_template('qb_sync.html', unsynced_count=unsynced_count, qb_logs=qb_logs)

# ── Payroll is now handled natively by payroll_bp blueprint at /payroll/* ─────

# ── Server restart ────────────────────────────────────────────────────────────

@app.route('/admin/restart', methods=['POST'])
@role_required('admin')
def restart_server():
    import threading
    def _do_restart():
        import time, os, sys
        time.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Thread(target=_do_restart, daemon=True).start()
    return ('', 204)

# ── Users ─────────────────────────────────────────────────────────────────────

@app.route('/admin/roles', methods=['GET','POST'])
@role_required('admin')
def manage_roles():
    conn = get_db()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'save':
            # Save permission checkboxes for all non-admin roles
            rows = conn.execute("SELECT role FROM role_permissions WHERE role != 'admin'").fetchall()
            for row in rows:
                role = row['role']
                perms = request.form.getlist(f'perm_{role}')
                conn.execute("UPDATE role_permissions SET permissions=? WHERE role=?",
                             (json.dumps(perms), role))
        elif action == 'add_role':
            new_role = request.form.get('new_role', '').strip().lower().replace(' ', '_')
            if new_role and new_role not in ('admin',):
                perms = request.form.getlist('new_role_perms')
                conn.execute("INSERT OR IGNORE INTO role_permissions (role, permissions) VALUES (?,?)",
                             (new_role, json.dumps(perms)))
        elif action == 'delete_role':
            role = request.form.get('role')
            if role not in ('admin','teacher','accountant','frontdesk','parent','student','viewer'):
                conn.execute("DELETE FROM role_permissions WHERE role=?", (role,))
        conn.commit()
        conn.close()
        reload_roles()
        return redirect('/admin/roles')

    rows = conn.execute("SELECT role, permissions FROM role_permissions ORDER BY role").fetchall()
    conn.close()
    role_data = [(r['role'], json.loads(r['permissions'])) for r in rows]
    return render_template('roles.html', role_data=role_data, all_permissions=ALL_PERMISSIONS)


@app.route('/users')
@role_required('admin')
def users():
    conn = get_db()
    rows     = conn.execute("SELECT * FROM users ORDER BY full_name").fetchall()
    students = conn.execute("SELECT id, student_id, first_name, last_name FROM students WHERE status='Active' ORDER BY last_name, first_name").fetchall()
    teachers = conn.execute("SELECT id, teacher_id, first_name, last_name FROM teachers WHERE status='Active' ORDER BY last_name, first_name").fetchall()
    classes  = conn.execute("SELECT id, name, teacher_id FROM classes ORDER BY name").fetchall()
    conn.close()
    return render_template('users.html', users=rows, students=students, teachers=teachers, classes=classes)

@app.route('/users/add', methods=['POST'])
@role_required('admin')
def add_user():
    d = request.form
    username = d.get('username', '').strip()
    password = d.get('password', '').strip()
    full_name = d.get('full_name', '').strip()
    if not username or not password or not full_name:
        return redirect('/users?error=missing_fields')
    linked_ids = [v for v in d.getlist('linked_id') if v]
    linked_id = linked_ids[0] if linked_ids else None
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if existing:
        conn.close()
        return redirect(f'/users?error=username_taken&username={username}')
    conn.execute('''INSERT INTO users (username,password_hash,full_name,email,role,linked_id,is_active,created_at)
                    VALUES (?,?,?,?,?,?,?,?)''',
                 (username, hash_pw(password), full_name, d.get('email'),
                  d.get('role','viewer'), linked_id, 1, date.today().isoformat()))
    conn.commit(); conn.close()
    return redirect('/users?success=user_added')

@app.route('/users/edit/<int:id>', methods=['POST'])
@role_required('admin')
def edit_user(id):
    d = request.form; conn = get_db()
    linked_ids = [v for v in d.getlist('linked_id') if v]
    linked_id = linked_ids[0] if linked_ids else None
    if d.get('password'):
        conn.execute("UPDATE users SET full_name=?,email=?,role=?,is_active=?,linked_id=?,password_hash=? WHERE id=?",
                     (d['full_name'],d.get('email'),d['role'],int(d.get('is_active',1)),linked_id,hash_pw(d['password']),id))
    else:
        conn.execute("UPDATE users SET full_name=?,email=?,role=?,is_active=?,linked_id=? WHERE id=?",
                     (d['full_name'],d.get('email'),d['role'],int(d.get('is_active',1)),linked_id,id))
    conn.commit(); conn.close(); return redirect('/users')

@app.route('/users/delete/<int:id>', methods=['POST'])
@role_required('admin')
def delete_user(id):
    if id == session.get('user_id'): return redirect('/users')
    conn = get_db(); conn.execute("DELETE FROM users WHERE id=?", (id,)); conn.commit(); conn.close()
    return redirect('/users')

@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    if request.method == 'POST':
        d = request.form; conn = get_db()
        if d.get('new_password'):
            user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
            if _check_pw(d.get('current_password',''), user['password_hash']):
                conn.execute("UPDATE users SET full_name=?,email=?,password_hash=? WHERE id=?",
                             (d['full_name'],d.get('email'),hash_pw(d['new_password']),session['user_id']))
                session['full_name'] = d['full_name']
        else:
            conn.execute("UPDATE users SET full_name=?,email=? WHERE id=?",
                         (d['full_name'],d.get('email'),session['user_id']))
            session['full_name'] = d['full_name']
        conn.commit(); conn.close(); return redirect('/profile')
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    conn.close()
    return render_template('profile.html', user=user)

@app.route('/api/subjects_by_class/<int:class_id>')
@login_required
def subjects_by_class(class_id):
    conn = get_db()
    subs = conn.execute("SELECT * FROM subjects WHERE class_id=?", (class_id,)).fetchall()
    conn.close(); return jsonify([dict(s) for s in subs])

@app.errorhandler(403)
def forbidden(e): return render_template('error.html', message="Access denied."), 403
@app.errorhandler(404)
def not_found(e): return render_template('error.html', message="Page not found."), 404

# ── School Settings ───────────────────────────────────────────────────────────

_ALLOWED_LOGO_EXT = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'}

@app.route('/admin/settings', methods=['GET', 'POST'])
@role_required('admin')
def school_settings():
    saved = False
    if request.method == 'POST':
        for key in ('school_name', 'school_address', 'school_phone', 'school_email'):
            val = request.form.get(key, '').strip()
            set_setting(key, val)

        logo_file = request.files.get('school_logo')
        if logo_file and logo_file.filename:
            ext = logo_file.filename.rsplit('.', 1)[-1].lower()
            if ext in _ALLOWED_LOGO_EXT:
                logo_filename = f'school_logo.{ext}'
                logo_path = os.path.join(_APP_DIR, 'static', 'images', logo_filename)
                logo_file.save(logo_path)
                set_setting('school_logo', f'/static/images/{logo_filename}')

        audit('UPDATE_SCHOOL_SETTINGS')
        saved = True

    settings = {
        'school_name':    get_setting('school_name', ''),
        'school_address': get_setting('school_address', ''),
        'school_phone':   get_setting('school_phone', ''),
        'school_email':   get_setting('school_email', ''),
        'school_logo':    get_setting('school_logo', '/static/images/logo-light.jpg'),
    }
    return render_template('school_settings.html', settings=settings, saved=saved)


# ── Deployment & Connection Settings ─────────────────────────────────────────

@app.route('/admin/deployment', methods=['GET', 'POST'])
@role_required('admin')
def deployment_settings():
    saved = False
    error = None

    if request.method == 'POST':
        action = request.form.get('action', 'save')

        if action == 'kick_session':
            tok = request.form.get('token')
            if tok:
                conn = get_db()
                conn.execute("DELETE FROM active_sessions WHERE token=?", (tok,))
                conn.commit(); conn.close()
        elif action == 'kick_all':
            my_tok = session.get('_tok')
            conn = get_db()
            if my_tok:
                conn.execute("DELETE FROM active_sessions WHERE token!=?", (my_tok,))
            else:
                conn.execute("DELETE FROM active_sessions")
            conn.commit(); conn.close()
        else:
            max_conn = request.form.get('max_connections', '0').strip()
            timeout_h = request.form.get('session_timeout_h', '8').strip()
            server_mode = request.form.get('server_mode', 'lan')
            try:
                if int(max_conn) < 0: max_conn = '0'
            except ValueError:
                max_conn = '0'
            try:
                if int(timeout_h) < 1: timeout_h = '1'
            except ValueError:
                timeout_h = '8'
            set_setting('max_connections', max_conn)
            set_setting('session_timeout_h', timeout_h)
            set_setting('server_mode', server_mode)
            # Apply new session timeout to Flask config
            app.config['PERMANENT_SESSION_LIFETIME'] = \
                __import__('datetime').timedelta(hours=int(timeout_h))
            audit('UPDATE_DEPLOYMENT_SETTINGS')
            saved = True

    _prune_stale_sessions()
    conn = get_db()
    active_sessions = conn.execute(
        "SELECT s.token, s.ip_address, s.user_agent, s.last_seen, s.created_at, "
        "       u.username, u.full_name, u.role "
        "FROM active_sessions s LEFT JOIN users u ON s.user_id=u.id "
        "ORDER BY s.last_seen DESC"
    ).fetchall()
    conn.close()

    local_ip   = get_local_ip()
    port       = int(os.environ.get('PORT', 5000))
    lan_url    = f'http://{local_ip}:{port}'
    my_tok     = session.get('_tok')

    cfg = {
        'max_connections':   get_setting('max_connections', '0'),
        'session_timeout_h': get_setting('session_timeout_h', '8'),
        'server_mode':       get_setting('server_mode', 'lan'),
    }

    cloudflare_running = False
    try:
        import subprocess
        r = subprocess.run(['tasklist'], capture_output=True, text=True, timeout=3)
        cloudflare_running = 'cloudflared' in r.stdout.lower()
    except Exception:
        pass

    return render_template('deployment.html',
        cfg=cfg,
        active_sessions=active_sessions,
        active_count=len(active_sessions),
        local_ip=local_ip,
        lan_url=lan_url,
        port=port,
        my_tok=my_tok,
        cloudflare_running=cloudflare_running,
        saved=saved,
        error=error)


# ── License Activation & Status ──────────────────────────────────────────────

@app.route('/activate', methods=['GET', 'POST'])
def activate():
    existing_key = get_setting('license_key', '')
    if existing_key:
        ok, info, _ = _lic.validate_key(existing_key)
        if ok:
            return redirect('/')

    error = None
    if request.method == 'POST':
        key = request.form.get('license_key', '').strip()
        ok, info, err = _lic.validate_key(key)
        if ok:
            set_setting('license_key', key)
            return redirect('/')
        error = err or 'Invalid license key.'

    return render_template('activate.html', error=error)


@app.route('/admin/license', methods=['GET', 'POST'])
@role_required('admin')
def license_status():
    saved = False
    error = None

    if request.method == 'POST':
        key = request.form.get('license_key', '').strip()
        ok, info, err = _lic.validate_key(key)
        if ok:
            set_setting('license_key', key)
            audit('UPDATE_LICENSE_KEY')
            saved = True
        else:
            error = err or 'Invalid license key.'

    key = get_setting('license_key', '')
    ok, info, err = _lic.validate_key(key) if key else (False, None, 'No license key activated.')
    days_left = _lic.days_until_expiry(info['expiry']) if info else None

    return render_template('license_status.html',
        license_key=key,
        license_ok=ok,
        license_info=info,
        license_error=err,
        days_left=days_left,
        saved=saved,
        error=error,
        tiers=_lic.TIERS)


if __name__ == '__main__':
    init_db()
    # Apply saved session timeout from DB
    _saved_timeout = int(get_setting('session_timeout_h', '8') or 8)
    app.config['PERMANENT_SESSION_LIFETIME'] = \
        __import__('datetime').timedelta(hours=_saved_timeout)
    name = get_setting('school_name', 'School Management System')
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    print("\n" + "="*55)
    print(f"  {name}")
    print("  School Management System")
    print("="*55)
    print(f"  Open:        http://{host}:{port}")
    print(f"  Admin login: admin / (set on first login)")
    print(f"  Public site: http://{host}:{port}/home")
    print("="*55+"\n")
    app.run(debug=False, port=port, host=host)
