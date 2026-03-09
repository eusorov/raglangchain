# Requirements: Chapter Metadata on Vector Store Chunks

This document describes the requirements for enriching every chunk stored in ChromaDB with chapter-level structural metadata. The planner agent should turn it into a technical plan; the implementer will then build according to that plan.

## Goal

When a PDF is indexed, each chunk stored in the vector store should carry metadata about the chapter it belongs to: the chapter number, chapter title, and the page range of that chapter. This makes it possible to filter retrieval by chapter and to answer structural questions about the document.

## Must-have requirements

1. **Four new metadata fields on every chunk**
   - `chapter_number` — integer; the chapter number (e.g. `3`). `-1` for pages before the first chapter.
   - `chapter_title` — string; the chapter title (e.g. `"Prohibited AI Practices"`). `""` for pages before the first chapter.
   - `chapter_page_start` — integer; the 1-based page number where this chapter starts. `-1` for pages before the first chapter.
   - `chapter_page_end` — integer; the 1-based page number where this chapter ends (inclusive). `-1` for pages before the first chapter.

2. **Chapter detection by heading regex**
   - Chapters must be detected by scanning page text for headings that match patterns such as `"CHAPTER I"`, `"CHAPTER II"`, `"Chapter 1"`, `"Chapter 2"` (case-insensitive, Roman numerals and Arabic numerals both supported).
   - The regex should look only at the first ~400 characters of each page (headings appear near the top).
   - Roman numerals (I–XIII range is sufficient for EU legislative documents) must be converted to integers.

3. **Metadata propagation via page-level annotation**
   - The chapter metadata must be attached to each page-level `Document` object *before* `split_documents` is called.
   - LangChain's `RecursiveCharacterTextSplitter` copies parent metadata to all child chunks automatically; no changes to `split_documents` are needed.

4. **ChromaDB compatibility**
   - ChromaDB rejects `None` metadata values. Pages before the first detected chapter must use `-1` for integer fields and `""` for string fields.

5. **Backwards compatibility**
   - All existing metadata fields (`pdf_name`, `indexed_at`, `file_modified`, `page`) must remain unchanged.
   - The embedding functions (`embed_documents_with_huggingface`, `embed_documents_with_ollama`) and `split_documents` must not require signature changes.

## Nice-to-have (optional)

- A helper function `get_chapter_structure(documents)` that returns the full list of detected chapters (number, title, page_start, page_end), usable by other parts of the app (e.g. Gradio UI to display a table of contents).

## Out of scope

- LLM-generated chapter summaries.
- A separate metadata store (JSON file or SQLite) for document-level facts.
- Changes to `retriever.py` or `gradio_app.py`.
- Detection of sub-chapters, articles, or sections (only top-level chapters).

## Context for the planner

- **File to modify:** `vector.py` — add `extract_chapter_structure(documents)` helper and update `load_documents()` to call it and annotate each page Document.
- **Existing flow:** `load_documents()` → `split_documents()` → `embed_documents_with_huggingface()`. The new logic fits entirely inside `load_documents()`.
- **PDF loader:** `PyPDFLoader` from `langchain_community.document_loaders`. It produces one `Document` per page; each has `doc.metadata["page"]` (0-based page index).
- **Splitter:** `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)` in `split_documents()`. No changes needed here.
- **Target PDF:** EU AI Act, which uses Roman-numeral chapter headings (e.g. `CHAPTER I`, `CHAPTER II`). The regex must handle both Roman and Arabic numeral styles.

The planner should produce a step-by-step technical plan that the implementer can follow to add `extract_chapter_structure`, wire it into `load_documents`, and verify that all four metadata fields appear on chunks stored in ChromaDB.
