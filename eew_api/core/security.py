import hashlib
import secrets

import bcrypt


def hash_api_key(api_key: str) -> str:
    return bcrypt.hashpw(api_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_api_key(api_key: str, api_key_hash: str) -> bool:
    try:
        return bcrypt.checkpw(api_key.encode("utf-8"), api_key_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def sha256_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
