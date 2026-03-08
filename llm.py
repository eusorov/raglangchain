"""
LLM factory: choose Ollama, Google Gemini, or OpenAI based on LLM_PROVIDER env var.
Used by gradio_app and main. Set in Docker via LLM_PROVIDER=ollama|gemini|openai.
"""
import os

from dotenv import dotenv_values

config = dotenv_values(".env")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", config.get("LLM_PROVIDER", "ollama")).lower().strip()

if LLM_PROVIDER == "gemini":
    from langchain_google_genai import ChatGoogleGenerativeAI

    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", config.get("GOOGLE_API_KEY", ""))
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", config.get("GEMINI_MODEL", "gemini-2.0-flash-lite"))
    llm = ChatGoogleGenerativeAI(
        google_api_key=GOOGLE_API_KEY or None,
        model=GEMINI_MODEL,
    )
elif LLM_PROVIDER == "openai":
    from langchain_openai import ChatOpenAI

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", config.get("OPENAI_API_KEY", ""))
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", config.get("OPENAI_MODEL", "gpt-4o-mini"))
    llm = ChatOpenAI(api_key=OPENAI_API_KEY or None, model=OPENAI_MODEL)
elif LLM_PROVIDER == "ollama":
    from langchain_ollama.chat_models import ChatOllama

    LOCAL_LLM_BASE = os.getenv(
        "LOCAL_LLM_BASE", config.get("LOCAL_LLM_BASE", "http://localhost:11434")
    )
    LOCAL_LLM_MODEL = os.getenv(
        "LOCAL_LLM_MODEL", config.get("LOCAL_LLM_MODEL", "qwen3")
    )
    llm = ChatOllama(base_url=LOCAL_LLM_BASE, model=LOCAL_LLM_MODEL)
else:
    raise ValueError(
        f"Unknown LLM_PROVIDER={LLM_PROVIDER!r}. Use LLM_PROVIDER=ollama, gemini, or openai."
    )
