import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.db.sqlite_store import ChunkRow, SQLiteStore
from app.services.ollama_client import OllamaClient
from app.services.pii_sanitizer import mask_pii
from app.services.rag_index import RagIndex, estimate_tokens


router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    docId: str
    modelId: Optional[str] = None
    messages: List[ChatMessage]
    documentMarkdown: Optional[str] = None


class CitationOut(BaseModel):
    id: str
    fileName: str
    snippet: str
    pageNumber: Optional[int] = None


def _json_from_text(text: str) -> Optional[Dict[str, Any]]:
    # Try to extract the first JSON object from the model output.
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _build_citations_context(
    chunks: List[ChunkRow],
    max_chars_per_chunk: int = 1400,
) -> Tuple[str, Dict[int, str]]:
    id_map: Dict[int, str] = {}
    parts: List[str] = []
    for i, c in enumerate(chunks, start=1):
        cid = f"C{i}"
        id_map[c.chunk_id] = cid
        snippet = c.chunk_text.strip()
        if len(snippet) > max_chars_per_chunk:
            snippet = snippet[:max_chars_per_chunk] + "..."
        parts.append(f"[{cid}] {snippet}")
    context = "\n\n".join(parts)
    return context, id_map


def _build_system_instruction() -> str:
    return (
        "You are a precise document assistant. "
        "Ground every factual claim in the provided citations. "
        "If the information is not present in the citations, say you don't know. "
        "When responding, output strict JSON with keys: "
        "'answer' (string) and 'used_citations' (array of citation ids like [\"C1\",\"C3\"])."
    )


def _generation_options() -> Dict[str, Any]:
    # Keep deterministic-ish for evaluation/faithfulness.
    return {"temperature": 0.2, "top_p": 0.9}


