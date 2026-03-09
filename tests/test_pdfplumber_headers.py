"""Tests for pdfplumber-based header detection in vector.py.

Covers _estimate_body_font_size, _extract_headers_with_pdfplumber,
_assign_chapter_number, extract_chapter_structure(file_path=...), and
the load_documents file_path pass-through.
"""
import sys
from contextlib import contextmanager
from types import ModuleType
from unittest.mock import MagicMock, patch, call

import pytest
from langchain_core.documents import Document

# ---------------------------------------------------------------------------
# Bootstrap stubs so vector.py imports cleanly (same pattern as test_chapter_metadata.py)
# ---------------------------------------------------------------------------
if "logger" not in sys.modules:
    _logger_stub = ModuleType("logger")
    _logger_stub.setup_otel_logging = MagicMock(return_value=None)  # type: ignore[attr-defined]
    sys.modules["logger"] = _logger_stub

import chromadb as _chromadb  # noqa: E402

_real_http_client = _chromadb.HttpClient
_chromadb.HttpClient = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
try:
    import vector  # noqa: E402
    from vector import (
        _estimate_body_font_size,
        _extract_headers_with_pdfplumber,
        _assign_chapter_number,
        _extract_chapters_pdfplumber,
        extract_chapter_structure,
        load_documents,
    )
finally:
    _chromadb.HttpClient = _real_http_client


# ---------------------------------------------------------------------------
# Helpers for building mock pdfplumber objects
# ---------------------------------------------------------------------------

def _make_char(size: float, text: str = "x") -> dict:
    return {"size": size, "text": text}


def _make_word(text: str, size: float, top: float) -> dict:
    return {"text": text, "size": size, "top": top, "x0": 0.0, "x1": 50.0, "bottom": top + 12}


@contextmanager
def _mock_pdfplumber(pages_chars: list[list[dict]], pages_words: list[list[dict]], page_height: float = 800.0):
    """
    Context manager that patches pdfplumber.open so each page has
    .chars = pages_chars[i]  and  .extract_words(...) = pages_words[i].
    """
    import pdfplumber as _pdfplumber

    mock_pages = []
    for chars, words in zip(pages_chars, pages_words):
        page = MagicMock()
        page.chars = chars
        page.height = page_height
        page.extract_words.return_value = words
        mock_pages.append(page)

    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = mock_pages

    with patch.object(_pdfplumber, "open", return_value=mock_pdf):
        yield mock_pdf


def _docs(pages: list[int]) -> list[Document]:
    """Create minimal page-level Documents with 0-based 'page' metadata."""
    return [Document(page_content=f"body text page {p}", metadata={"page": p}) for p in pages]


# ---------------------------------------------------------------------------
# TestEstimateBodyFontSize
# ---------------------------------------------------------------------------

class TestEstimateBodyFontSize:

    def test_returns_mode_font_size(self):
        chars = [_make_char(10.0)] * 5 + [_make_char(14.0)] * 2
        with _mock_pdfplumber([chars], [[]]):
            result = _estimate_body_font_size("dummy.pdf")
        assert result == 10.0

    def test_rounds_font_size_to_one_decimal(self):
        # 10.049 and 10.051 both round to 10.0 — treated as same size
        chars = [{"size": 10.049, "text": "a"}] * 3 + [{"size": 10.051, "text": "b"}] * 3
        with _mock_pdfplumber([chars], [[]]):
            result = _estimate_body_font_size("dummy.pdf")
        assert result == 10.0

    def test_returns_default_when_no_chars(self):
        with _mock_pdfplumber([[]], [[]]):
            result = _estimate_body_font_size("dummy.pdf")
        assert result == 10.0

    def test_ignores_chars_with_no_size(self):
        chars = [{"text": "a"}] * 3 + [_make_char(12.0)] * 4
        with _mock_pdfplumber([chars], [[]]):
            result = _estimate_body_font_size("dummy.pdf")
        assert result == 12.0

    def test_aggregates_across_multiple_pages(self):
        page1 = [_make_char(10.0)] * 3
        page2 = [_make_char(10.0)] * 3 + [_make_char(16.0)]
        with _mock_pdfplumber([page1, page2], [[], []]):
            result = _estimate_body_font_size("dummy.pdf")
        assert result == 10.0


