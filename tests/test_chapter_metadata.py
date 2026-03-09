"""Tests for chapter metadata feature: _roman_to_int, extract_chapter_structure, load_documents."""
import copy
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch  # noqa: F401 (patch used in tests)

import pytest
from langchain_core.documents import Document

# ---------------------------------------------------------------------------
# Two targeted stubs so vector.py can be imported without external services:
#
# 1. `logger` — local module; stub setup_otel_logging so it is a no-op.
# 2. `chromadb.HttpClient` — chromadb 1.5.x connects to the server inside the
#    constructor.  We replace the function for the duration of the vector.py
#    import so that `client = get_chroma_http_client()` gets a MagicMock.
#    The rest of the real `chromadb` package is left untouched so that
#    langchain-chroma can import its submodules normally.
# ---------------------------------------------------------------------------
if "logger" not in sys.modules:
    _logger_stub = ModuleType("logger")
    _logger_stub.setup_otel_logging = MagicMock(return_value=None)  # type: ignore[attr-defined]
    sys.modules["logger"] = _logger_stub

import chromadb as _chromadb  # noqa: E402

_real_http_client = _chromadb.HttpClient
_chromadb.HttpClient = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
try:
    from vector import (  # noqa: E402
        _roman_to_int,
        extract_chapter_structure,
        load_documents,
        split_documents,
    )
finally:
    _chromadb.HttpClient = _real_http_client  # restore for any other code that needs it

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def make_page():
    """Factory: return a helper that creates a page-level Document."""
    def _make(content: str, page_index: int) -> Document:
        return Document(page_content=content, metadata={"page": page_index})
    return _make


@pytest.fixture()
def simple_pdf_pages():
    """Three-page PDF: cover page followed by two chapters with inline titles."""
    return [
        Document(page_content="Cover page text.", metadata={"page": 0}),
        Document(
            page_content="CHAPTER I – General Provisions\nIntroductory text.",
            metadata={"page": 1},
        ),
        Document(
            page_content="CHAPTER II – Prohibited AI Practices\nRegulatory text.",
            metadata={"page": 2},
        ),
    ]


# ---------------------------------------------------------------------------
# TestRomanToInt — tests 1–8
# ---------------------------------------------------------------------------

class TestRomanToInt:

    def test_single_char_I(self):
        assert _roman_to_int("I") == 1

    def test_roman_III(self):
        assert _roman_to_int("III") == 3

    def test_roman_XIII(self):
        assert _roman_to_int("XIII") == 13

    def test_roman_lowercase(self):
        assert _roman_to_int("iv") == 4

    def test_roman_with_whitespace(self):
        assert _roman_to_int("  VI  ") == 6

    def test_arabic_raises(self):
        with pytest.raises(ValueError):
            _roman_to_int("3")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            _roman_to_int("")

    def test_mixed_invalid_raises(self):
        with pytest.raises(ValueError):
            _roman_to_int("I3")


# ---------------------------------------------------------------------------
# TestExtractChapterStructure — tests 9–22
# ---------------------------------------------------------------------------

class TestExtractChapterStructure:

    # --- happy path ---

    def test_detects_two_roman_chapters(self, simple_pdf_pages):
        chapters = extract_chapter_structure(simple_pdf_pages)
        assert len(chapters) == 2
        assert chapters[0]["number"] == 1
        assert chapters[1]["number"] == 2

    def test_chapter_titles_extracted(self, simple_pdf_pages):
        chapters = extract_chapter_structure(simple_pdf_pages)
        assert chapters[0]["title"] == "General Provisions"
        assert chapters[1]["title"] == "Prohibited AI Practices"

    def test_page_start_is_1based(self, simple_pdf_pages):
        # CHAPTER I is on the doc with metadata["page"]==1 → page_start must be 2
        chapters = extract_chapter_structure(simple_pdf_pages)
        assert chapters[0]["page_start"] == 2

    def test_page_end_filled_correctly(self, simple_pdf_pages):
        # CHAPTER II starts at page_start=3, so CHAPTER I page_end = 3-1 = 2
        chapters = extract_chapter_structure(simple_pdf_pages)
        assert chapters[0]["page_end"] == 2

    def test_last_chapter_page_end_is_last_page(self, simple_pdf_pages):
        # Last doc has metadata["page"]==2 → last chapter page_end = 2+1 = 3
        chapters = extract_chapter_structure(simple_pdf_pages)
        assert chapters[1]["page_end"] == 3

    def test_arabic_numeral_headings(self, make_page):
        pages = [
            make_page("Chapter 1 – Introduction\nText", 0),
            make_page("Chapter 2 – Background\nText", 1),
        ]
        chapters = extract_chapter_structure(pages)
        assert chapters[0]["number"] == 1
        assert chapters[1]["number"] == 2

    def test_heading_with_dash_separator(self, make_page):
        pages = [make_page("CHAPTER I – General Provisions\nText", 0)]
        chapters = extract_chapter_structure(pages)
        assert chapters[0]["title"] == "General Provisions"

    def test_heading_with_colon_separator(self, make_page):
        pages = [make_page("Chapter I: General Provisions\nText", 0)]
        chapters = extract_chapter_structure(pages)
        assert chapters[0]["title"] == "General Provisions"

    def test_heading_case_insensitive(self, make_page):
        pages = [make_page("chapter i – some title\nText", 0)]
        chapters = extract_chapter_structure(pages)
        assert len(chapters) == 1
        assert chapters[0]["number"] == 1

    # --- edge cases ---

    def test_no_chapter_headings_returns_empty(self, make_page):
        pages = [
            make_page("Introduction text without a chapter heading.", 0),
            make_page("More text with no heading.", 1),
        ]
        assert extract_chapter_structure(pages) == []

    def test_heading_not_in_first_400_chars(self, make_page):
        # Heading placed beyond the 400-char scan window must not be detected
        preamble = "x" * 410
        pages = [make_page(preamble + "CHAPTER I – Title\nText", 0)]
        assert extract_chapter_structure(pages) == []

    def test_chapter_mid_sentence_not_detected(self, make_page):
        # "chapter" not at line start (MULTILINE ^ anchor) must not match
        pages = [make_page("See chapter I for details.\nMore text.", 0)]
        assert extract_chapter_structure(pages) == []

    def test_title_empty_falls_back_to_generic(self, make_page):
        # No title text on the same line as the heading
        pages = [make_page("CHAPTER V\nSome body text.", 0)]
        chapters = extract_chapter_structure(pages)
        assert chapters[0]["title"] == "Chapter 5"

    def test_single_chapter_pdf(self, make_page):
        pages = [
            make_page("CHAPTER I – Only Chapter\nText", 0),
            make_page("Continuation of chapter I.", 1),
        ]
        chapters = extract_chapter_structure(pages)
        assert len(chapters) == 1
        # Last doc metadata["page"]==1 → page_end = 1+1 = 2
        assert chapters[0]["page_end"] == 2


