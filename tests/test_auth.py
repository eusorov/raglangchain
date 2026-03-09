"""Tests for auth.py — user loading and credential verification."""

import json

import bcrypt
import pytest

import auth


# ---------------------------------------------------------------------------
# _load_users_from_file
# ---------------------------------------------------------------------------

class TestLoadUsersFromFile:

    def test_load_users_from_valid_file(self, tmp_users_file):
        users = auth._load_users_from_file()
        assert len(users) == 2
        assert "alice@example.com" in users
        assert "bob@example.com" in users

    def test_load_users_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr("auth.AUTH_USERS_FILE", str(tmp_path / "nope.json"))
        assert auth._load_users_from_file() == {}

    def test_load_users_file_invalid_json(self, monkeypatch, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json!!!", encoding="utf-8")
        monkeypatch.setattr("auth.AUTH_USERS_FILE", str(bad))
        assert auth._load_users_from_file() == {}

    def test_load_users_file_wrong_structure(self, monkeypatch, tmp_path):
        wrong = tmp_path / "wrong.json"
        wrong.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        monkeypatch.setattr("auth.AUTH_USERS_FILE", str(wrong))
        assert auth._load_users_from_file() == {}

    def test_load_users_file_skips_incomplete_entries(self, monkeypatch, tmp_path, known_hash):
        data = [
            {"email": "good@example.com", "password_hash": known_hash},
            {"email": "", "password_hash": known_hash},
            {"email": "nohash@example.com"},
            {"password_hash": known_hash},
        ]
        p = tmp_path / "partial.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr("auth.AUTH_USERS_FILE", str(p))
        users = auth._load_users_from_file()
        assert list(users.keys()) == ["good@example.com"]


# ---------------------------------------------------------------------------
# _load_users_from_env
# ---------------------------------------------------------------------------

class TestLoadUsersFromEnv:

    def test_load_users_from_env_both_set(self, monkeypatch, known_hash):
        monkeypatch.setenv("AUTH_USER", "env@example.com")
        monkeypatch.setenv("AUTH_PASSWORD_HASH", known_hash)
        users = auth._load_users_from_env()
        assert users == {"env@example.com": known_hash}

    def test_load_users_from_env_missing_user(self, monkeypatch, known_hash):
        monkeypatch.delenv("AUTH_USER", raising=False)
        monkeypatch.setenv("AUTH_PASSWORD_HASH", known_hash)
        monkeypatch.setattr("auth.config", {})
        assert auth._load_users_from_env() == {}

    def test_load_users_from_env_missing_hash(self, monkeypatch):
        monkeypatch.setenv("AUTH_USER", "user@example.com")
        monkeypatch.delenv("AUTH_PASSWORD_HASH", raising=False)
        monkeypatch.setattr("auth.config", {})
        assert auth._load_users_from_env() == {}

    def test_load_users_from_env_normalizes_email(self, monkeypatch, known_hash):
        monkeypatch.setenv("AUTH_USER", " Admin@Example.COM ")
        monkeypatch.setenv("AUTH_PASSWORD_HASH", known_hash)
        users = auth._load_users_from_env()
        assert "admin@example.com" in users


# ---------------------------------------------------------------------------
# _get_users
# ---------------------------------------------------------------------------

class TestGetUsers:

    def test_get_users_merges_file_and_env(self, tmp_path, monkeypatch, known_hash):
        data = [{"email": "file@example.com", "password_hash": known_hash}]
        p = tmp_path / "users.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr("auth.AUTH_USERS_FILE", str(p))
        monkeypatch.setenv("AUTH_USER", "env@example.com")
        monkeypatch.setenv("AUTH_PASSWORD_HASH", known_hash)

        users = auth._get_users()
        assert "file@example.com" in users
        assert "env@example.com" in users

    def test_get_users_file_overrides_env(self, tmp_path, monkeypatch):
        env_hash = bcrypt.hashpw(b"env-pw", bcrypt.gensalt()).decode()
        file_hash = bcrypt.hashpw(b"file-pw", bcrypt.gensalt()).decode()

        data = [{"email": "same@example.com", "password_hash": file_hash}]
        p = tmp_path / "users.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr("auth.AUTH_USERS_FILE", str(p))
        monkeypatch.setenv("AUTH_USER", "same@example.com")
        monkeypatch.setenv("AUTH_PASSWORD_HASH", env_hash)

        users = auth._get_users()
        assert users["same@example.com"] == file_hash


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------

class TestAuthenticate:

    def test_authenticate_valid_credentials(self, tmp_users_file, known_password):
        assert auth.authenticate("alice@example.com", known_password) is True

    def test_authenticate_wrong_password(self, tmp_users_file):
        assert auth.authenticate("alice@example.com", "wrong-password") is False

    def test_authenticate_unknown_user(self, tmp_users_file, known_password):
        assert auth.authenticate("unknown@example.com", known_password) is False

    def test_authenticate_case_insensitive_email(self, tmp_users_file, known_password):
        assert auth.authenticate("Alice@EXAMPLE.com", known_password) is True

    def test_authenticate_no_users_configured(self, monkeypatch, tmp_path):
        monkeypatch.setattr("auth.AUTH_USERS_FILE", str(tmp_path / "empty.json"))
        monkeypatch.delenv("AUTH_USER", raising=False)
        monkeypatch.delenv("AUTH_PASSWORD_HASH", raising=False)
        monkeypatch.setattr("auth.config", {})
        assert auth.authenticate("anyone@example.com", "anything") is False

    def test_authenticate_corrupt_hash(self, monkeypatch, tmp_path):
        data = [{"email": "bad@example.com", "password_hash": "not-a-bcrypt-hash"}]
        p = tmp_path / "users.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr("auth.AUTH_USERS_FILE", str(p))
        assert auth.authenticate("bad@example.com", "anything") is False
