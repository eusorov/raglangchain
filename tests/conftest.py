import json

import bcrypt
import pytest

KNOWN_PASSWORD = "test-secret-123"
KNOWN_HASH = bcrypt.hashpw(KNOWN_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


@pytest.fixture()
def known_password():
    return KNOWN_PASSWORD


@pytest.fixture()
def known_hash():
    return KNOWN_HASH


@pytest.fixture()
def tmp_users_file(tmp_path, monkeypatch, known_hash):
    """Write a temp users.json with two users and patch AUTH_USERS_FILE to point to it."""
    users = [
        {"email": "alice@example.com", "password_hash": known_hash},
        {"email": "bob@example.com", "password_hash": known_hash},
    ]
    path = tmp_path / "users.json"
    path.write_text(json.dumps(users), encoding="utf-8")
    monkeypatch.setattr("auth.AUTH_USERS_FILE", str(path))
    return path
