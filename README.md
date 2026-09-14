# raglangchain

A RAG (retrieval-augmented generation) app for asking questions about PDF documents, built with
LangChain, ChromaDB and Gradio. It ships with the EU AI Act as the sample corpus, but any PDF can be
uploaded through the web UI.

Beyond plain semantic search, the retriever classifies each question and routes it: questions about
document *structure* (how many chapters, list the chapters) are answered from chapter metadata
without a vector search, and questions scoped to a single chapter are answered from a
metadata-filtered similarity search.

## Features

- **PDF Q&A chat** — Gradio UI: upload a PDF, it is chunked, embedded and indexed, then chat about it.
- **Query routing** — an LLM classifier labels each question `structural`, `chapter_filtered` or
  `semantic` and picks the matching retrieval strategy (`retriever.py`).
- **Chapter metadata** — chapter headings are detected while loading (Roman or Arabic numerals) and
  every chunk carries `chapter_number`, `chapter_title` and page ranges (`vector.py`).
- **Pluggable LLM** — Ollama (local), Google Gemini or OpenAI, selected by `LLM_PROVIDER`.
- **Auth** — email/password login on the Gradio app, bcrypt hashes from `users.json` or env vars.
- **Observability** — OpenTelemetry logs and traces (including ChromaDB instrumentation) exported
  over OTLP/HTTP.
- **Deployment** — multi-stage Dockerfile, Compose stack, GitHub Actions build to GHCR and deploy to
  a VPS.

## Architecture

```
gradio_app.py      Gradio UI: upload, chat, sources tab, login
  ├─ auth.py       bcrypt credential check (users.json / AUTH_USER env)
  ├─ llm.py        LLM factory: ollama | gemini | openai
  ├─ vector.py     PDF load → chapter metadata → split → embed → Chroma (HTTP client)
  ├─ retriever.py  query classification + semantic / chapter-filtered / structural answering
  └─ logger.py     OpenTelemetry logging + tracing setup

main.py            CLI entry point: index EU_AI_Act.pdf and run a sample query
scripts/           hash_password.py, list_gemini_models.py
requirements/      feature specs and test plans that drove the implementation
tests/             pytest suite (auth, chapter metadata, query routing, UI wiring)
```

Embeddings use `sentence-transformers/all-mpnet-base-v2` via HuggingFace by default
(`embed_documents_with_ollama` is available as an alternative). Chunking is
`RecursiveCharacterTextSplitter` at 1000 characters with 200 overlap. ChromaDB is always accessed as
a **server** over HTTP — there is no embedded mode — so a Chroma instance must be reachable at
`CHROMA_HOST:CHROMA_PORT`.

Collections:

| Collection | Written by |
|---|---|
| `EU_AI_Act_huggingface` | `main.py` (bundled PDF) |
| `gradio_current_pdf` | the Gradio app (re-created on each upload) |

## Quick start (Docker Compose)

The Compose stack runs the app plus a ChromaDB server. It expects an external Docker network named
`nginx_proxy_net` and, if you keep the OTel settings, a reachable `otel-lgtm` collector.

```bash
# 1. Credentials: create users.json with at least one user
python scripts/hash_password.py 'my-secret-password'
cat > users.json <<'JSON'
[{"email": "you@example.com", "password_hash": "<hash printed above>"}]
JSON

# 2. Provider key (LLM_PROVIDER is set to openai in docker-compose.yml)
export OPENAI_API_KEY=sk-...

# 3. Up
docker network create nginx_proxy_net   # once, if it does not exist
docker compose up --build
```

The app listens on port 7860 inside the Compose network (`expose`, not `ports`), and is intended to
sit behind an nginx-proxy / Let's Encrypt companion — see the `VIRTUAL_HOST` and `LETSENCRYPT_HOST`
variables in `docker-compose.yml`. To reach it directly instead, add a `ports: ["7860:7860"]` mapping.

`users.json` is mounted as a Docker secret at `/run/secrets/users_json` rather than passed as an env
var, because bcrypt hashes contain `$`, which Compose variable interpolation would mangle.

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate   # Python 3.13 (see .python-version)
pip install -r requirements.txt

# ChromaDB server (the code never uses embedded Chroma)
docker run -d -p 8000:8000 -v "$PWD/chroma-data:/data" chromadb/chroma:1.5.3
export CHROMA_HOST=localhost

# Credentials (see step 1 above) and a provider key
export LLM_PROVIDER=openai OPENAI_API_KEY=sk-...

python -m gradio_app     # UI on http://127.0.0.1:7860
```

To run the non-interactive pipeline against the bundled EU AI Act PDF:

```bash
python main.py
```

Ollama instead of a hosted provider:

```bash
export LLM_PROVIDER=ollama LOCAL_LLM_BASE=http://localhost:11434 LOCAL_LLM_MODEL=qwen3
```

## Configuration

Values are read from the environment first, then from a local `.env` file (which is git-ignored).

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` \| `gemini` \| `openai` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | – / `gpt-4o-mini` | OpenAI provider |
| `GOOGLE_API_KEY` / `GEMINI_MODEL` | – / `gemini-2.0-flash-lite` | Gemini provider |
| `LOCAL_LLM_BASE` / `LOCAL_LLM_MODEL` | `http://localhost:11434` / `qwen3` | Ollama provider |
| `LOCAL_EMBEDDING_MODEL` | `qwen3-embedding` | Ollama embeddings (optional path) |
| `CHROMA_HOST` / `CHROMA_PORT` / `CHROMA_SSL` | `chromadb` / `8000` / `false` | Chroma server |
| `AUTH_USERS_FILE` | `users.json` | JSON list of `{email, password_hash}` |
| `AUTH_USER` / `AUTH_PASSWORD_HASH` | – | Single-user fallback when no users file |
| `GRADIO_SERVER_NAME` / `GRADIO_SERVER_PORT` | `127.0.0.1` / `7860` | UI bind address |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | – | OTLP/HTTP base URL; telemetry is off when unset |
| `OTEL_SERVICE_NAME` | `raglangchain` | Service name in traces and logs |

Logins are denied outright when no users are configured.

## Tests

```bash
pytest
```

The suite covers password hashing, the auth module, chapter-metadata extraction, structural query
routing and the Gradio/auth wiring. No LLM or Chroma server is required — external calls are stubbed.

## CI/CD

`.github/workflows/docker-image.yml` builds the image on every push and PR and pushes it to
`ghcr.io/eusorov/raglangchain` (tag `latest` on `master`, branch name otherwise), then calls
`docker-deploy-vps.yml`, which copies the Compose files to a VPS over SSH, writes `users.json` from
repository secrets, and restarts the stack using `docker-compose.deploy.yml` (which swaps the local
build for the pre-built image).
