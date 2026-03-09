"""Tests for structural query routing: classify_query, get_chapter_structure,
answer_structural, generate_chapter_filtered, and generate_response dispatch."""
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from retriever import QueryClassification, Retriever, classify_query

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_classifier_llm(query_type: str, chapter_number=None):
    """
    Return a mock LLM whose with_structured_output chain returns
    QueryClassification(query_type=..., chapter_number=...).

    classify_query builds: chain = prompt | structured_llm
    LangChain wraps structured_llm as RunnableLambda, so it is called
    as structured_llm(chat_prompt_value) → returns structured_llm.return_value.
    """
    result = QueryClassification(query_type=query_type, chapter_number=chapter_number)
    mock_structured_llm = MagicMock(return_value=result)
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured_llm
    return mock_llm


def _make_answering_llm(answer: str = "test answer"):
    """
    Return a mock LLM that, when used inside a prompt | llm | StrOutputParser()
    chain, causes chain.invoke(...) to return answer.

    LangChain wraps the mock as RunnableLambda, calling mock_llm(chat_prompt_value).
    StrOutputParser then calls result.content, so we return an AIMessage.
    """
    return MagicMock(return_value=AIMessage(content=answer))


def _make_db_with_chapters(chapters: list[dict]):
    """Return a mock Chroma db whose _collection.get returns chapter metadata rows."""
    rows = [
        {
            "chapter_number":     ch["number"],
            "chapter_title":      ch["title"],
            "chapter_page_start": ch["page_start"],
            "chapter_page_end":   ch["page_end"],
        }
        for ch in chapters
    ]
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"metadatas": rows}
    mock_db = MagicMock()
    mock_db._collection = mock_collection
    return mock_db


def _make_db_with_retriever_docs(docs: list[Document]):
    """Return a mock Chroma db whose as_retriever().invoke() returns docs."""
    mock_inner = MagicMock()
    mock_inner.invoke.return_value = docs
    mock_db = MagicMock()
    mock_db.as_retriever.return_value = mock_inner
    return mock_db


# ---------------------------------------------------------------------------
# TestClassifyQuery — tests 1–8
# ---------------------------------------------------------------------------

class TestClassifyQuery:

    # --- happy path ---

    def test_structural_query(self):
        llm = _make_classifier_llm("structural")
        assert classify_query("How many chapters are there?", llm) == ("structural", None)

    def test_chapter_filtered_query(self):
        llm = _make_classifier_llm("chapter_filtered", chapter_number=2)
        assert classify_query("What is chapter 2 about?", llm) == ("chapter_filtered", 2)

    def test_semantic_query(self):
        llm = _make_classifier_llm("semantic")
        assert classify_query("What does the Act say about AI?", llm) == ("semantic", None)

    def test_chapter_filtered_with_higher_chapter_number(self):
        llm = _make_classifier_llm("chapter_filtered", chapter_number=5)
        assert classify_query("Show me chapter 5", llm) == ("chapter_filtered", 5)

    def test_chapter_number_is_integer(self):
        llm = _make_classifier_llm("chapter_filtered", chapter_number=3)
        _, chapter_number = classify_query("Tell me about chapter 3", llm)
        assert isinstance(chapter_number, int)

    # --- fallback / error tests ---

    def test_with_structured_output_exception_falls_back(self):
        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = RuntimeError("unsupported")
        assert classify_query("any question", mock_llm) == ("semantic", None)

    def test_chain_invoke_exception_falls_back(self):
        mock_structured_llm = MagicMock(side_effect=ValueError("bad output"))
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured_llm
        assert classify_query("any question", mock_llm) == ("semantic", None)

    def test_chain_returns_none_falls_back(self):
        # If the chain returns None, accessing .query_type raises AttributeError → fallback
        mock_structured_llm = MagicMock(return_value=None)
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured_llm
        assert classify_query("any question", mock_llm) == ("semantic", None)


# ---------------------------------------------------------------------------
# TestGetChapterStructure — tests 9–13
# ---------------------------------------------------------------------------

