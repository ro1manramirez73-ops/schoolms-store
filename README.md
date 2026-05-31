# School Management System

A comprehensive Flask-based school management system with student tracking, attendance, grades, fees, payroll, and more.

## Quick Start (Windows)

1. Run the installer (`SchoolMS_Setup_v1.0.exe`)
2. Launch from the desktop shortcut or `launcher.vbs`
3. Enter your license key on first run
4. Log in: **admin / admin123** (you will be prompted to change the password)

## Local Development

1. Clone the repository
2. Create virtual environment: `python -m venv .venv`
3. Activate: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Linux/Mac)
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and fill in values
6. Add `LICENSE_DEV=1` to `.env` to skip license gate during development
7. Run: `python wsgi.py`

## Production Deployment

### Option 1: Simple VPS (Linux)

1. Get a VPS (DigitalOcean, Linode, AWS EC2, etc.)
2. `sudo apt update && sudo apt install python3 python3-pip python3-venv nginx -y`
3. Clone repository to `/var/www/schoolms`
4. Create venv and install dependencies
5. Copy `.env.example` to `.env` and configure
6. Run with Gunicorn: `gunicorn --config gunicorn.conf.py wsgi:app`
7. Configure Nginx as reverse proxy with SSL (Let's Encrypt)

### Option 2: Docker

Use the included `Dockerfile` and `docker-compose.yml`:

```bash
cp .env.example .env   # fill in values
docker-compose up -d
```

### Option 3: Cloudflare Tunnel (no port-forward)

Run `setup_cloudflare.bat` as Administrator for a free permanent HTTPS URL.

## License Key Management

- Generate keys: `python keygen.py` (seller only — keep `keygen.py` private)
- Customers activate at `/activate` on first run
- Admins can update the key at `/admin/license`

## Default Login

- Username: `admin`
- Password: `admin123` (must change on first login)
