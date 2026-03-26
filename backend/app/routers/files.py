import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, File, UploadFile, HTTPException, Request

from app.services.rag_index import RagIndex
from app.db.sqlite_store import SQLiteStore
from app.services.text_extractor import extract_text_with_pages


router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("")
async def list_files(request: Request) -> List[Dict[str, Any]]:
    store: SQLiteStore = request.app.state.store
    return await store.list_files()


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), request: Request = ...) -> Dict[str, Any]:
    store: SQLiteStore = request.app.state.store  # type: ignore[union-attr]
    rag: RagIndex = request.app.state.rag  # type: ignore[union-attr]
    file_id = f"file-{uuid.uuid4()}"
    mime_type = file.content_type or "application/octet-stream"

    text, per_page = await extract_text_with_pages(file)
    if not text.strip():
        raise HTTPException(status_code=400, detail="No extractable text found.")

    await rag.index_text_document(
        file_id=file_id,
        file_name=file.filename or file_id,
        mime_type=mime_type,
        text=text,
        per_page_text=per_page,
    )

    return {"id": file_id, "fileName": file.filename, "mimeType": mime_type}


@router.delete("/{file_id}")
async def delete_file(file_id: str, request: Request) -> Dict[str, Any]:
    store: SQLiteStore = request.app.state.store
    rag: RagIndex = request.app.state.rag

    await store.mark_file_deleted(file_id)
    await rag.rebuild_index_from_active_files()
    return {"ok": True}

