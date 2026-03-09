# Requirements: Gradio GUI for PDF Q&A Chat

This document describes the requirements for a feature that the planner agent should turn into a technical plan. The implementer will then build according to that plan.

## Goal

Add a **Gradio-based GUI** so that a user can upload a PDF file and ask questions about it in a chat interface. Answers should be generated using the existing RAG pipeline (retriever + LLM).

## Must-have requirements

1. **Gradio GUI**
   - The application must expose a web UI built with Gradio.
   - The UI should be the primary way to use the app (e.g. `gradio` or `python -m gradio_app` starts the server).

2. **PDF upload**
   - The user must be able to upload a PDF file through the GUI (e.g. Gradio file upload component).
   - After upload, the system should process the PDF: load pages, split into chunks, embed, and store in the vector DB (reusing existing logic in `vector.py`).
   - Only one PDF should be in scope at a time (per session or per “current document”); uploading a new PDF can replace or reset the current document.

3. **Chat about the PDF**
   - The user can ask questions in a chat interface (e.g. Gradio Chatbot or similar).
   - Each question is answered using the current PDF’s content via the existing RAG flow: retrieve relevant chunks from the vector store, then generate an answer with the LLM (reusing `Retriever` and LLM setup from `main.py`).
   - Chat history (questions and answers) should be visible in the UI for the current session.

4. **Reuse existing code**
   - Use the current stack: LangChain, Chroma, existing `vector.py` (load, split, embed, create_db), and `retriever.py` (e.g. `generate` or `generate_with_qa`).
   - Use the same config as today: `.env` for `LOCAL_LLM_BASE`, `LOCAL_LLM_MODEL`, `LOCAL_EMBEDDING_MODEL`; existing embedding and LLM choices (e.g. Ollama, HuggingFace) should remain usable.

5. **LLM provider choice**
   - The user must be able to choose between using a local LLM and using the OpenAI API.
   - The application should support configuration for both options through environment variables and/or the UI.
   - If OpenAI is selected, the app should use an `OPENAI_API_KEY` (and model setting if needed).
   - If local LLM is selected, the app should continue to use the existing local configuration such as `LOCAL_LLM_BASE` and `LOCAL_LLM_MODEL`.
   - The planner should include how provider selection is wired into app configuration, runtime initialization, and error handling when required credentials are missing.

6. **Containerization**
   - The project should include a `Dockerfile` to build and run the application in a container.
   - The project should include a `docker-compose.yml` (or `compose.yaml`) to run the application locally with the required configuration.
   - The planner should include how environment variables, app startup, exposed ports, and persistent data (for example Chroma storage) are handled in Docker.
   - The planner should consider how the app connects to a local LLM service versus OpenAI when running inside Docker.

## Nice-to-have (optional)

- Clear indication when the PDF is still being processed (e.g. “Indexing…” or disabled chat until ready).
- Option to reset/clear the current PDF and start with a new upload.
- Display or link to source chunks used for the last answer (e.g. expandable section or tooltip).

## Out of scope

- Multi-PDF or multi-document selection in one session (single PDF per “session” or current document is enough).
- User authentication, persistence of chat across server restarts, or deployment/HTTPS (local or simple `share=False` Gradio is fine).

## Context for the planner

- **Existing modules:** `main.py` (entry point, hardcoded PDF path and query), `vector.py` (PDF load, split, embed, Chroma create_db/collection checks), `retriever.py` (retrieve, generate, generate_with_qa, generate_with_message).
- **Config:** `.env` with `LOCAL_LLM_BASE`, `LOCAL_LLM_MODEL`, `LOCAL_EMBEDDING_MODEL`; Chroma persist dir and collection name in `vector.py`.
- **New config requirement:** add support for OpenAI configuration as well, such as `OPENAI_API_KEY` and an OpenAI model name variable.
- **Dependencies:** Project already uses LangChain, Chroma, PyPDF; Gradio will need to be added.
- **Deployment requirement:** add container support with `Dockerfile` and Docker Compose configuration.

The planner should produce a technical plan that the implementer can follow to add the Gradio UI, wire PDF upload to the existing pipeline, and connect the chat to the RAG retriever and LLM.
