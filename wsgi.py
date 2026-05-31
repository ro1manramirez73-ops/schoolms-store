import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'files'))

from app import app, init_db, get_setting
import datetime

init_db()

# Apply session timeout saved in DB settings
_timeout_h = int(get_setting('session_timeout_h', '8') or 8)
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(hours=_timeout_h)

if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get('PORT', 5000))
    serve(app, host='0.0.0.0', port=port, threads=16, connection_limit=200)
