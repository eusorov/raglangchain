# Test Plan: Structural Query Routing

This document describes the test plan for the structural query routing feature added in requirement `6_structural_query_routing.md`. The implementer should follow this plan to create automated tests.

## Files under test

| File | Type | What to test |
|---|---|---|
| `retriever.py` | Unit tests | `classify_query`, `Retriever.get_chapter_structure`, `Retriever.answer_structural`, `Retriever.generate_chapter_filtered` |

## Test file: `tests/test_structural_query_routing.py`

All tests run without network access — no ChromaDB server, no LLM service, no real PDF. The LLM and the ChromaDB collection are replaced with `MagicMock` objects.

### Mocking strategy

**LLM mock for `classify_query`:** `classify_query` calls `llm.with_structured_output(QueryClassification)`. To control what the classifier returns, configure the mock chain:

```python
from unittest.mock import MagicMock
from retriever import QueryClassification

def make_llm_returning(query_type, chapter_number=None):
    """Return a mock LLM whose with_structured_output chain yields QueryClassification."""
    result = QueryClassification(query_type=query_type, chapter_number=chapter_number)
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = result
    mock_llm = MagicMock()
    mock_llm.__or__ = MagicMock(return_value=mock_chain)   # prompt | structured_llm
    mock_llm.with_structured_output.return_value = mock_llm
    return mock_llm, mock_chain
```

**LLM mock for `answer_structural` / `generate_chapter_filtered`:** These methods build a plain LangChain chain (`prompt | llm | StrOutputParser()`). To control the answer:

```python
def make_answering_llm(answer_text: str):
    """Return a mock LLM whose chain invoke returns answer_text."""
    mock_llm = MagicMock()
    mock_llm.__or__ = MagicMock(return_value=mock_llm)  # prompt | llm
    mock_llm.invoke.return_value = answer_text
    return mock_llm
```

**ChromaDB collection mock for `get_chapter_structure`:** Patch `self.db._collection.get` to return controlled metadata:

```python
def make_db_with_chapters(chapters: list[dict]):
    """Return a mock db whose _collection.get returns chapter metadata rows."""
    rows = []
    for ch in chapters:
        rows.append({
            "chapter_number":     ch["number"],
            "chapter_title":      ch["title"],
            "chapter_page_start": ch["page_start"],
            "chapter_page_end":   ch["page_end"],
        })
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"metadatas": rows}
    mock_db = MagicMock()
    mock_db._collection = mock_collection
    return mock_db
```

**ChromaDB retriever mock for `generate_chapter_filtered`:** `self.db.as_retriever(...).invoke(query)` returns a list of `Document` objects. Mock this as:

```python
from langchain_core.documents import Document

mock_db.as_retriever.return_value.invoke.return_value = [
    Document(page_content="Some chapter content.", metadata={"chapter_number": 2})
]
```

---

### Test class: `TestClassifyQuery`

Tests for `classify_query(query, llm)`. Import: `from retriever import classify_query, QueryClassification`.

#### Happy-path tests

| # | Test name | Mock LLM returns | Input query | Expected output |
|---|---|---|---|---|
| 1 | `test_structural_query` | `("structural", None)` | `"How many chapters are there?"` | `("structural", None)` |
| 2 | `test_chapter_filtered_query` | `("chapter_filtered", 2)` | `"What is chapter 2 about?"` | `("chapter_filtered", 2)` |
| 3 | `test_semantic_query` | `("semantic", None)` | `"What does the Act say about AI?"` | `("semantic", None)` |
| 4 | `test_chapter_filtered_with_chapter_number_returned` | `("chapter_filtered", 5)` | `"Show me chapter 5"` | `("chapter_filtered", 5)` |
| 5 | `test_chapter_number_is_integer` | `("chapter_filtered", 3)` | any chapter query | second element is `int`, not `str` or `None` |

#### Fallback / error tests

| # | Test name | Mock LLM behaviour | Expected output |
|---|---|---|---|
| 6 | `test_llm_exception_falls_back_to_semantic` | `with_structured_output` raises `RuntimeError` | `("semantic", None)` |
| 7 | `test_llm_invoke_exception_falls_back_to_semantic` | `chain.invoke` raises `ValueError` | `("semantic", None)` |
| 8 | `test_llm_returns_none_falls_back_to_semantic` | `chain.invoke` returns `None` | `("semantic", None)` |

---

### Test class: `TestGetChapterStructure`

Tests for `Retriever.get_chapter_structure()`. Import: `from retriever import Retriever`.

| # | Test name | Mock collection returns | Expected |
|---|---|---|---|
| 9 | `test_returns_sorted_chapters` | 3 rows with chapter_number 3, 1, 2 (unsorted) | List sorted by number: `[{number:1}, {number:2}, {number:3}]` |
| 10 | `test_deduplicates_by_chapter_number` | 5 rows — chapter 1 repeated 3 times, chapter 2 once | Returns 2 distinct chapters |
| 11 | `test_empty_collection_returns_empty_list` | `{"metadatas": []}` | `[]` |
| 12 | `test_excludes_pre_chapter_sentinel` | Rows with `chapter_number` of -1 are NOT returned by the `$gt 0` filter (verify the `where` clause is correct by checking what the collection mock was called with) | `mock_collection.get` called with `where={"chapter_number": {"$gt": 0}}` |
| 13 | `test_correct_fields_in_returned_dicts` | One row with all four fields | Each dict has keys `number`, `title`, `page_start`, `page_end` with correct values |

