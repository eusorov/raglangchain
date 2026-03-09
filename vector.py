import os
import re
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

def _estimate_body_font_size(file_path: str) -> float:
    """Return the most-common (mode) rounded font size across all pages — the body-text baseline."""
    from collections import Counter
    import pdfplumber
    sizes = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            for char in page.chars:
                sz = char.get("size")
                if sz:
                    sizes.append(round(float(sz), 1))
    return Counter(sizes).most_common(1)[0][0] if sizes else 10.0


def _extract_headers_with_pdfplumber(file_path: str, body_size: float) -> list[dict]:
    """
    For each page return the first large-font, short line in the top half of the page.
    Returns a list of {page_1based, text}.
    """
    import pdfplumber
    threshold = body_size * 1.2
    headers = []
    with pdfplumber.open(file_path) as pdf:
        for page_0based, page in enumerate(pdf.pages):
            page_1based = page_0based + 1
            page_height = page.height or 1
            words = page.extract_words(extra_attrs=["size"])
            if not words:
                continue
            # Keep only large-font words in the top half of the page
            large_words = [
                w for w in words
                if w.get("size", 0) >= threshold and w.get("top", page_height) <= page_height * 0.5
            ]
            if not large_words:
                continue
            # Group consecutive words into lines by rounding their top-coordinate
            lines: dict[int, list[str]] = {}
            for w in large_words:
                key = round(w["top"])
                lines.setdefault(key, []).append(w["text"])
            # Reconstruct line strings, pick the first one that is short enough
            for _top, words_in_line in sorted(lines.items()):
                line_text = " ".join(words_in_line).strip()
                if 3 <= len(line_text) <= 80:
                    headers.append({"page_1based": page_1based, "text": line_text})
                    break  # one header per page
    return headers


def _roman_to_int(s: str) -> int:
    """Convert a Roman numeral string (I–XIII range) to int. Raises ValueError for unrecognised input."""
    roman_values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    s = s.upper().strip()
    if not s or not all(c in roman_values for c in s):
        raise ValueError(f"Not a Roman numeral: {s!r}")
    total = 0
    prev = 0
    for ch in reversed(s):
        val = roman_values[ch]
        if val < prev:
            total -= val
        else:
            total += val
        prev = val
    return total


_numbered_heading_re = re.compile(
    r'^([IVXLCDM]+|\d+)\.?\s+(.*)',
    re.IGNORECASE,
)
_chapter_re = re.compile(
    r'^chapter\s+([IVXLCDM]+|\d+)[^\S\r\n]*[–\-:]?[^\S\r\n]*(.*)',
    re.IGNORECASE | re.MULTILINE,
)


def _assign_chapter_number(text: str, counter: int) -> tuple[int, str]:
    """
    Parse a leading digit or Roman numeral from *text*.
    Returns (chapter_number, chapter_title).
    Falls back to auto-incrementing *counter* when no number is found.
    """
    m = _numbered_heading_re.match(text.strip())
    if m:
        raw_num = m.group(1).strip()
        title = m.group(2).strip() or text.strip()
        try:
            return _roman_to_int(raw_num), title
        except ValueError:
            return int(raw_num), title
    return counter, text.strip()


def extract_chapter_structure(documents, file_path: str | None = None):
    """
    Scan page-level Documents for chapter headings.
    Returns a list of dicts: {number, title, page_start, page_end}.
    page_start and page_end are 1-based page numbers.

    When *file_path* is given, pdfplumber font-size analysis is used to detect
    the largest text on each page as the chapter header (regardless of wording).
    When *file_path* is None the legacy regex path ("Chapter X …") is used.
    """
    if file_path is not None:
        chapters = _extract_chapters_pdfplumber(documents, file_path)
    else:
        chapters = _extract_chapters_regex(documents)

    for i, ch in enumerate(chapters):
        if i + 1 < len(chapters):
            ch["page_end"] = chapters[i + 1]["page_start"] - 1
        else:
            ch["page_end"] = documents[-1].metadata.get("page", 0) + 1

    return chapters


def _extract_chapters_regex(documents):
    """Legacy path: detect headings that literally start with 'Chapter N'."""
    chapters = []
    for doc in documents:
        page_1based = doc.metadata.get("page", 0) + 1
        match = _chapter_re.search(doc.page_content[:400])
        if match:
            raw_num = match.group(1).strip()
            raw_title = match.group(2).strip()
            try:
                number = _roman_to_int(raw_num)
            except ValueError:
                number = int(raw_num)
            chapters.append({
                "number": number,
                "title": raw_title if raw_title else f"Chapter {number}",
                "page_start": page_1based,
                "page_end": -1,
            })
    return chapters


def _extract_chapters_pdfplumber(documents, file_path: str):
    """
    Use pdfplumber font-size analysis to detect chapter-level headers.
    Each page's largest-font short line (top half of page) is treated as the header.
    Chapter numbers are parsed from a leading digit/Roman numeral, or auto-incremented.
    """
    body_size = _estimate_body_font_size(file_path)
    raw_headers = _extract_headers_with_pdfplumber(file_path, body_size)

    # Build a fast lookup: page_1based → header text
    header_by_page = {h["page_1based"]: h["text"] for h in raw_headers}

    chapters = []
    auto_counter = 0
    for doc in documents:
        page_1based = doc.metadata.get("page", 0) + 1
        header_text = header_by_page.get(page_1based)
        if header_text is None:
            continue
        auto_counter += 1
        number, title = _assign_chapter_number(header_text, auto_counter)
        # Avoid duplicates: skip if same number was already recorded
        if chapters and chapters[-1]["number"] == number:
            continue
        chapters.append({
            "number": number,
            "title": title,
            "page_start": page_1based,
            "page_end": -1,
        })
    return chapters


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
    chapters = extract_chapter_structure(documents, file_path=file_path)

    def _chapter_for_page(page_1based):
        """Return the chapter dict whose range contains page_1based, or None."""
        for ch in reversed(chapters):
            if ch["page_start"] <= page_1based:
                return ch
        return None

    for doc in documents:
        doc.metadata.update(base_meta)
        page_1based = doc.metadata.get("page", 0) + 1
        ch = _chapter_for_page(page_1based)
        doc.metadata.update({
            "chapter_number":     ch["number"]     if ch is not None else -1,
            "chapter_title":      ch["title"]      if ch is not None else "",
            "chapter_page_start": ch["page_start"] if ch is not None else -1,
            "chapter_page_end":   ch["page_end"]   if ch is not None else -1,
        })
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