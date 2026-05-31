"""
License key system for School Management System.
Keys are HMAC-signed payloads encoding tier, user limit, and expiry.

SELLER ONLY: Use keygen.py (at repo root) to generate keys.
"""

import hmac, hashlib, base64, json, datetime, os

# Change this secret before distributing — keep it private.
_SECRET = os.environ.get('LICENSE_SECRET', '594ff1c25e4b861008cd0615e951d5c43a77146566a43354491622cf438f1ce9')

TIERS = {
    'starter':      {'label': 'Starter',      'max_users': 10},
    'standard':     {'label': 'Standard',      'max_users': 30},
    'professional': {'label': 'Professional',  'max_users': 9999},
}

def _sign(payload_b64: str) -> str:
    return hmac.new(_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()[:20]

def generate_key(tier: str, expiry: str = 'lifetime') -> str:
    """
    Generate a license key.
    tier   : 'starter' | 'standard' | 'professional'
    expiry : 'lifetime' | 'YYYY-MM-DD'
    Returns a formatted key string.
    """
    if tier not in TIERS:
        raise ValueError(f"Unknown tier: {tier}")
    payload = {
        't': tier,
        'e': expiry,
        'i': datetime.date.today().isoformat(),
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode()
    ).decode().rstrip('=')
    sig = _sign(payload_b64)
    raw = f"{payload_b64}.{sig}"
    # Pretty-print as XXXXX-XXXXX-... groups
    clean = raw.replace('-', '').replace('_', '').replace('.', '')
    parts = [raw]  # store raw for easy parsing
    return raw

def validate_key(key: str):
    """
    Validate a license key.
    Returns (ok: bool, info: dict | None, error: str | None)
    info contains: tier, label, max_users, expiry, issued
    """
    try:
        key = key.strip()
        if '.' not in key:
            return False, None, "Invalid key format."
        payload_b64, sig = key.rsplit('.', 1)
        expected = _sign(payload_b64)
        if not hmac.compare_digest(sig, expected):
            return False, None, "License key is invalid or has been tampered with."
        # Decode payload
        padding = '=' * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding).decode())
        tier = payload.get('t', '')
        expiry = payload.get('e', 'lifetime')
        issued = payload.get('i', '')
        if tier not in TIERS:
            return False, None, f"Unknown tier in license: {tier}"
        # Check expiry
        if expiry != 'lifetime':
            try:
                exp_date = datetime.date.fromisoformat(expiry)
                if exp_date < datetime.date.today():
                    return False, None, f"License expired on {expiry}. Please renew."
            except ValueError:
                return False, None, "Invalid expiry date in license."
        info = {
            'tier':      tier,
            'label':     TIERS[tier]['label'],
            'max_users': TIERS[tier]['max_users'],
            'expiry':    expiry,
            'issued':    issued,
        }
        return True, info, None
    except Exception as ex:
        return False, None, f"Key validation error: {ex}"

def days_until_expiry(expiry: str) -> int | None:
    """Returns days remaining, or None for lifetime licenses."""
    if expiry == 'lifetime':
        return None
    try:
        exp = datetime.date.fromisoformat(expiry)
        return (exp - datetime.date.today()).days
    except Exception:
        return None
