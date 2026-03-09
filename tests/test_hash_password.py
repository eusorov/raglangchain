"""Tests for scripts/hash_password.py."""

import sys
from unittest.mock import patch

import bcrypt

from scripts.hash_password import main


class TestHashPassword:

    def test_hash_password_cli_arg(self, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["hash_password.py", "test123"])
        main()
        output = capsys.readouterr().out.strip()
        assert output.startswith("$2b$")
        assert bcrypt.checkpw(b"test123", output.encode("utf-8"))

    def test_hash_password_interactive(self, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["hash_password.py"])
        with patch("builtins.input", return_value="test123"):
            main()
        output = capsys.readouterr().out.strip()
        assert output.startswith("$2b$")
        assert bcrypt.checkpw(b"test123", output.encode("utf-8"))