class TestGetChapterStructure:

    def test_returns_sorted_chapters(self):
        db = _make_db_with_chapters([
            {"number": 3, "title": "Chapter C", "page_start": 11, "page_end": 15},
            {"number": 1, "title": "Chapter A", "page_start": 1,  "page_end": 5},
            {"number": 2, "title": "Chapter B", "page_start": 6,  "page_end": 10},
        ])
        chapters = Retriever(db).get_chapter_structure()
        assert [c["number"] for c in chapters] == [1, 2, 3]

    def test_deduplicates_by_chapter_number(self):
        # Chapter 1 repeated 3 times (many chunks per chapter), chapter 2 once
        db = _make_db_with_chapters([
            {"number": 1, "title": "Chapter A", "page_start": 1, "page_end": 5},
            {"number": 1, "title": "Chapter A", "page_start": 1, "page_end": 5},
            {"number": 1, "title": "Chapter A", "page_start": 1, "page_end": 5},
            {"number": 2, "title": "Chapter B", "page_start": 6, "page_end": 10},
        ])
        chapters = Retriever(db).get_chapter_structure()
        assert len(chapters) == 2

    def test_empty_collection_returns_empty_list(self):
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"metadatas": []}
        mock_db = MagicMock()
        mock_db._collection = mock_collection
        chapters = Retriever(mock_db).get_chapter_structure()
        assert chapters == []

    def test_gt_filter_passed_to_collection(self):
        db = _make_db_with_chapters([])
        Retriever(db).get_chapter_structure()
        db._collection.get.assert_called_once_with(
            where={"chapter_number": {"$gt": 0}},
            include=["metadatas"],
        )

    def test_correct_fields_in_returned_dicts(self):
        db = _make_db_with_chapters([
            {"number": 1, "title": "General Provisions", "page_start": 3, "page_end": 7},
        ])
        chapters = Retriever(db).get_chapter_structure()
        ch = chapters[0]
        assert ch["number"] == 1
        assert ch["title"] == "General Provisions"
        assert ch["page_start"] == 3
        assert ch["page_end"] == 7


# ---------------------------------------------------------------------------
# TestAnswerStructural — tests 14–18
# ---------------------------------------------------------------------------

_TWO_CHAPTERS = [
    {"number": 1, "title": "General Provisions",      "page_start": 1,  "page_end": 7},
    {"number": 2, "title": "Prohibited AI Practices",  "page_start": 8,  "page_end": 15},
]


class TestAnswerStructural:

    def test_returns_llm_answer_and_empty_sources(self):
        db = _make_db_with_chapters(_TWO_CHAPTERS)
        llm = _make_answering_llm("There are two chapters.")
        answer, sources = Retriever(db).answer_structural("How many chapters?", llm)
        assert answer == "There are two chapters."
        assert sources == []

    def test_no_chapters_returns_no_structure_message(self):
        db = _make_db_with_chapters([])
        llm = _make_answering_llm()
        answer, sources = Retriever(db).answer_structural("List chapters", llm)
        assert "No chapter structure" in answer
        assert sources == []

    def test_structure_text_includes_all_chapter_titles(self):
        db = _make_db_with_chapters(_TWO_CHAPTERS)
        llm = _make_answering_llm()
        Retriever(db).answer_structural("List chapters", llm)
        context_str = str(llm.call_args)
        assert "General Provisions" in context_str
        assert "Prohibited AI Practices" in context_str

    def test_structure_text_includes_chapter_count(self):
        three_chapters = _TWO_CHAPTERS + [
            {"number": 3, "title": "Third Chapter", "page_start": 16, "page_end": 20},
        ]
        db = _make_db_with_chapters(three_chapters)
        llm = _make_answering_llm()
        Retriever(db).answer_structural("How many chapters?", llm)
        context_str = str(llm.call_args)
        assert "3 chapter" in context_str

    def test_source_docs_always_empty(self):
        db = _make_db_with_chapters(_TWO_CHAPTERS)
        llm = _make_answering_llm("answer")
        _, sources = Retriever(db).answer_structural("any question", llm)
        assert sources == []


# ---------------------------------------------------------------------------
# TestGenerateChapterFiltered — tests 19–24
# ---------------------------------------------------------------------------

