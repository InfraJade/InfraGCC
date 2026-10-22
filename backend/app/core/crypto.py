"""Symmetric encryption for small secrets stored in the database, such as Teams webhook URLs."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet(secret: str | None = None) -> Fernet:
    raw = secret if secret is not None else get_settings().app_secret_key.get_secret_value()
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def encrypt(value: str, *, secret: str | None = None) -> str:
    return _fernet(secret).encrypt(value.encode()).decode()


def decrypt(token: str, *, secret: str | None = None) -> str:
    try:
        return _fernet(secret).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt value: APP_SECRET_KEY changed or data is corrupt") from exc


def mask_target(channel: str, target: str) -> str:
    """A display-safe hint: email addresses stay readable, webhook URLs keep only scheme and host."""
    if channel == "email":
        return target
    head, _, rest = target.partition("://")
    host = rest.split("/", 1)[0]
    return f"{head}://{host}/…" if rest else "…"