# ---------------------------------------------------------------------------
# TestLoadDocumentsChapterAnnotation — tests 23–28
# ---------------------------------------------------------------------------

_BASE_FAKE_PAGES = [
    Document(page_content="Cover page text.", metadata={"page": 0}),
    Document(
        page_content="CHAPTER I – General Provisions\nIntroductory text.",
        metadata={"page": 1},
    ),
    Document(
        page_content="CHAPTER II – Prohibited AI Practices\nRegulatory text.",
        metadata={"page": 2},
    ),
]

_CHAPTER_FIELDS = (
    "chapter_number",
    "chapter_title",
    "chapter_page_start",
    "chapter_page_end",
)


@pytest.fixture()
def fresh_pages():
    """Deep-copy the fake pages before each test; load_documents mutates metadata in place."""
    return copy.deepcopy(_BASE_FAKE_PAGES)


class TestLoadDocumentsChapterAnnotation:

    def _call_load(self, pages, extra_metadata=None):
        with patch("vector.PyPDFLoader") as mock_cls:
            mock_cls.return_value.load.return_value = pages
            return load_documents("fake.pdf", extra_metadata=extra_metadata)

    def test_chapter_fields_present_on_every_doc(self, fresh_pages):
        docs = self._call_load(fresh_pages)
        for doc in docs:
            for field in _CHAPTER_FIELDS:
                assert field in doc.metadata, f"Missing field {field!r} on page {doc.metadata.get('page')}"

    def test_pre_chapter_page_gets_sentinels(self, fresh_pages):
        docs = self._call_load(fresh_pages)
        cover = docs[0]
        assert cover.metadata["chapter_number"] == -1
        assert cover.metadata["chapter_title"] == ""
        assert cover.metadata["chapter_page_start"] == -1
        assert cover.metadata["chapter_page_end"] == -1

    def test_chapter_page_gets_correct_values(self, fresh_pages):
        docs = self._call_load(fresh_pages)
        ch1_doc = docs[1]
        assert ch1_doc.metadata["chapter_number"] == 1
        assert ch1_doc.metadata["chapter_title"] == "General Provisions"

    def test_existing_base_metadata_preserved(self, fresh_pages):
        docs = self._call_load(fresh_pages)
        for doc in docs:
            assert "pdf_name" in doc.metadata
            assert "indexed_at" in doc.metadata
            assert "page" in doc.metadata

    def test_no_none_values_in_metadata(self, fresh_pages):
        docs = self._call_load(fresh_pages)
        for doc in docs:
            for key, value in doc.metadata.items():
                assert value is not None, (
                    f"None value for key {key!r} on page {doc.metadata.get('page')}"
                )

    def test_extra_metadata_arg_preserved(self, fresh_pages):
        docs = self._call_load(fresh_pages, extra_metadata={"source": "test"})
        for doc in docs:
            assert doc.metadata.get("source") == "test"


# ---------------------------------------------------------------------------
# TestSplitDocumentsInheritChapterMetadata — tests 29–30
# ---------------------------------------------------------------------------

class TestSplitDocumentsInheritChapterMetadata:

    @pytest.fixture()
    def chapter_page(self):
        """Page Document with chapter metadata and enough text to produce multiple chunks."""
        return Document(
            page_content="This is chunk content. " * 120,  # ~2760 chars → splits into 3+ chunks
            metadata={
                "chapter_number": 3,
                "chapter_title": "Test Chapter",
                "chapter_page_start": 5,
                "chapter_page_end": 10,
                "pdf_name": "test.pdf",
                "page": 4,
            },
        )

    def test_chunks_inherit_chapter_number(self, chapter_page):
        chunks = split_documents([chapter_page])
        assert len(chunks) > 1, "Expected multiple chunks from a long page"
        for chunk in chunks:
            assert chunk.metadata["chapter_number"] == 3

    def test_chunks_inherit_all_four_fields(self, chapter_page):
        chunks = split_documents([chapter_page])
        for chunk in chunks:
            assert chunk.metadata["chapter_number"] == 3
            assert chunk.metadata["chapter_title"] == "Test Chapter"
            assert chunk.metadata["chapter_page_start"] == 5
            assert chunk.metadata["chapter_page_end"] == 10