# ---------------------------------------------------------------------------
# TestExtractHeadersWithPdfplumber
# ---------------------------------------------------------------------------

class TestExtractHeadersWithPdfplumber:

    def test_returns_header_for_large_text_in_top_half(self):
        words = [_make_word("GENERAL", 14.0, 100.0), _make_word("PROVISIONS", 14.0, 100.0)]
        with _mock_pdfplumber([[]], [words], page_height=800.0):
            headers = _extract_headers_with_pdfplumber("dummy.pdf", body_size=10.0)
        assert len(headers) == 1
        assert headers[0]["text"] == "GENERAL PROVISIONS"
        assert headers[0]["page_1based"] == 1

    def test_ignores_large_text_in_bottom_half(self):
        # top=450 > 800*0.5=400 → bottom half → ignored
        words = [_make_word("FOOTER", 14.0, 450.0)]
        with _mock_pdfplumber([[]], [words], page_height=800.0):
            headers = _extract_headers_with_pdfplumber("dummy.pdf", body_size=10.0)
        assert headers == []

    def test_ignores_text_below_size_threshold(self):
        # threshold = 10.0 * 1.2 = 12.0; word size 11.9 is below
        words = [_make_word("BODY", 11.9, 50.0)]
        with _mock_pdfplumber([[]], [words], page_height=800.0):
            headers = _extract_headers_with_pdfplumber("dummy.pdf", body_size=10.0)
        assert headers == []

    def test_ignores_line_that_is_too_long(self):
        long_text = "A" * 81
        words = [_make_word(long_text, 14.0, 50.0)]
        with _mock_pdfplumber([[]], [words], page_height=800.0):
            headers = _extract_headers_with_pdfplumber("dummy.pdf", body_size=10.0)
        assert headers == []

    def test_ignores_line_that_is_too_short(self):
        words = [_make_word("AB", 14.0, 50.0)]
        with _mock_pdfplumber([[]], [words], page_height=800.0):
            headers = _extract_headers_with_pdfplumber("dummy.pdf", body_size=10.0)
        assert headers == []

    def test_returns_at_most_one_header_per_page(self):
        # Two large-text lines on the same page → only the first (smaller top) is returned
        words = [
            _make_word("FIRST", 14.0, 40.0),
            _make_word("SECOND", 14.0, 80.0),
        ]
        with _mock_pdfplumber([[]], [words], page_height=800.0):
            headers = _extract_headers_with_pdfplumber("dummy.pdf", body_size=10.0)
        assert len(headers) == 1
        assert headers[0]["text"] == "FIRST"

    def test_multi_word_line_joined_correctly(self):
        words = [
            _make_word("General", 14.0, 50.0),
            _make_word("Provisions", 14.0, 50.0),
        ]
        with _mock_pdfplumber([[]], [words], page_height=800.0):
            headers = _extract_headers_with_pdfplumber("dummy.pdf", body_size=10.0)
        assert headers[0]["text"] == "General Provisions"

    def test_returns_empty_list_for_page_with_no_words(self):
        with _mock_pdfplumber([[]], [[]], page_height=800.0):
            headers = _extract_headers_with_pdfplumber("dummy.pdf", body_size=10.0)
        assert headers == []

    def test_headers_from_multiple_pages(self):
        words_p1 = [_make_word("Introduction", 14.0, 50.0)]
        words_p2 = [_make_word("Scope", 14.0, 50.0)]
        with _mock_pdfplumber([[], []], [words_p1, words_p2], page_height=800.0):
            headers = _extract_headers_with_pdfplumber("dummy.pdf", body_size=10.0)
        assert len(headers) == 2
        assert headers[0]["page_1based"] == 1
        assert headers[1]["page_1based"] == 2


# ---------------------------------------------------------------------------
# TestAssignChapterNumber
# ---------------------------------------------------------------------------