async def _assistant_core(
    request: Request,
    query: str,
    operation: str,
    selection: Optional[str] = None,
    document_markdown: Optional[str] = None,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    store: SQLiteStore = request.app.state.store
    rag: RagIndex = request.app.state.rag
    ollama: OllamaClient = request.app.state.ollama
    settings = request.app.state.settings

    request_id = str(uuid.uuid4())
    retrieval_start = time.time()
    retrieved = await rag.search(query, top_k=settings.rag_top_k)
    retrieval_time_ms = (time.time() - retrieval_start) * 1000.0

    chunk_ids = [cid for cid, _score in retrieved]
    chunks = await rag.get_chunks(chunk_ids)
    if not chunks:
        context = ""
        id_map: Dict[int, str] = {}
    else:
        context, id_map = _build_citations_context(chunks)

    retrieved_tokens_est = sum(int(c.tokens_est) for c in chunks) if chunks else 0
    doc_tokens_est = (
        estimate_tokens(document_markdown) if isinstance(document_markdown, str) else 0
    )
    context_usage_pct = (
        min(100, int(round(((doc_tokens_est + retrieved_tokens_est) / max(1, settings.max_context_tokens)) * 100)))
        if settings.max_context_tokens
        else 0
    )

    # Ask for grounded JSON output.
    if operation in ("summarize", "improve"):
        if not selection or document_markdown is None:
            raise HTTPException(
                status_code=400,
                detail="summarize/improve requires 'selection' and 'documentMarkdown'.",
            )

        if operation == "summarize":
            task = (
                "Summarize the selection into a concise Markdown rewrite that preserves meaning. "
                "Use only the provided citations."
            )
        else:
            task = (
                "Improve the selection for clarity and style while preserving meaning. "
                "Use only the provided citations."
            )

        user_prompt = (
            f"Task: {task}\n\n"
            f"Selection:\n{selection}\n\n"
            f"Document (for context):\n{document_markdown}\n\n"
            f"Retrieved citations context:\n{context}\n\n"
            "Return JSON with keys 'answer' (Markdown for the updated selection) "
            "and 'used_citations'."
        )
    else:
        user_prompt = (
            "Answer the user question using only the provided citations.\n\n"
            f"User question: {query}\n\n"
            f"Retrieved citations context:\n{context}\n\n"
            "Return JSON with keys 'answer' and 'used_citations'."
        )

    # PII mask for the prompt.
    masked_prompt, _ = mask_pii(user_prompt)
    system_instruction = _build_system_instruction()

    gen_start = time.time()
    raw_text, meta = await ollama.generate(
        prompt=masked_prompt,
        system_prompt=system_instruction,
        options=_generation_options(),
        model=model_id,
    )
    generation_wall_ms = (time.time() - gen_start) * 1000.0

    data = _json_from_text(raw_text)
    answer = ""
    used_citation_ids: List[str] = []
    if data:
        answer = str(data.get("answer", "")).strip()
        used_citation_ids = [str(x) for x in (data.get("used_citations") or [])]
    else:
        answer = raw_text.strip()

    citations_out: List[Dict[str, Any]] = []
    # Map citation ids like ["C1","C2"] back to chunk rows.
    if chunks and used_citation_ids:
        # Reverse id_map: chunk_id -> Cn; build reverse for lookup.
        chunk_id_by_citation: Dict[str, int] = {v: k for k, v in id_map.items()}
        used_chunk_ids: List[int] = [
            chunk_id_by_citation[cid] for cid in used_citation_ids if cid in chunk_id_by_citation
        ]
        used_rows = await rag.get_chunks(used_chunk_ids)
        file_id_list = list({r.file_id for r in used_rows})
        file_names = await store.get_file_names(file_id_list)
        for r in used_rows:
            cite_id = id_map.get(r.chunk_id)
            if not cite_id:
                continue
            snippet = r.chunk_text.strip()
            if len(snippet) > 520:
                snippet = snippet[:520] + "..."
            citations_out.append(
                {
                    "id": cite_id,
                    "fileName": file_names.get(r.file_id, r.file_id),
                    "snippet": snippet,
                    "pageNumber": r.page_num,
                }
            )

    # Trace: token generation speed.
    eval_count = meta.get("eval_count") or 0
    eval_duration_ms = meta.get("eval_duration") or 0
    token_speed = 0.0
    if isinstance(eval_count, (int, float)) and eval_duration_ms:
        try:
            token_speed = float(eval_count) / (float(eval_duration_ms) / 1000.0)
        except Exception:
            token_speed = 0.0

    return {
        "request_id": request_id,
        "retrieval_time_ms": retrieval_time_ms,
        "token_generation_speed_tokens_per_second": token_speed,
        "wall_generation_ms": generation_wall_ms,
        "answer": answer,
        "citations": citations_out,
        "used_citations": used_citation_ids,
        "doc_tokens_est": doc_tokens_est,
        "retrieved_tokens_est": retrieved_tokens_est,
        "context_usage_pct": context_usage_pct,
    }


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request) -> Dict[str, Any]:
    # Use last user message as the query.
    user_messages = [m for m in payload.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message provided.")

    query = user_messages[-1].content
    res = await _assistant_core(
        request,
        query=query,
        operation="chat",
        document_markdown=payload.documentMarkdown,
        model_id=payload.modelId,
    )

    # Persist chat history (best-effort).
    try:
        store: SQLiteStore = request.app.state.store
        model_id = payload.modelId or request.app.state.settings.ollama_chat_model
        chat_id = f"chat-{uuid.uuid4()}"
        await store.insert_chat_history(
            chat_id=chat_id,
            doc_id=payload.docId,
            request_id=res["request_id"],
            model_id=model_id,
            messages=[m.model_dump() for m in payload.messages],
            answer=res["answer"],
            citations=res["citations"],
            retrieval_time_ms=float(res["retrieval_time_ms"]),
            token_generation_speed_tokens_per_second=float(
                res["token_generation_speed_tokens_per_second"]
            ),
        )
    except Exception:
        pass

    return {
        "request_id": res["request_id"],
        "retrieval_time_ms": res["retrieval_time_ms"],
        "token_generation_speed_tokens_per_second": res["token_generation_speed_tokens_per_second"],
        "answer": res["answer"],
        "citations": res["citations"],
        "used_citations": res["used_citations"],
        "context_usage_pct": res.get("context_usage_pct"),
    }


@router.post("/summarize")
async def summarize(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    selection = payload.get("selection") or ""
    doc_id = payload.get("docId") or ""
    document_markdown = payload.get("documentMarkdown")
    if not doc_id:
        raise HTTPException(status_code=400, detail="docId is required.")

    res = await _assistant_core(
        request,
        query=selection,
        operation="summarize",
        selection=selection,
        document_markdown=document_markdown,
        model_id=payload.get("modelId"),
    )

    # Persist doc version if we have full markdown.
    if isinstance(document_markdown, str) and selection:
        updated = document_markdown.replace(selection, res["answer"], 1)
    else:
        updated = res["answer"]

    store: SQLiteStore = request.app.state.store
    await store.create_doc_version(
        doc_id, updated, version_id=f"v-{uuid.uuid4()}"
    )

    return {
        "request_id": res["request_id"],
        "retrieval_time_ms": res["retrieval_time_ms"],
        "token_generation_speed_tokens_per_second": res[
            "token_generation_speed_tokens_per_second"
        ],
        "context_usage_pct": res.get("context_usage_pct"),
        "replacementMarkdown": res["answer"],
        "citations": res["citations"],
        "used_citations": res["used_citations"],
        "updatedDocumentMarkdown": updated,
    }


@router.post("/improve")
async def improve(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    selection = payload.get("selection") or ""
    doc_id = payload.get("docId") or ""
    document_markdown = payload.get("documentMarkdown")
    if not doc_id:
        raise HTTPException(status_code=400, detail="docId is required.")

    res = await _assistant_core(
        request,
        query=selection,
        operation="improve",
        selection=selection,
        document_markdown=document_markdown,
        model_id=payload.get("modelId"),
    )

    if isinstance(document_markdown, str) and selection:
        updated = document_markdown.replace(selection, res["answer"], 1)
    else:
        updated = res["answer"]

    store: SQLiteStore = request.app.state.store
    await store.create_doc_version(
        doc_id, updated, version_id=f"v-{uuid.uuid4()}"
    )

    return {
        "request_id": res["request_id"],
        "retrieval_time_ms": res["retrieval_time_ms"],
        "token_generation_speed_tokens_per_second": res[
            "token_generation_speed_tokens_per_second"
        ],
        "context_usage_pct": res.get("context_usage_pct"),
        "replacementMarkdown": res["answer"],
        "citations": res["citations"],
        "used_citations": res["used_citations"],
        "updatedDocumentMarkdown": updated,
    }

