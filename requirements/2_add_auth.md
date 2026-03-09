# Requirements: Authentication for PDF Q&A App

This document describes the requirements for adding simple email/password authentication. The planner agent should turn it into a technical plan; the implementer will then build according to that plan.

## Goal

Protect the Gradio app behind a login wall so that only users with valid email/password credentials can access the PDF Q&A interface.

## Approaches considered

### A. Gradio built-in `auth` parameter (recommended)

Gradio's `demo.launch(auth=authenticate_fn)` accepts a callable `(username, password) -> bool`. When set, Gradio renders its own login page and blocks all access (UI and API) until the user authenticates.

- Zero additional dependencies; minimal code change in `gradio_app.py`.
- Gradio provides a styled login page out of the box.
- The logged-in username is available via `gr.Request.username` inside handlers.
- The Gradio 6 auth bugs (#12444, #12814) have been fixed as of PR #12817 (Jan 2026); the project uses Gradio 6.9.0 which includes the fix.
- **Pros:** simplest approach, no extra containers or libraries, native login UI, protects both UI and API endpoints.
- **Cons:** limited login-page customization, no built-in registration flow, basic session management.

### B. nginx-proxy basic auth

The app is already behind nginx-proxy (`VIRTUAL_HOST`, `LETSENCRYPT_HOST`, `nginx_proxy_net` in `docker-compose.yml`). Basic auth can be added via an htpasswd file or the `PROXY_BASIC_AUTH` environment variable.

- **Pros:** no code changes, infrastructure-level.
- **Cons:** browser popup instead of styled login page (poor UX), requires HTTPS, harder to manage users dynamically.

### C. FastAPI wrapper with custom auth

Mount Gradio inside a FastAPI app using `gr.mount_gradio_app()`. Build a custom `/login` endpoint with session cookies, a styled HTML login page, and a users store (JSON file or SQLite).

- **Pros:** full control over login UI and session management; extensible to registration and password reset.
- **Cons:** significant refactoring of `gradio_app.py`, manual session/cookie/CSRF handling, more moving parts.

### D. External auth proxy (Authelia / Authentik)

Add a dedicated authentication container to `docker-compose.yml` that intercepts all requests before they reach the Gradio app.

- **Pros:** most robust (2FA, multiple auth methods, admin UI).
- **Cons:** heavy for a simple or small-team app, extra container, complex configuration.

## Must-have requirements

1. **Login wall**
   - The app must show a login page before any content is accessible.
   - Use Gradio's built-in `auth` parameter (Approach A).
   - Both the web UI and Gradio API endpoints must be protected.

2. **Credential verification**
   - The `auth` callable receives `(username, password)` and returns `True`/`False`.
   - Passwords must be stored as bcrypt hashes (`bcrypt` is already in `requirements.txt`).
   - The planner should implement an `authenticate(username, password) -> bool` function that loads credentials and verifies the hash.

3. **User storage**
   - Support a `users.json` file containing a list of `{"email": "...", "password_hash": "..."}` entries.
   - The file path should be configurable via the `AUTH_USERS_FILE` environment variable (default: `users.json`).
   - In Docker, `users.json` can be bind-mounted or baked into the image.
   - As a convenience fallback, support a single user defined by `AUTH_USER` and `AUTH_PASSWORD_HASH` environment variables (checked when `users.json` is absent or empty).

4. **Hashed passwords**
   - Never store plaintext passwords.
   - Provide a helper script (e.g. `scripts/hash_password.py`) that takes a plaintext password and prints the bcrypt hash so the operator can populate `users.json` or the env var.

5. **Docker integration**
   - Add `AUTH_USERS_FILE`, `AUTH_USER`, and `AUTH_PASSWORD_HASH` to the `environment` section in `docker-compose.yml`.
   - Document how to generate a password hash and add it to the compose file or `users.json`.

## optional requirements:

- Display the logged-in username somewhere in the UI (e.g. in the header or status bar) using `gr.Request.username`.
- `auth_message` parameter on `demo.launch()` to show a custom message on the login page (e.g. "PDF Q&A — please log in").
- A `scripts/create_user.py` helper that appends a new user entry to `users.json` interactively.

## Out of scope

- Registration through the UI.
- Password reset flow.
- OAuth / SSO / third-party identity providers.
- Role-based access control or per-user data isolation.
- Persisting sessions across server restarts (Gradio sessions are in-memory).

## Context for the planner

- **File to modify:** `gradio_app.py` — the `main()` function where `demo.launch()` is called.
- **New file:** `auth.py` — authentication logic (load users, verify password).
- **New file:** `scripts/hash_password.py` — CLI helper to generate bcrypt hashes.
- **Config files:** `docker-compose.yml` (add env vars), `.env.example` (document new variables).
- **Existing dependency:** `bcrypt==5.0.0` is already in `requirements.txt`.
- **Gradio version:** 6.9.0 — built-in `auth` parameter works correctly (bug fixes merged).

The planner should produce a step-by-step technical plan that the implementer can follow to wire the `auth` callable into `demo.launch()`, implement bcrypt-based credential verification, and configure user storage for both local development and Docker deployment.
