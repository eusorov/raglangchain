# Test Plan: Authentication Feature

This document describes the test plan for the authentication feature added in requirement `2_add_auth.md`. The implementer should follow this plan to create automated tests.

## Prerequisites

The project has no existing test infrastructure. Before writing tests:

1. Add `pytest` to `requirements.txt`.
2. Create a `tests/` directory with an empty `__init__.py`.
3. Create `tests/conftest.py` for shared fixtures.

## Files under test

| File | Type | What to test |
|---|---|---|
| `auth.py` | Unit tests | All functions: `_load_users_from_file`, `_load_users_from_env`, `_get_users`, `authenticate` |
| `scripts/hash_password.py` | Unit test | `main()` produces a valid bcrypt hash |
| `gradio_app.py` | Smoke test | `demo.launch()` receives `auth=authenticate` (no full Gradio server needed) |

## Test file: `tests/test_auth.py`

### Fixtures (in `conftest.py`)

- **`tmp_users_file`** — writes a temporary `users.json` with one or more known email/hash pairs, patches `auth.AUTH_USERS_FILE` to point to it, yields the path, and cleans up.
- **`known_password`** / **`known_hash`** — a fixed plaintext password and its bcrypt hash for deterministic assertions.

### Test cases for `auth.py`

#### `_load_users_from_file`

| # | Test name | Setup | Expected |
|---|---|---|---|
| 1 | `test_load_users_from_valid_file` | Temp JSON file with two users | Returns dict with 2 entries, emails lowercased |
| 2 | `test_load_users_file_missing` | Point `AUTH_USERS_FILE` to a nonexistent path | Returns empty dict |
| 3 | `test_load_users_file_invalid_json` | Temp file with broken JSON | Returns empty dict (logs exception) |
| 4 | `test_load_users_file_wrong_structure` | Temp file with `{"not": "a list"}` | Returns empty dict (logs warning) |
| 5 | `test_load_users_file_skips_incomplete_entries` | Entries missing `email` or `password_hash` | Only complete entries returned |

#### `_load_users_from_env`

| # | Test name | Setup | Expected |
|---|---|---|---|
| 6 | `test_load_users_from_env_both_set` | Set `AUTH_USER` and `AUTH_PASSWORD_HASH` env vars | Returns single-entry dict |
| 7 | `test_load_users_from_env_missing_user` | Only `AUTH_PASSWORD_HASH` set | Returns empty dict |
| 8 | `test_load_users_from_env_missing_hash` | Only `AUTH_USER` set | Returns empty dict |
| 9 | `test_load_users_from_env_normalizes_email` | `AUTH_USER=" Admin@Example.COM "` | Key is `"admin@example.com"` |

#### `_get_users`

| # | Test name | Setup | Expected |
|---|---|---|---|
| 10 | `test_get_users_merges_file_and_env` | Env has user A, file has user B | Both present |
| 11 | `test_get_users_file_overrides_env` | Same email in both env and file with different hashes | File hash wins |

#### `authenticate`

| # | Test name | Setup | Expected |
|---|---|---|---|
| 12 | `test_authenticate_valid_credentials` | Known email + correct plaintext password | Returns `True` |
| 13 | `test_authenticate_wrong_password` | Known email + wrong password | Returns `False` |
| 14 | `test_authenticate_unknown_user` | Email not in users | Returns `False` |
| 15 | `test_authenticate_case_insensitive_email` | Username as `"Admin@EXAMPLE.com"` | Matches lowercased stored email |
| 16 | `test_authenticate_no_users_configured` | No file, no env vars | Returns `False` |
| 17 | `test_authenticate_corrupt_hash` | Stored hash is not valid bcrypt | Returns `False` (logs exception) |

### Test cases for `scripts/hash_password.py`

| # | Test name | Setup | Expected |
|---|---|---|---|
| 18 | `test_hash_password_cli_arg` | Call `main()` with `sys.argv = ["prog", "test123"]` | Prints a string starting with `$2b$` that verifies against `"test123"` via `bcrypt.checkpw` |
| 19 | `test_hash_password_interactive` | Mock `input()` to return `"test123"` | Same as above |

### Smoke test for `gradio_app.py` auth wiring

| # | Test name | Setup | Expected |
|---|---|---|---|
| 20 | `test_gradio_app_has_auth_wired` | Import `gradio_app`, patch heavy deps (llm, vector, retriever), call `main()` up to `demo.launch` | Verify `demo.launch` is called with `auth=authenticate` kwarg |

## Running the tests

```bash
pytest tests/ -v
```

## Implementation notes for the implementer

- Use `monkeypatch` (pytest built-in) to override `auth.AUTH_USERS_FILE` and environment variables. Avoid modifying global state permanently.
- Use `tmp_path` (pytest built-in) for temporary file fixtures.
- For test 20 (Gradio smoke test), mock `gr.Blocks` and `demo.launch` to capture kwargs without starting a server. Alternatively, just verify the import and that `authenticate` is the correct callable — a full Gradio launch test is out of scope.
- All tests should run without network access (no Chroma, no LLM, no Gradio server).
- Use `bcrypt.hashpw(b"password", bcrypt.gensalt())` to generate test hashes in fixtures rather than hardcoding hash strings (they vary by salt).
