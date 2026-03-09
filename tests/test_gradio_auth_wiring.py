"""Smoke test: verify gradio_app wires auth=authenticate into demo.launch()."""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_gradio_app(monkeypatch):
    """Prevent import of heavy modules (vector, llm, retriever, logger) that need network."""
    for mod_name in ("vector", "llm", "retriever", "logger",
                     "opentelemetry", "opentelemetry.instrumentation",
                     "opentelemetry.instrumentation.chromadb",
                     "chromadb"):
        if mod_name not in sys.modules:
            monkeypatch.setitem(sys.modules, mod_name, ModuleType(mod_name))

    stub_vector = sys.modules["vector"]
    for attr in ("GRADIO_COLLECTION_NAME", "create_db",
                 "chroma_collection_exists", "get_collection_sample_metadata",
                 "load_documents", "split_documents",
                 "embed_documents_with_huggingface"):
        setattr(stub_vector, attr, MagicMock())

    stub_llm = sys.modules["llm"]
    stub_llm.llm = MagicMock()

    stub_retriever = sys.modules["retriever"]
    stub_retriever.Retriever = MagicMock()

    stub_logger = sys.modules["logger"]
    stub_logger.setup_otel_logging = MagicMock()

    # Ensure gradio_app is freshly imported each test
    monkeypatch.delitem(sys.modules, "gradio_app", raising=False)
    yield


def test_gradio_app_has_auth_wired():
    """Confirm demo.launch is called with auth=authenticate."""
    import gradio_app
    from auth import authenticate

    mock_launch = MagicMock()
    with (
        patch.object(gradio_app.gr.Blocks, "launch", mock_launch),
        patch.object(gradio_app.gr.Blocks, "queue"),
        patch.object(gradio_app.gr.Blocks, "load"),
    ):
        gradio_app.main()

    mock_launch.assert_called_once()
    call_kwargs = mock_launch.call_args.kwargs
    assert call_kwargs.get("auth") is authenticate
    assert "auth_message" in call_kwargs