class TestGenerateChapterFiltered:

    def test_returns_answer_and_source_docs(self):
        docs = [
            Document(page_content="Chapter 2 content.", metadata={"chapter_number": 2}),
            Document(page_content="More chapter 2.",    metadata={"chapter_number": 2}),
        ]
        db = _make_db_with_retriever_docs(docs)
        llm = _make_answering_llm("Chapter 2 is about prohibitions.")
        answer, sources = Retriever(db).generate_chapter_filtered("What is ch 2 about?", llm, 2)
        assert answer == "Chapter 2 is about prohibitions."
        assert len(sources) == 2

    def test_no_chunks_returns_no_content_message(self):
        db = _make_db_with_retriever_docs([])
        llm = _make_answering_llm()
        answer, sources = Retriever(db).generate_chapter_filtered("Show chapter 4", llm, 4)
        assert "No content found for chapter" in answer
        assert sources == []

    def test_filter_passed_to_as_retriever(self):
        db = _make_db_with_retriever_docs([
            Document(page_content="content", metadata={})
        ])
        llm = _make_answering_llm()
        Retriever(db).generate_chapter_filtered("query", llm, chapter_number=3)
        call_kwargs = db.as_retriever.call_args.kwargs
        assert call_kwargs["search_kwargs"]["filter"] == {"chapter_number": 3}

    def test_default_k_is_10(self):
        db = _make_db_with_retriever_docs([Document(page_content="x", metadata={})])
        llm = _make_answering_llm()
        Retriever(db).generate_chapter_filtered("query", llm, chapter_number=1)
        call_kwargs = db.as_retriever.call_args.kwargs
        assert call_kwargs["search_kwargs"]["k"] == 10

    def test_custom_k_passed_through(self):
        db = _make_db_with_retriever_docs([Document(page_content="x", metadata={})])
        llm = _make_answering_llm()
        Retriever(db).generate_chapter_filtered("query", llm, chapter_number=1, k=5)
        call_kwargs = db.as_retriever.call_args.kwargs
        assert call_kwargs["search_kwargs"]["k"] == 5

    def test_no_content_message_includes_chapter_number(self):
        db = _make_db_with_retriever_docs([])
        llm = _make_answering_llm()
        answer, _ = Retriever(db).generate_chapter_filtered("query", llm, chapter_number=7)
        assert "7" in answer


# ---------------------------------------------------------------------------
# TestGenerateResponseDispatch — tests 25–28
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def _stub_for_dispatch(monkeypatch):
    """Stub heavy modules so gradio_app can be imported; delete it after each test."""
    for mod_name in (
        "vector", "llm", "retriever", "logger",
        "opentelemetry", "opentelemetry.instrumentation",
        "opentelemetry.instrumentation.chromadb", "chromadb",
    ):
        if mod_name not in sys.modules:
            monkeypatch.setitem(sys.modules, mod_name, ModuleType(mod_name))

    stub_vector = sys.modules["vector"]
    for attr in ("GRADIO_COLLECTION_NAME", "create_db", "chroma_collection_exists",
                 "get_collection_sample_metadata", "load_documents", "split_documents",
                 "embed_documents_with_huggingface"):
        setattr(stub_vector, attr, MagicMock())

    sys.modules["llm"].llm = MagicMock()

    stub_retriever = sys.modules["retriever"]
    stub_retriever.Retriever = MagicMock()
    stub_retriever.classify_query = MagicMock(return_value=("semantic", None))

    sys.modules["logger"].setup_otel_logging = MagicMock()

    monkeypatch.delitem(sys.modules, "gradio_app", raising=False)
    yield
    monkeypatch.delitem(sys.modules, "gradio_app", raising=False)


def _call_generate_response(classify_return, method_return=("LLM answer", [])):
    """
    Import gradio_app (using already-installed stubs), patch classify_query and
    Retriever to control dispatch, call generate_response, and return the mock
    Retriever instance so callers can assert on it.
    """
    import gradio_app

    mock_instance = MagicMock()
    mock_instance.answer_structural.return_value = method_return
    mock_instance.generate_chapter_filtered.return_value = method_return
    mock_instance.generate_with_message.return_value = method_return

    history = [{"role": "user", "content": "test question"}]
    state_db = MagicMock()

    with (
        patch.object(gradio_app, "classify_query", return_value=classify_return),
        patch.object(gradio_app, "Retriever", return_value=mock_instance),
    ):
        gradio_app.generate_response(history, state_db, "")

    return mock_instance


class TestGenerateResponseDispatch:

    def test_dispatches_to_answer_structural(self, _stub_for_dispatch):
        instance = _call_generate_response(("structural", None))
        instance.answer_structural.assert_called_once()
        instance.generate_chapter_filtered.assert_not_called()
        instance.generate_with_message.assert_not_called()

    def test_dispatches_to_chapter_filtered_with_correct_number(self, _stub_for_dispatch):
        instance = _call_generate_response(("chapter_filtered", 3))
        instance.generate_chapter_filtered.assert_called_once()
        call_kwargs = instance.generate_chapter_filtered.call_args
        assert call_kwargs.args[2] == 3 or call_kwargs.kwargs.get("chapter_number") == 3
        instance.answer_structural.assert_not_called()
        instance.generate_with_message.assert_not_called()

    def test_dispatches_to_semantic(self, _stub_for_dispatch):
        instance = _call_generate_response(("semantic", None))
        instance.generate_with_message.assert_called_once()
        instance.answer_structural.assert_not_called()
        instance.generate_chapter_filtered.assert_not_called()

    def test_semantic_fallback_when_classify_returns_semantic(self, _stub_for_dispatch):
        # classify_query already falls back to ("semantic", None) on LLM errors;
        # here we confirm generate_response handles that result correctly.
        instance = _call_generate_response(("semantic", None))
        instance.generate_with_message.assert_called_once()
