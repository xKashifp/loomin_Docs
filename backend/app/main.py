import os
import uuid
from typing import Any, Dict, List

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.settings import get_settings
from app.db.sqlite_store import SQLiteStore
from app.routers.files import router as files_router
from app.routers.assistant import router as assistant_router
from app.services.ollama_client import OllamaClient
from app.services.rag_index import RagIndex
from app.services.collab_server import LoominWebsocketServer, PathStrippingASGI
from ypy_websocket import ASGIServer


app = FastAPI(title="Loomin-Docs Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _request_id() -> str:
    return str(uuid.uuid4())


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/models")
async def models() -> List[Dict[str, Any]]:
    """
    Model profiles for the frontend dropdown.

    Tries to discover local models from Ollama (/api/tags). Falls back to
    env-based defaults for air-gapped setups.
    """

    embed_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    max_context_tokens = int(os.getenv("MAX_CONTEXT_TOKENS", "4096"))

    wanted_ids = os.getenv("OLLAMA_CHAT_MODEL_IDS", "").strip()
    if wanted_ids:
        wanted = [x.strip() for x in wanted_ids.split(",") if x.strip()]
    else:
        chat_model = os.getenv("OLLAMA_CHAT_MODEL", "loomin-llama3").strip()
        second = os.getenv("OLLAMA_SECOND_CHAT_MODEL", "loomin-mistral").strip()
        wanted = [chat_model] if chat_model else []
        if second and second not in wanted:
            wanted.append(second)

    # Best-effort discovery from Ollama.
    base_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
    discovered: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            for m in data.get("models") or []:
                name = m.get("name")
                if isinstance(name, str):
                    discovered.append(name)
    except Exception:
        discovered = []

    final_ids: List[str]
    if discovered:
        final_ids = [mid for mid in wanted if mid in discovered]
        # If none matched the discovered set, keep env wanted list.
        if not final_ids:
            final_ids = wanted
    else:
        final_ids = wanted

    def _display_name(mid: str) -> str:
        if "llama3" in mid:
            return f"Llama3 ({mid}) (Ollama)"
        if "mistral" in mid:
            return f"Mistral ({mid}) (Ollama)"
        return f"{mid} (Ollama)"

    return [
        {
            "id": mid,
            "displayName": _display_name(mid),
            "chatModel": mid,
            "embedModel": embed_model,
            "maxContextTokens": max_context_tokens,
        }
        for mid in final_ids
    ]

@app.get("/api/docs/{doc_id}")
async def get_doc(doc_id: str, request: Request) -> Dict[str, Any]:
    store: SQLiteStore = request.app.state.store
    markdown = await store.get_latest_doc_markdown(doc_id)
    return {"docId": doc_id, "markdown": markdown}


@app.on_event("startup")
async def startup() -> None:
    settings = get_settings()
    os.makedirs(settings.data_dir, exist_ok=True)

    store = SQLiteStore(settings.sqlite_path)
    await store.init()

    ollama = OllamaClient(
        base_url=settings.ollama_base_url,
        chat_model=settings.ollama_chat_model,
        embed_model=settings.ollama_embed_model,
    )

    rag = RagIndex(
        data_dir=settings.data_dir,
        sqlite_store=store,
        faiss_index_path=settings.faiss_index_path,
        faiss_metadata_path=settings.faiss_metadata_path,
        ollama=ollama,
        rag_top_k=settings.rag_top_k,
    )
    await rag.load()

    # Real-time collaboration server (Yjs) persisted in /data
    websocket_server = LoominWebsocketServer()
    await websocket_server.__aenter__()
    collab_asgi = PathStrippingASGI(ASGIServer(websocket_server), prefix="/ws/collab")

    app.state.settings = settings
    app.state.store = store
    app.state.ollama = ollama
    app.state.rag = rag
    app.state.websocket_server = websocket_server

    # Mount collaboration ASGI app under FastAPI.
    app.mount("/ws/collab", collab_asgi)


@app.on_event("shutdown")
async def shutdown() -> None:
    websocket_server = getattr(app.state, "websocket_server", None)
    if websocket_server is not None:
        await websocket_server.__aexit__(None, None, None)


app.include_router(files_router)
app.include_router(assistant_router)