import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str
    ollama_chat_model: str
    ollama_embed_model: str
    sqlite_path: str
    data_dir: str
    faiss_index_path: str
    faiss_metadata_path: str
    max_context_tokens: int
    rag_top_k: int

    # PII masking toggles/regex tuning knobs can be configured later.
    pii_trust_regexes: bool


def get_settings() -> Settings:
    data_dir = os.getenv("DATA_DIR", "/data")
    return Settings(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        ollama_chat_model=os.getenv("OLLAMA_CHAT_MODEL", "llama3"),
        ollama_embed_model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
        sqlite_path=os.getenv("SQLITE_PATH", f"{data_dir}/loomin.sqlite"),
        data_dir=data_dir,
        faiss_index_path=os.getenv("FAISS_INDEX_PATH", f"{data_dir}/faiss.index"),
        faiss_metadata_path=os.getenv(
            "FAISS_METADATA_PATH", f"{data_dir}/faiss_metadata.json"
        ),
        max_context_tokens=int(os.getenv("MAX_CONTEXT_TOKENS", "4096")),
        rag_top_k=int(os.getenv("RAG_TOP_K", "6")),
        pii_trust_regexes=os.getenv("PIIS_TRUSTED_REGEXES", "false").lower()
        in ("1", "true", "yes"),
    )

