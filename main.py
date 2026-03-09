from llm import llm
from retriever import Retriever
from vector import (
    create_db,
    chroma_collection_exists,
    load_documents,
    split_documents,
    embed_documents_with_huggingface,
    print_source_documents,
)

if __name__ == "__main__":
    print("Starting the application...")

    if chroma_collection_exists():
        print("Using existing Chroma collection (skipping load/split/embed).")
        db = create_db()
        print(f"Loaded {db._collection.count()} chunks from disk.")
    else:
        print("No existing collection found. Loading, splitting, and embedding...")
        documents = load_documents("./EU_AI_Act.pdf")
        print(f"Loaded {len(documents)} documents")
        all_splits = split_documents(documents)
        print(f"Split into {len(all_splits)} chunks")
        db = embed_documents_with_huggingface(all_splits)
        print(f"Embedded {db._collection.count()} chunks")

    query = "In the context of EU AI Act, how is performed the testing of high-risk AI systems in real world conditions?"

    print("Sending RAG query (Retriever.generate)...")
    retriever = Retriever(db)
    result = retriever.generate(query, llm, k=4)
    answer, source_documents = result
    print(f"Question: {query}")
    print(f"Answer: {answer}")
    print_source_documents(source_documents)

    print("Sending RAG query (Retriever.generate_with_message)...")
    result = retriever.generate_with_message(query, llm, k=4, template=None)
    answer, source_documents = result
    print(f"Question: {query}")
    print(f"Answer: {answer}")
    print_source_documents(source_documents)