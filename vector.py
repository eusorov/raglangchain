from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from chromadb.config import Settings
from dotenv import dotenv_values

config = dotenv_values(".env")
LOCAL_LLM_BASE = config.get("LOCAL_LLM_BASE", "http://localhost:11434")
LOCAL_LLM_MODEL = config.get("LOCAL_LLM_MODEL", "qwen3")
LOCAL_EMBEDDING_MODEL = config.get("LOCAL_EMBEDDING_MODEL", "qwen3-embedding")
CHROMA_PERSIST_DIR = "./chroma-data"
CHROMA_COLLECTION_NAME = "EU_AI_Act_huggingface"

def create_db(collection_name=CHROMA_COLLECTION_NAME, embedding="huggingface"):
    """
    Create a LangChain Chroma vectorstore (db) that uses the existing persisted collection.
    Use this when the collection already exists (e.g. after a previous embed_documents_* run).
    """
    if embedding == "huggingface":
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")
    else:
        embeddings = OllamaEmbeddings(base_url=LOCAL_LLM_BASE, model=LOCAL_EMBEDDING_MODEL)
    db = Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=embeddings,
        collection_name=collection_name,
    )
    return db

def chroma_collection_exists(persist_directory=CHROMA_PERSIST_DIR, collection_name=CHROMA_COLLECTION_NAME):
    """Return True if the Chroma collection already exists and has at least one document."""
    try:
        client = chromadb.PersistentClient(path=persist_directory)
        coll = client.get_collection(name=collection_name)
        return coll.count() > 0
    except Exception:
        return False

def load_documents(file_path):
    """Load documents from a file path."""
    loader = PyPDFLoader(file_path)
    documents = loader.load()
    return documents


def split_documents(documents):
    """Split documents into chunks."""
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    all_splits = text_splitter.split_documents(documents)
    return all_splits

def embed_documents_with_huggingface(all_splits):
    """Embed documents."""
    

    # clear the database
    chroma_client = chromadb.Client(
        Settings(
            is_persistent=True,
            persist_directory="./chroma-data"
        )
    )
    chroma_client.delete_collection(name="EU_AI_Act_huggingface")   
    chroma_client.close()

    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")
    db = Chroma.from_documents(
        all_splits,
        embeddings,
        persist_directory="./chroma-data",
        collection_name="EU_AI_Act_huggingface",
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
        persist_directory="./chroma-data",
        collection_name="EU_AI_Act_ollama",
    )
    return db

def print_source_documents(source_documents, max_chars=500):
    """Print which documents were used for the RAG answer."""
    if not source_documents:
        return
    print(f"\n--- Source documents ({len(source_documents)} chunks) ---")
    for i, doc in enumerate(source_documents, 1):
        content = doc.page_content.replace("\n", " ").strip()
        preview = content[:max_chars] + "..." if len(content) > max_chars else content
        meta = getattr(doc, "metadata", None) or {}
        print(f"\n[{i}] {preview}")
        if meta:
            print(f"    metadata: {meta}")