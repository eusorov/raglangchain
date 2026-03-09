# Requirements: Structural Query Routing in RAG

This document describes the requirements for extending the retriever to handle structural questions about a PDF document. The planner agent should use it to produce a technical plan; the implementer will then build according to that plan.

## Goal

Users can currently only ask semantic questions about the PDF content (e.g. "What does the Act say about high-risk AI?"). After this change they will also be able to ask:

- **Structural questions:** "How many chapters are there?", "List all chapter titles", "Show me the table of contents"
- **Chapter-filtered questions:** "What is chapter 2 about?", "Show me the content of chapter 3", "Summarise the second chapter"

## Background

The chapter metadata feature (`4_add_chapter_metadata.md`) already stores `chapter_number`, `chapter_title`, `chapter_page_start`, and `chapter_page_end` on every chunk in ChromaDB. This requirement builds on top of that by making the retriever aware of those fields.

## Must-have requirements

### 1. Query classification using the LLM

Every incoming user question must be classified into one of three types before retrieval is attempted:

| Type | Description | Example questions |
|---|---|---|
| `structural` | Questions about the document's structure, not its content | "How many chapters?", "List all chapters", "Table of contents", "What are the chapter titles?" |
| `chapter_filtered` | Questions about the content of a specific chapter | "What is chapter 2 about?", "Show me chapter 3", "Summarise the second chapter", "Tell me about Chapter II" |
| `semantic` | All other content questions (current behaviour) | "What does the Act say about AI providers?", "Define high-risk AI" |

Classification must be performed by the **same LLM** that is already used for answering (not by regex or a separate model). Use `llm.with_structured_output()` with a Pydantic schema to get a reliable, typed result. The classifier must:

- Return the category label and, for `chapter_filtered`, the chapter number as an integer.
- Convert ordinals ("second" → 2) and Roman numerals ("II" → 2) to integers.
- Fall back to `("semantic", None)` on any error, so the app never crashes.

### 2. Structural answer path

When the query is `structural`:

- Read the chapter structure directly from ChromaDB metadata (no vector similarity search needed).
- Deduplicate chunks by `chapter_number` to build a list of `{number, title, page_start, page_end}` dicts.
- Format the list as plain text and pass it to the LLM with the user's question.
- Return an empty source-documents list (answers come from metadata, not from text chunks).

### 3. Chapter-filtered answer path

When the query is `chapter_filtered`:

- Apply a ChromaDB `where` filter (`{"chapter_number": N}`) so that vector similarity search is restricted to chunks from the requested chapter only.
- Run the same LangChain chain as the existing `generate_with_message` method, but over the filtered chunk set.
- If no chunks are found for the requested chapter number, return a graceful "no content found" message instead of an error.

### 4. Semantic answer path (unchanged)

When the query is `semantic`, the existing `generate_with_message` behaviour must remain exactly as it is today. This requirement must not change the semantic path.

### 5. Wiring into the Gradio app

The `generate_response()` function in `gradio_app.py` must be updated to call the classifier first and dispatch to the correct retriever method. All other parts of `gradio_app.py` (status bar, source display, history, reset) must remain unchanged.

- Log which query type was selected for each request (for observability).
- If the LLM classifier falls back to `semantic` due to an error, log a warning so the issue is visible in traces.

## Out of scope

- Regex-based query classification (replaced by the LLM classifier).
- Multi-chapter queries (e.g. "compare chapters 2 and 3") — treat as semantic.
- Sub-chapter or article-level filtering.
- Changes to the vector indexing pipeline or chunk splitting logic.
- Changes to the authentication layer.

## Context for the planner

- **Files to modify:** `retriever.py` and `gradio_app.py`.
- **`retriever.py` today:** Contains the `Retriever` class with `retrieve`, `generate`, `generate_with_message`. Has no imports from `pydantic` or `typing`. `ChatPromptTemplate` and `StrOutputParser` are already imported.
- **`gradio_app.py` today:** `generate_response()` always calls `retriever.generate_with_message(message, llm, k=10)`. The `llm` object is a module-level variable imported from `llm.py` and is in scope inside the function.
- **LLM providers in use:** Ollama (`ChatOllama`), Gemini (`ChatGoogleGenerativeAI`), OpenAI (`ChatOpenAI`), selected via `LLM_PROVIDER` env var. All three support `with_structured_output()` with a Pydantic model.
- **Chapter metadata already in ChromaDB:** Every chunk has `chapter_number` (int, `-1` for pre-chapter pages), `chapter_title` (str), `chapter_page_start` (int), `chapter_page_end` (int). The raw collection is accessible via `self.db._collection` on a LangChain `Chroma` object.
- **Pydantic version:** `pydantic==2.12.5` (v2) is installed.

The planner should produce a step-by-step technical plan that the implementer can follow to add the classifier, the new retriever methods, and the dispatch logic in `gradio_app.py`.
