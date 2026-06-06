import os
import multiprocessing

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# WEB_CONCURRENCY lets cloud platforms (Railway, Render, Heroku) override this.
# Default: 2×CPU+1, capped at 9 to avoid SQLite file-lock contention.
workers = int(os.environ.get('WEB_CONCURRENCY', min(multiprocessing.cpu_count() * 2 + 1, 9)))
worker_class = "sync"
threads = 1

max_requests = 1000       # recycle worker after N requests to prevent memory leaks
max_requests_jitter = 100 # stagger restarts so no all-at-once downtime
timeout = 60              # generous for PDF/ZIP generation (was 30)
keepalive = 2

# Log to stdout/stderr so the process manager (systemd, Docker, etc.) captures them.
# Override with LOG_DIR env var if you want file-based logs.
_log_dir = os.environ.get('LOG_DIR', '')
if _log_dir:
    accesslog = os.path.join(_log_dir, 'access.log')
    errorlog  = os.path.join(_log_dir, 'error.log')
else:
    accesslog = '-'   # stdout
    errorlog  = '-'   # stderr

loglevel = "info"