---

### Test class: `TestAnswerStructural`

Tests for `Retriever.answer_structural(query, llm)`.

| # | Test name | Setup | Expected |
|---|---|---|---|
| 14 | `test_returns_llm_answer_and_empty_sources` | db with 2 chapters; answering LLM mock returns `"Two chapters."` | `answer == "Two chapters."`, `source_docs == []` |
| 15 | `test_no_chapters_returns_no_structure_message` | db with no chapters (empty metadata) | answer contains `"No chapter structure"`, `source_docs == []` |
| 16 | `test_structure_text_includes_all_chapters` | Capture what the LLM chain receives as context; db has chapters 1 and 2 | `context` string contains both chapter titles and page ranges |
| 17 | `test_chapter_count_in_structure_text` | db with 3 chapters | `context` string includes `"3 chapter"` |
| 18 | `test_source_docs_always_empty` | Any valid db with chapters | `source_docs` is always `[]` (structural answers never return chunks) |

For tests 16–17, capture the context by inspecting what `mock_llm.invoke` was called with, or by patching `ChatPromptTemplate` to record its input.

---

### Test class: `TestGenerateChapterFiltered`

Tests for `Retriever.generate_chapter_filtered(query, llm, chapter_number, k=10)`.

| # | Test name | Setup | Expected |
|---|---|---|---|
| 19 | `test_returns_answer_and_source_docs` | `db.as_retriever().invoke()` returns 2 documents; LLM returns `"Chapter 2 is about..."` | `answer == "Chapter 2 is about..."`, `len(source_docs) == 2` |
| 20 | `test_no_chunks_returns_no_content_message` | `db.as_retriever().invoke()` returns `[]` | answer contains `"No content found for chapter"`, `source_docs == []` |
| 21 | `test_filter_passed_to_as_retriever` | Call `generate_chapter_filtered(query, llm, chapter_number=3)` | `db.as_retriever` called with `search_kwargs` containing `"filter": {"chapter_number": 3}` |
| 22 | `test_default_k_is_10` | Call without explicit k | `db.as_retriever` called with `search_kwargs` containing `"k": 10` |
| 23 | `test_custom_k_is_passed_through` | Call with `k=5` | `db.as_retriever` called with `search_kwargs` containing `"k": 5` |
| 24 | `test_no_content_message_includes_chapter_number` | Call with `chapter_number=7`; `invoke` returns `[]` | answer contains `"7"` |

---

### Integration smoke test: `TestGenerateResponseDispatch`

These tests verify that `generate_response()` in `gradio_app.py` correctly dispatches based on the result of `classify_query`. Use the same heavy-module stubbing pattern from `test_gradio_auth_wiring.py`.

| # | Test name | `classify_query` returns | Expected Retriever method called |
|---|---|---|---|
| 25 | `test_dispatches_to_answer_structural` | `("structural", None)` | `retriever_instance.answer_structural` called once |
| 26 | `test_dispatches_to_chapter_filtered` | `("chapter_filtered", 3)` | `retriever_instance.generate_chapter_filtered` called with `chapter_number=3` |
| 27 | `test_dispatches_to_semantic` | `("semantic", None)` | `retriever_instance.generate_with_message` called once |
| 28 | `test_fallback_classify_error_uses_semantic` | `classify_query` raises `Exception` — but per implementation it already returns `("semantic", None)` on error, so mock it returning `("semantic", None)` | `generate_with_message` called |

For tests 25–28, patch `classify_query` at the `gradio_app` module level (`patch("gradio_app.classify_query", return_value=("structural", None))`), patch `gradio_app.Retriever` to return a controlled mock instance, and call `gradio_app.generate_response(history, mock_db, "")` directly.

---

## Running the tests

```bash
pytest tests/test_structural_query_routing.py -v
```

All 28 tests should pass without network, ChromaDB, or LLM access.

## Implementation notes for the implementer

- Import `classify_query` and `QueryClassification` from `retriever` at the top of the test file.
- For the `classify_query` mock chain, `with_structured_output` returns a mock that participates in LangChain's `|` (pipe) operator. The simplest approach: make `mock_llm.__or__` return a pre-configured mock chain whose `.invoke()` returns the desired `QueryClassification` instance.
- For `answer_structural` and `generate_chapter_filtered`, the chain is `prompt | llm | StrOutputParser()`. The easiest way to intercept the final answer is to patch `StrOutputParser` or configure `mock_llm.invoke.return_value` — since `StrOutputParser` passes through whatever the LLM returns when it's a plain string.
- For tests 25–28 (`generate_response` dispatch), use the same `sys.modules` stub pattern from `test_gradio_auth_wiring.py` to prevent heavy imports. Add `gradio_app` to the delete-after-test list so each test gets a fresh import.
- Do not test the actual LLM classification quality (that is an integration concern) — only test that `classify_query` correctly invokes the LLM chain and returns/falls back as expected.
