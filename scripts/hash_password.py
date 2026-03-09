#!/usr/bin/env python3
"""Generate a bcrypt hash for a plaintext password.

Usage:
    python scripts/hash_password.py
    python scripts/hash_password.py 'my-secret-password'

The hash can be used in users.json or the AUTH_PASSWORD_HASH env var.
"""

import sys

import bcrypt


def main():
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = input("Enter password: ")

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    print(hashed)


if __name__ == "__main__":
    main()
