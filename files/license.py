"""
License key system for School Management System.
Keys are Ed25519-signed payloads encoding tier, user limit, and expiry.

SELLER ONLY: Use keygen.py (at repo root) to generate keys.
             Keep license_private.pem private — never distribute it.
             The public key below is intentionally embedded; it cannot
             be used to forge keys, only to verify them.
"""

import base64, json, datetime, hashlib, uuid, socket, logging
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.exceptions import InvalidSignature

log = logging.getLogger(__name__)

# Ed25519 public key — safe to ship in source; useless for forging keys.
_PUBLIC_KEY_HEX = 'a04f8d53034e53be23b027ad0cab5256d37423a64661a1f929dee86192c2efee'
_PUBLIC_KEY_BYTES = bytes.fromhex(_PUBLIC_KEY_HEX)
_PUBLIC_KEY: Ed25519PublicKey = Ed25519PublicKey.from_public_bytes(_PUBLIC_KEY_BYTES)

TIERS = {
    'starter':      {'label': 'Starter',      'max_users': 10},
    'standard':     {'label': 'Standard',      'max_users': 30},
    'professional': {'label': 'Professional',  'max_users': 9999},
}


def get_machine_id() -> str:
    """Stable fingerprint of this machine (MAC address + hostname)."""
    raw = f"{uuid.getnode()}:{socket.gethostname()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


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

        payload_b64, sig_b64 = key.rsplit('.', 1)

        # Verify Ed25519 signature
        try:
            sig_bytes = base64.urlsafe_b64decode(sig_b64 + '==')
            _PUBLIC_KEY.verify(sig_bytes, payload_b64.encode())
        except (InvalidSignature, Exception):
            return False, None, "License key is invalid or has been tampered with."

        # Decode payload
        padding = '=' * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding).decode())

        tier   = payload.get('t', '')
        expiry = payload.get('e', 'lifetime')
        issued = payload.get('i', '')

        if tier not in TIERS:
            return False, None, f"Unknown tier in license: {tier}"

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
        log.exception("License key validation error")
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
