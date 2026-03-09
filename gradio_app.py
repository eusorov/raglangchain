"""
Gradio web UI for PDF Q&A: upload a PDF, chat about it using the existing RAG pipeline.
Run with: python -m gradio_app  or  python gradio_app.py
"""
from logger import setup_otel_logging
import logging
import os

import gradio as gr
from dotenv import dotenv_values

logger = logging.getLogger(__name__)
from auth import authenticate
from llm import llm
from retriever import Retriever
from vector import (
    GRADIO_COLLECTION_NAME,
    create_db,
    chroma_collection_exists,
    get_collection_sample_metadata,
    load_documents,
    split_documents,
    embed_documents_with_huggingface,
)

config = dotenv_values(".env")
GRADIO_SERVER_NAME = os.getenv(
    "GRADIO_SERVER_NAME", config.get("GRADIO_SERVER_NAME", "127.0.0.1")
)
GRADIO_SERVER_PORT = int(
    os.getenv("GRADIO_SERVER_PORT", config.get("GRADIO_SERVER_PORT", "7860"))
)


def process_pdf(file_obj, state_db, status_msg, state_pdf_name):
    """Load, split, embed the uploaded PDF into the Gradio collection. Yield status updates."""
    if file_obj is None:
        logger.debug("process_pdf called with no file")
        yield state_db, status_msg or "No file selected.", state_pdf_name
        return
    path = file_obj if isinstance(file_obj, str) else (getattr(file_obj, "name", None) or getattr(file_obj, "path", None))
    if not path or not str(path).lower().endswith(".pdf"):
        logger.warning("process_pdf: invalid or non-PDF file path=%s", path)
        yield state_db, "Please upload a PDF file.", state_pdf_name
        return
    logger.info("Processing PDF: path=%s", path)
    yield state_db, "Indexing…", state_pdf_name
    try:
        documents = load_documents(path)
        if not documents:
            logger.warning("No content loaded from PDF: path=%s", path)
            yield state_db, "No content could be loaded from the PDF.", state_pdf_name
            return
        logger.info("Loaded %d pages from PDF: path=%s", len(documents), path)
        all_splits = split_documents(documents)
        logger.info("Split into %d chunks, embedding into collection=%s", len(all_splits), GRADIO_COLLECTION_NAME)
        db = embed_documents_with_huggingface(all_splits, collection_name=GRADIO_COLLECTION_NAME)
        # Read PDF name from chunk metadata (set in vector.load_documents)
        pdf_name = (all_splits[0].metadata.get("pdf_name") if all_splits else None) or "PDF"
        logger.info("PDF indexed successfully: pdf_name=%s chunks=%d", pdf_name, len(all_splits))
        yield db, f"Ready. {len(all_splits)} chunks indexed. You can ask questions below.", pdf_name
    except Exception as e:
        logger.exception("Error processing PDF: path=%s", path)
        yield state_db, f"Error processing PDF: {e}", state_pdf_name


def add_user_message(message, history):
    """Add the user's message immediately so Gradio can show progress while the answer is generated."""
    if not message or not message.strip():
        return history, ""
    logger.info("User question: %s", message.strip()[:200] + ("..." if len(message.strip()) > 200 else ""))
    new_history = (history or []) + [{"role": "user", "content": message}]
    return new_history, ""


