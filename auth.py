"""
Authentication module: loads user credentials and verifies passwords with bcrypt.

Credential sources (checked in order):
1. JSON file at AUTH_USERS_FILE (default: users.json)
2. Single-user fallback via AUTH_USER + AUTH_PASSWORD_HASH env vars
"""

import json
import logging
import os
from pathlib import Path

import bcrypt
from dotenv import dotenv_values

logger = logging.getLogger(__name__)

config = dotenv_values(".env")

AUTH_USERS_FILE = os.getenv(
    "AUTH_USERS_FILE", config.get("AUTH_USERS_FILE", "users.json")
)


def _load_users_from_file() -> dict[str, str]:
    """Return {email: password_hash} from the JSON users file, or empty dict."""
    path = Path(AUTH_USERS_FILE)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            logger.warning("users file %s: expected a JSON list, got %s", path, type(data).__name__)
            return {}
        users = {}
        for entry in data:
            email = entry.get("email", "").strip().lower()
            pw_hash = entry.get("password_hash", "")
            if email and pw_hash:
                users[email] = pw_hash
        logger.info("Loaded %d user(s) from %s", len(users), path)
        return users
    except Exception:
        logger.exception("Failed to read users file %s", path)
        return {}


def _load_users_from_env() -> dict[str, str]:
    """Return a single-user dict from AUTH_USER / AUTH_PASSWORD_HASH env vars."""
    user = os.getenv("AUTH_USER", config.get("AUTH_USER", "")).strip().lower()
    pw_hash = os.getenv("AUTH_PASSWORD_HASH", config.get("AUTH_PASSWORD_HASH", ""))
    if user and pw_hash:
        logger.info("Using single-user AUTH_USER=%s", user)
        return {user: pw_hash}
    return {}


def _get_users() -> dict[str, str]:
    """Merge file-based and env-var-based users; file takes precedence for duplicates."""
    users = _load_users_from_env()
    users.update(_load_users_from_file())
    return users


def authenticate(username: str, password: str) -> bool:
    """Verify username/password against loaded credentials. Used as Gradio auth callable."""
    users = _get_users()
    if not users:
        logger.warning("No auth users configured — denying all logins")
        return False
    stored_hash = users.get(username.strip().lower())
    if stored_hash is None:
        return False
    logger.info("Authenticating user=%s", username)
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            stored_hash.encode("utf-8"),
        )
    except Exception:
        logger.exception("bcrypt verification error for user=%s", username)
        return False