class TestAssignChapterNumber:

    def test_digit_prefix_with_dot(self):
        num, title = _assign_chapter_number("3. Enforcement", counter=99)
        assert num == 3
        assert title == "Enforcement"

    def test_digit_prefix_without_dot(self):
        num, title = _assign_chapter_number("5 General Provisions", counter=99)
        assert num == 5
        assert title == "General Provisions"

    def test_roman_numeral_prefix(self):
        num, title = _assign_chapter_number("II. Scope", counter=99)
        assert num == 2
        assert title == "Scope"

    def test_no_number_uses_counter(self):
        num, title = _assign_chapter_number("GENERAL PROVISIONS", counter=7)
        assert num == 7
        assert title == "GENERAL PROVISIONS"

    def test_single_word_no_number_uses_counter(self):
        num, title = _assign_chapter_number("Introduction", counter=1)
        assert num == 1
        assert title == "Introduction"


# ---------------------------------------------------------------------------
# TestExtractChapterStructureWithFilePath (pdfplumber path)
# ---------------------------------------------------------------------------

class TestExtractChapterStructureWithFilePath:

    def _run(self, raw_headers: list[dict], docs: list[Document]) -> list[dict]:
        """Run extract_chapter_structure with file_path by stubbing the two helpers."""
        with (
            patch.object(vector, "_estimate_body_font_size", return_value=10.0),
            patch.object(vector, "_extract_headers_with_pdfplumber", return_value=raw_headers),
        ):
            return extract_chapter_structure(docs, file_path="dummy.pdf")

    def test_numbered_header_uses_explicit_number(self):
        docs = _docs([0, 1])
        raw = [{"page_1based": 1, "text": "3. Enforcement"}]
        chapters = self._run(raw, docs)
        assert len(chapters) == 1
        assert chapters[0]["number"] == 3
        assert chapters[0]["title"] == "Enforcement"

    def test_unnumbered_header_auto_increments(self):
        docs = _docs([0, 1, 2])
        raw = [
            {"page_1based": 1, "text": "General Provisions"},
            {"page_1based": 2, "text": "Scope"},
        ]
        chapters = self._run(raw, docs)
        assert chapters[0]["number"] == 1
        assert chapters[1]["number"] == 2

    def test_duplicate_numbers_skipped(self):
        # Two pages produce the same chapter number — only the first kept
        docs = _docs([0, 1, 2])
        raw = [
            {"page_1based": 1, "text": "1. Introduction"},
            {"page_1based": 2, "text": "1. Introduction continued"},
        ]
        chapters = self._run(raw, docs)
        assert len(chapters) == 1

    def test_page_end_computed_correctly(self):
        docs = _docs([0, 1, 2, 3])
        raw = [
            {"page_1based": 1, "text": "1. First"},
            {"page_1based": 3, "text": "2. Second"},
        ]
        chapters = self._run(raw, docs)
        assert chapters[0]["page_end"] == 2   # page before ch2 starts
        assert chapters[1]["page_end"] == 4   # last page of doc (page 3 = 0-based → 1-based = 4)

    def test_no_headers_returns_empty_list(self):
        docs = _docs([0, 1])
        chapters = self._run([], docs)
        assert chapters == []

    def test_file_path_none_uses_regex_path(self):
        """When file_path is None the legacy regex helper is called, not pdfplumber."""
        docs = [Document(page_content="CHAPTER 1 Introduction\nbody text", metadata={"page": 0})]
        with patch.object(vector, "_estimate_body_font_size") as mock_est:
            chapters = extract_chapter_structure(docs, file_path=None)
        mock_est.assert_not_called()
        assert len(chapters) == 1
        assert chapters[0]["number"] == 1


# ---------------------------------------------------------------------------
# TestLoadDocumentsPassesFilePath
# ---------------------------------------------------------------------------

class TestLoadDocumentsPassesFilePath:

    def test_file_path_passed_to_extract_chapter_structure(self, tmp_path):
        dummy_pdf = tmp_path / "test.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4")  # minimal stub; loader will be mocked

        fake_doc = Document(page_content="body text", metadata={"page": 0})

        with (
            patch("vector.PyPDFLoader") as mock_loader_cls,
            patch.object(vector, "extract_chapter_structure", return_value=[]) as mock_ecs,
        ):
            mock_loader_cls.return_value.load.return_value = [fake_doc]
            load_documents(str(dummy_pdf))

        called_file_path = mock_ecs.call_args.kwargs.get("file_path") or mock_ecs.call_args.args[1]
        assert called_file_path == str(dummy_pdf)
