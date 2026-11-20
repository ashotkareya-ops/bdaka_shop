import secrets

def make_order_reference() -> str:
    return secrets.token_urlsafe(12)
