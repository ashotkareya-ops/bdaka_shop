import hashlib
import hmac
import secrets
import time

def build_headers(api_key: str, api_secret: str, method: str, path_with_query: str, body: bytes):
    """Create Sandromania HMAC-SHA256 headers exactly as specified by the provider."""
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)  # fresh unique nonce for every HTTP request/retry
    canonical = (
        timestamp.encode("utf-8") + b"." +
        nonce.encode("utf-8") + b"." +
        method.upper().encode("utf-8") + b"." +
        path_with_query.encode("utf-8") + b"." +
        body
    )
    signature = hmac.new(
        api_secret.encode("utf-8"), canonical, hashlib.sha256
    ).hexdigest()
    return {
        "X-Api-Key": api_key,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }
