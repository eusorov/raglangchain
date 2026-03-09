# Test Plan: Chapter Metadata Feature

This document describes the test plan for the chapter metadata feature added in requirement `4_add_chapter_metadata.md`. The implementer should follow this plan to create automated tests.

## Files under test

| File | Type | What to test |
|---|---|---|
| `vector.py` | Unit tests | `_roman_to_int`, `extract_chapter_structure`, chapter annotation inside `load_documents` |

## Test file: `tests/test_chapter_metadata.py`

All tests run without network access — no ChromaDB, no LLM, no real PDF file. Page-level `Document` objects are constructed directly in fixtures.

### Fixtures (in `conftest.py` or at the top of the test file)

- **`make_page`** — factory fixture that returns a helper `make_page(content, page_index)` producing a LangChain `Document` with the given `page_content` and `metadata={"page": page_index}`.
- **`simple_pdf_pages`** — a list of three `Document` objects simulating a minimal PDF:
  - page 0: cover page text with no chapter heading
  - page 1: text starting with `"CHAPTER I\nGeneral Provisions\n..."` (EU-style Roman numeral heading)
  - page 2: text starting with `"CHAPTER II\nProhibited AI Practices\n..."` (second chapter)

---

### Test class: `TestRomanToInt`

Tests for the `_roman_to_int` private helper in `vector.py`. Import it directly: `from vector import _roman_to_int`.

| # | Test name | Input | Expected |
|---|---|---|---|
| 1 | `test_single_char_I` | `"I"` | `1` |
| 2 | `test_roman_III` | `"III"` | `3` |
| 3 | `test_roman_XIII` | `"XIII"` | `13` |
| 4 | `test_roman_lowercase` | `"iv"` | `4` (case-insensitive) |
| 5 | `test_roman_with_whitespace` | `"  VI  "` | `6` (strips whitespace) |
| 6 | `test_arabic_raises` | `"3"` | raises `ValueError` |
| 7 | `test_empty_string_raises` | `""` | raises `ValueError` |
| 8 | `test_mixed_invalid_raises` | `"I3"` | raises `ValueError` |

---

### Test class: `TestExtractChapterStructure`

Tests for `extract_chapter_structure(documents)`. Import: `from vector import extract_chapter_structure`.

#### Happy-path tests

| # | Test name | Setup | Expected |
|---|---|---|---|
| 9 | `test_detects_two_roman_chapters` | `simple_pdf_pages` fixture (pages 0–2) | Returns list of 2 dicts; `chapters[0]["number"] == 1`, `chapters[1]["number"] == 2` |
| 10 | `test_chapter_titles_extracted` | `simple_pdf_pages` fixture | `chapters[0]["title"] == "General Provisions"`, `chapters[1]["title"] == "Prohibited AI Practices"` |
| 11 | `test_page_start_is_1based` | `simple_pdf_pages` (chapter I is on doc with `metadata["page"]==1`) | `chapters[0]["page_start"] == 2` |
| 12 | `test_page_end_filled_correctly` | `simple_pdf_pages` (3 pages, chapter I on page 1, chapter II on page 2) | `chapters[0]["page_end"] == 1` (one page before chapter II starts at page 2) |
| 13 | `test_last_chapter_page_end_is_last_page` | `simple_pdf_pages` (last page has `metadata["page"]==2`) | `chapters[1]["page_end"] == 3` |
| 14 | `test_arabic_numeral_headings` | Pages with `"Chapter 1\nTitle"` and `"Chapter 2\nTitle"` | `chapters[0]["number"] == 1`, `chapters[1]["number"] == 2` |
| 15 | `test_heading_with_dash_separator` | Page text `"CHAPTER I – General Provisions"` | `chapters[0]["title"] == "General Provisions"` |
| 16 | `test_heading_with_colon_separator` | Page text `"Chapter I: General Provisions"` | `chapters[0]["title"] == "General Provisions"` |
| 17 | `test_heading_case_insensitive` | Page text `"chapter i\nsome title"` | Detected; `chapters[0]["number"] == 1` |

#### Edge-case tests

| # | Test name | Setup | Expected |
|---|---|---|---|
| 18 | `test_no_chapter_headings_returns_empty` | Pages with no "chapter" keyword | Returns `[]` |
| 19 | `test_heading_not_in_first_400_chars` | Chapter heading appears at character 500 | Not detected; returns `[]` |
| 20 | `test_chapter_heading_mid_page_not_detected` | Long preamble pushes heading past char 400 | Not detected (heading outside scan window) |
| 21 | `test_title_empty_falls_back_to_generic` | Page text `"CHAPTER V"` with no title on same line | `chapters[0]["title"] == "Chapter 5"` |
| 22 | `test_single_chapter_pdf` | One page with chapter heading | `len(chapters) == 1`; `page_end` equals 1-based last page number |

---

### Test class: `TestLoadDocumentsChapterAnnotation`

Tests for the chapter annotation logic in `load_documents()`. Because `load_documents` calls `PyPDFLoader` on a real file path, **mock `PyPDFLoader`** to avoid needing a real PDF.

Use `unittest.mock.patch` to replace `vector.PyPDFLoader` with a mock whose `.load()` returns a controlled list of `Document` objects.

| # | Test name | Setup | Expected |
|---|---|---|---|
| 23 | `test_chapter_fields_present_on_every_doc` | Mock loader returns `simple_pdf_pages`; call `load_documents("fake.pdf")` | Every returned doc has keys `chapter_number`, `chapter_title`, `chapter_page_start`, `chapter_page_end` in `.metadata` |
| 24 | `test_pre_chapter_page_gets_sentinels` | Cover page (page 0) has no heading | `doc.metadata["chapter_number"] == -1`, `doc.metadata["chapter_title"] == ""`, `chapter_page_start == -1`, `chapter_page_end == -1` |
| 25 | `test_chapter_page_gets_correct_values` | Page 1 has `"CHAPTER I\nGeneral Provisions"` | `doc.metadata["chapter_number"] == 1`, `doc.metadata["chapter_title"] == "General Provisions"` |
| 26 | `test_existing_base_metadata_preserved` | Any page | `pdf_name`, `indexed_at`, `page` remain in `.metadata` after chapter annotation |
| 27 | `test_no_none_values_in_metadata` | All pages (pre-chapter and in-chapter) | No `metadata` value is `None` (ChromaDB constraint) |
| 28 | `test_extra_metadata_arg_preserved` | Call `load_documents("fake.pdf", extra_metadata={"source": "test"})` | `doc.metadata["source"] == "test"` present alongside chapter fields |

---

### Test class: `TestSplitDocumentsInheritChapterMetadata`

Tests that `split_documents` propagates chapter metadata from page-level Documents to all child chunks. No mocking needed — `split_documents` is a pure function over `Document` objects.

| # | Test name | Setup | Expected |
|---|---|---|---|
| 29 | `test_chunks_inherit_chapter_number` | Create a `Document` with 2000-char content and `metadata={"chapter_number": 3, "chapter_title": "Test", "chapter_page_start": 5, "chapter_page_end": 10}`; call `split_documents([doc])` | Every chunk in the result has `metadata["chapter_number"] == 3` |
| 30 | `test_chunks_inherit_all_four_fields` | Same setup as above | All four chapter fields present on every chunk with correct values |

---

## Mocking strategy

For tests 23–28, patch `PyPDFLoader` at the `vector` module level:

```python
from unittest.mock import MagicMock, patch
from langchain_core.documents import Document

fake_pages = [
    Document(page_content="Cover page text", metadata={"page": 0}),
    Document(page_content="CHAPTER I\nGeneral Provisions\nSome text", metadata={"page": 1}),
    Document(page_content="CHAPTER II\nProhibited AI Practices\nSome text", metadata={"page": 2}),
]

with patch("vector.PyPDFLoader") as mock_loader_cls:
    mock_loader_cls.return_value.load.return_value = fake_pages
    docs = load_documents("fake.pdf")
```

This avoids any filesystem or PDF-parsing dependency.

---

## Running the tests

```bash
pytest tests/test_chapter_metadata.py -v
```

All 30 tests should pass without network, ChromaDB, or LLM access.

## Implementation notes for the implementer

- Import `_roman_to_int` and `extract_chapter_structure` directly from `vector`: `from vector import _roman_to_int, extract_chapter_structure`. Both are module-level functions despite the `_` prefix.
- `load_documents` triggers the OTel/ChromaDB import chain at module load time. Use the same `sys.modules` stubbing pattern from `test_gradio_auth_wiring.py` (`_isolate_gradio_app` fixture) if needed — or patch just `vector.PyPDFLoader` after `import vector`.
- For `split_documents` tests (29–30), no mocking is needed: `split_documents` only calls `RecursiveCharacterTextSplitter` which has no side effects.
- Use `langchain_core.documents.Document` (not `langchain_community`) to construct fake page objects.
- Do not hardcode specific chapter titles from the real EU AI Act PDF; test data should be self-contained in the test file.
