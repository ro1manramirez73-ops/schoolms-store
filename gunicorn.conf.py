import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = 3
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = 30
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
