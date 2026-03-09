import os
from datetime import datetime, timezone

# OpenTelemetry: set up logging/tracing and instrument ChromaDB before first use
from logger import setup_otel_logging
setup_otel_logging()
from opentelemetry.instrumentation.chromadb import ChromaInstrumentor
ChromaInstrumentor().instrument()

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from dotenv import dotenv_values
import logging

config = dotenv_values(".env")
LOCAL_LLM_BASE = os.getenv(
    "LOCAL_LLM_BASE", config.get("LOCAL_LLM_BASE", "http://localhost:11434")
)
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", config.get("LOCAL_LLM_MODEL", "qwen3"))
LOCAL_EMBEDDING_MODEL = os.getenv(
    "LOCAL_EMBEDDING_MODEL", config.get("LOCAL_EMBEDDING_MODEL", "qwen3-embedding")
)
CHROMA_HOST = os.getenv("CHROMA_HOST", config.get("CHROMA_HOST", "chromadb"))
CHROMA_PORT = int(os.getenv("CHROMA_PORT", config.get("CHROMA_PORT", "8000")))
CHROMA_SSL = os.getenv("CHROMA_SSL", config.get("CHROMA_SSL", "false")).lower() == "true"
CHROMA_COLLECTION_NAME = "EU_AI_Act_huggingface"
GRADIO_COLLECTION_NAME = "gradio_current_pdf"


def get_chroma_http_client():
    """Create an HTTP client for the Chroma server container."""
    return chromadb.HttpClient(
        host=CHROMA_HOST,
        port=CHROMA_PORT,
        ssl=CHROMA_SSL,
    )

client = get_chroma_http_client()

def create_db(collection_name=CHROMA_COLLECTION_NAME, embedding="huggingface"):
    """
    Create a LangChain Chroma vectorstore (db) that connects to the Chroma HTTP server.
    Use this when the collection already exists (e.g. after a previous embed_documents_* run).
    """
    if embedding == "huggingface":
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")
    else:
        embeddings = OllamaEmbeddings(base_url=LOCAL_LLM_BASE, model=LOCAL_EMBEDDING_MODEL)
    db = Chroma(
        client=client,
        embedding_function=embeddings,
        collection_name=collection_name,
    )
    return db

def chroma_collection_exists(collection_name=CHROMA_COLLECTION_NAME):
    """Return True if the Chroma collection already exists and has at least one document."""
    try:
        coll = client.get_collection(name=collection_name)
        return coll.count() > 0
    except Exception:
        return False


def get_collection_sample_metadata(collection_name=CHROMA_COLLECTION_NAME):
    """Return metadata from one document in the collection (e.g. pdf_name, indexed_at), or None if empty/missing."""
    try:
        coll = client.get_collection(name=collection_name)
        if coll.count() == 0:
            return None
        result = coll.get(limit=1, include=["metadatas"])
        if result and result.get("metadatas") and len(result["metadatas"]) > 0:
            return result["metadatas"][0]
        return None
    except Exception:
        return None

def load_documents(file_path, extra_metadata=None):
    """Load documents from a file path. Optionally add PDF-level metadata (e.g. pdf_name, indexed_at) to every page."""
    loader = PyPDFLoader(file_path)
    documents = loader.load()
    # Add document-level metadata (inherited by all chunks after split)
    pdf_name = os.path.basename(file_path)
    indexed_at = datetime.now(timezone.utc).isoformat()
    try:
        file_modified = datetime.fromtimestamp(os.path.getmtime(file_path), tz=timezone.utc).isoformat()
    except OSError:
        file_modified = None
    base_meta = {
        "pdf_name": pdf_name,
        "indexed_at": indexed_at,
        **({"file_modified": file_modified} if file_modified else {}),
        **(extra_metadata or {}),
    }
    for doc in documents:
        doc.metadata.update(base_meta)
    return documents


def split_documents(documents):
    """Split documents into chunks."""
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    all_splits = text_splitter.split_documents(documents)
    return all_splits

def embed_documents_with_huggingface(all_splits, collection_name=CHROMA_COLLECTION_NAME):
    """Embed documents into the Chroma HTTP server. Optionally use a different collection."""
    if chroma_collection_exists(collection_name=collection_name):
        client.delete_collection(name=collection_name)

    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")
    db = Chroma.from_documents(
        all_splits,
        embeddings,
        host=CHROMA_HOST,
        port=CHROMA_PORT,
        ssl=CHROMA_SSL,
        collection_name=collection_name,
    )
    return db

def embed_documents_with_ollama(all_splits):
    """Embed documents using Ollama (e.g. qwen3 embedding model)."""
    embeddings = OllamaEmbeddings(
        base_url=LOCAL_LLM_BASE,
        model=LOCAL_EMBEDDING_MODEL,
    )
    db = Chroma.from_documents(
        all_splits,
        embeddings,
        host=CHROMA_HOST,
        port=CHROMA_PORT,
        ssl=CHROMA_SSL,
        collection_name="EU_AI_Act_ollama",
    )
    return db

def print_source_documents(source_documents, max_chars=500):
    """Print which documents were used for the RAG answer."""
    if not source_documents:
        return
    logging.info(f"\n--- Source documents ({len(source_documents)} chunks) ---")
    # for i, doc in enumerate(source_documents, 1):
    #     content = doc.page_content.replace("\n", " ").strip()
    #     preview = content[:max_chars] + "..." if len(content) > max_chars else content
    #     meta = getattr(doc, "metadata", None) or {}
    #     print(f"\n[{i}] {preview}")
    #     if meta:
    #         print(f"    metadata: {meta}")