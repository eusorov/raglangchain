from typing import Literal, Optional

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


# ---------------------------------------------------------------------------
# LLM-based query classifier
# ---------------------------------------------------------------------------

class QueryClassification(BaseModel):
    query_type: Literal["structural", "chapter_filtered", "semantic"] = Field(
        description=(
            "structural — question about document structure (chapter count, chapter list, table of contents).\n"
            "chapter_filtered — question about the content of a specific chapter.\n"
            "semantic — all other content questions."
        )
    )
    chapter_number: Optional[int] = Field(
        default=None,
        description="The chapter number (integer) when query_type is 'chapter_filtered', otherwise null.",
    )


_CLASSIFICATION_PROMPT = (
    "You are a query router for a PDF document Q&A system.\n"
    "Classify the user question into exactly one category:\n"
    "- 'structural': asks about document structure — chapter count, chapter titles, "
    "table of contents, list of chapters.\n"
    "- 'chapter_filtered': asks about the content of a specific chapter — identify the chapter number.\n"
    "- 'semantic': any other content question.\n\n"
    "For 'chapter_filtered', extract the chapter number as an integer "
    "(convert ordinals like 'second' → 2 and Roman numerals like 'II' → 2).\n\n"
    "User question: {query}"
)


def classify_query(query: str, llm) -> tuple[str, int | None]:
    """
    Use the LLM to classify query into one of:
      ('structural', None)
      ('chapter_filtered', chapter_number)
      ('semantic', None)
    Falls back to ('semantic', None) on any error so the app never crashes.
    """
    try:
        structured_llm = llm.with_structured_output(QueryClassification)
        prompt = ChatPromptTemplate.from_messages([
            ("human", _CLASSIFICATION_PROMPT),
        ])
        chain = prompt | structured_llm
        result: QueryClassification = chain.invoke({"query": query})
        return result.query_type, result.chapter_number
    except Exception:
        return "semantic", None


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------

class Retriever:
    def __init__(self, db):
        self.db = db

    def retrieve(self, query, k=4):
        retriever = self.db.as_retriever(search_type="similarity", search_kwargs={"k": k})
        return retriever

    def generate(self, query, llm, k=4):
        retriever = self.retrieve(query, k)
        source_documents = retriever.invoke(query)
        template = """
        Answer questions based on the following context:
        {context}

        Question: {input}
        """
        prompt = ChatPromptTemplate.from_template(template)
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": source_documents, "input": query})
        return response, source_documents

    def generate_with_message(self, query, llm, k=4):
        retriever = self.retrieve(query, k)
        source_documents = retriever.invoke(query)
        prompt = ChatPromptTemplate.from_messages([
            ("system", "{context}"),
            ("human", "{input}"),
        ])
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": source_documents, "input": query})
        return response, source_documents

    def get_chapter_structure(self):
        """Return sorted list of chapter dicts from ChromaDB metadata, deduplicating by chapter_number."""
        result = self.db._collection.get(
            where={"chapter_number": {"$gt": 0}},
            include=["metadatas"],
        )
        seen = {}
        for meta in result.get("metadatas") or []:
            cn = meta.get("chapter_number")
            if cn and cn not in seen:
                seen[cn] = {
                    "number":     cn,
                    "title":      meta.get("chapter_title", ""),
                    "page_start": meta.get("chapter_page_start", -1),
                    "page_end":   meta.get("chapter_page_end", -1),
                }
        return sorted(seen.values(), key=lambda c: c["number"])

    def answer_structural(self, query, llm):
        """Answer structure-only questions using chapter metadata directly (no vector search)."""
        chapters = self.get_chapter_structure()
        if not chapters:
            return "No chapter structure was detected in this document.", []
        lines = [
            f"Chapter {c['number']}: {c['title']} (pages {c['page_start']}–{c['page_end']})"
            for c in chapters
        ]
        structure_text = f"This document has {len(chapters)} chapter(s):\n" + "\n".join(lines)
        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "You are a helpful assistant. Use the document structure below to answer the question.\n\n{context}",
            ),
            ("human", "{input}"),
        ])
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": structure_text, "input": query})
        return response, []

    def generate_chapter_filtered(self, query, llm, chapter_number: int, k: int = 10):
        """Semantic search restricted to chunks from a single chapter."""
        retriever = self.db.as_retriever(
            search_type="similarity",
            search_kwargs={"k": k, "filter": {"chapter_number": chapter_number}},
        )
        source_documents = retriever.invoke(query)
        if not source_documents:
            return f"No content found for chapter {chapter_number}.", []
        prompt = ChatPromptTemplate.from_messages([
            ("system", "{context}"),
            ("human", "{input}"),
        ])
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": source_documents, "input": query})
        return response, source_documents
