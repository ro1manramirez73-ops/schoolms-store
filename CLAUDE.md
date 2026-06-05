# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Setup:**
```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements.txt
cp .env.example .env
```

**Run (development):**
```bash
python wsgi.py               # Waitress on port 5000
```

**Run (production):**
```bash
gunicorn --config gunicorn.conf.py wsgi:app
docker-compose up -d
```

**Windows shortcuts:** `SchoolMSLaunch.bat`, `RestartServer.bat`, `build_python_env.bat`

## Architecture

The app is a Flask monolith. Nearly all backend logic lives in a single large file: `files/app.py` (~4,300+ lines). The entry point is `wsgi.py`, which loads the app from `files/app.py` via Waitress (dev) or Gunicorn/Docker (prod).

**Key architectural facts:**
- `files/app.py` — all routes, DB schema creation, auth, and business logic in one file
- `files/payroll_routes.py` — payroll Flask blueprint, registered at `/payroll/`; maintains a separate `payroll.db`
- `files/license.py` — license key validation; set `LICENSE_DEV=1` in `.env` to bypass during development
- `files/templates/` — 53 Jinja2 templates; `base.html` is the shared layout
- `files/static/i18n/en.json` and `es.json` — all UI strings; language set per session via `/set-language/<lang>`

**Database:** SQLite (`files/school.db`) by default; `DATABASE_URL` env var switches to PostgreSQL. Schema auto-migrates on startup. All dates stored as ISO TEXT. Tables use `INTEGER PRIMARY KEY AUTOINCREMENT`.

**Auth & Roles:** 6 roles (admin, teacher, accountant, frontdesk, parent, student). Role permissions are stored in `role_permissions` table and are customizable at runtime. Sessions tracked in `active_sessions` with configurable concurrent-user limits (staff only).

**Frontend:** Jinja2 + HTMX for dynamic updates + Bootstrap/Tailwind. No build step — static assets served directly. PWA support via `manifest.json` and `sw.js`.

## Environment Variables

Required in `.env`:
| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session secret |
| `DATABASE_URL` | SQLite path or PostgreSQL URL |
| `LICENSE_DEV=1` | Skip license gate (dev only) |
| `MAIL_SERVER` / `MAIL_PORT` / `MAIL_USERNAME` / `MAIL_PASSWORD` | SMTP for email delivery |
| `QBWC_USER` / `QBWC_PASS` | QuickBooks Web Connector (optional) |

## Important Patterns

- **Password hashing:** bcrypt; legacy SHA-256 hashes are auto-migrated on first login.
- **CSRF:** Flask-WTF enabled globally — all POST forms need `{{ form.hidden_tag() }}` or the CSRF token.
- **Rate limiting:** Flask-Limiter applied to auth routes.
- **Audit log:** All significant actions are written to the `audit_log` table.
- **PDF generation:** reportlab and fpdf2 are both used; receipts/invoices use fpdf2, report cards use reportlab.
- **CSV import utilities:** `files/import_*.py` scripts for bulk data loading.