def _extract_message_text(content):
    """Normalize Gradio chat message content into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part).strip()
    return str(content)


def generate_response(history, state_db, last_sources):
    """Generate the assistant response for the latest user message."""
    if not history:
        return history, last_sources, last_sources

    message = _extract_message_text(history[-1]["content"])
    if state_db is None:
        logger.debug("Generate requested but no PDF loaded")
        new_history = history + [
            {"role": "assistant", "content": "Please upload a PDF first."},
        ]
        return new_history, last_sources, last_sources
    try:
        retriever = Retriever(state_db)
        answer, source_documents = retriever.generate_with_message(message, llm, k=10)
        source_text = _format_sources(source_documents) if source_documents else ""
        num_sources = len(source_documents) if source_documents else 0
        logger.info("RAG response generated: query_len=%d answer_len=%d sources=%d", len(message), len(answer), num_sources)
        new_history = history + [{"role": "assistant", "content": answer}]
        return new_history, source_text, source_text
    except Exception as e:
        logger.exception("RAG generate failed: query=%s", message[:100])
        new_history = history + [{"role": "assistant", "content": f"Error: {e}"}]
        return new_history, last_sources, last_sources


def _format_sources(source_documents, max_chars=400):
    """Format source chunks for display."""
    if not source_documents:
        return ""
    lines = []
    for i, doc in enumerate(source_documents[:5], 1):
        content = (doc.page_content or "").replace("\n", " ").strip()
        preview = content[:max_chars] + "..." if len(content) > max_chars else content
        lines.append(f"[{i}] {preview}")
    return "\n\n".join(lines)


def reset_pdf(state_db, chatbot, status, last_sources, state_pdf_name):
    """Clear current PDF, chat history, and status."""
    logger.info("User cleared PDF and chat")
    return None, [], "Upload a PDF to get started.", "", "", None


def load_initial_state():
    """Read current metadata from the Gradio collection on app start; restore db and PDF name if present."""
    if not chroma_collection_exists(collection_name=GRADIO_COLLECTION_NAME):
        logger.info("No existing Gradio collection; prompt user to upload PDF")
        return None, None, "Upload a PDF to get started."
    db = create_db(collection_name=GRADIO_COLLECTION_NAME)
    meta = get_collection_sample_metadata(collection_name=GRADIO_COLLECTION_NAME)
    pdf_name = (meta.get("pdf_name") if meta else None) or "PDF"
    logger.info("Restored state from existing collection: pdf_name=%s", pdf_name)
    return db, pdf_name, f"Loaded existing document: {pdf_name}"


def main():
    with gr.Blocks(title="PDF Q&A") as demo:
        gr.Markdown("# PDF Q&A")
        gr.Markdown("Upload a PDF, then ask questions about it.")

        state_db = gr.State(value=None)
        state_pdf_name = gr.State(value=None)

        with gr.Row(variant="compact"):
            status = gr.Textbox(
                label="Status",
                value="Upload a PDF to get started.",
                interactive=False,
                lines=1,
                max_lines=1,
                show_label=True,
                scale=2,
            )
            upload_btn = gr.UploadButton(
                "Upload file",
                file_types=[".pdf"],
                type="filepath",
                size="lg",
                scale=0,
                min_width=120,
            )
            reset_btn = gr.Button("Clear PDF & Chat", scale=0, size="lg")

        upload_btn.upload(
            fn=process_pdf,
            inputs=[upload_btn, state_db, status, state_pdf_name],
            outputs=[state_db, status, state_pdf_name],
        )

        last_sources = gr.State(value="")
        with gr.Tabs():
            with gr.Tab("Chat"):
                chatbot = gr.Chatbot(label="Chat", height=400)
               
            with gr.Tab("Sources"):
                sources_box = gr.Textbox(
                    label="Sources (last answer)",
                    value="",
                    lines=12,
                    max_lines=20,
                    interactive=False,
                )
                
        msg = gr.Textbox(label="Your question", placeholder="Ask a question about the PDF...")

        reset_btn.click(
            fn=reset_pdf,
            inputs=[state_db, chatbot, status, last_sources, state_pdf_name],
            outputs=[state_db, chatbot, status, last_sources, sources_box, state_pdf_name],
        )

        msg.submit(
            add_user_message,
            inputs=[msg, chatbot],
            outputs=[chatbot, msg],
            queue=False,
        ).then(
            generate_response,
            inputs=[chatbot, state_db, last_sources],
            outputs=[chatbot, last_sources, sources_box],
            show_progress="full",
        )

        demo.load(
            fn=load_initial_state,
            inputs=[],
            outputs=[state_db, state_pdf_name, status],
        )

    demo.queue()
    logger.info(
        "Starting Gradio server: host=%s port=%s",
        GRADIO_SERVER_NAME,
        GRADIO_SERVER_PORT,
    )
    demo.launch(
        share=False,
        server_name=GRADIO_SERVER_NAME,
        server_port=GRADIO_SERVER_PORT,
        auth=authenticate,
        auth_message="RAG Demo - PDF Q&A - please log in",
    )


if __name__ == "__main__":
    setup_otel_logging()
    main()
