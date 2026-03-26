from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import faiss
import numpy as np

from app.db.sqlite_store import ChunkRow, SQLiteStore
from app.services.ollama_client import OllamaClient


def estimate_tokens(text: str) -> int:
    # Rough heuristic: 1 token ~= 4 chars in English-ish text.
    return max(1, int(len(text) / 4))


def chunk_text(text: str, target_chars: int = 1800, overlap_chars: int = 200) -> List[str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + target_chars)
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap_chars
        if start < 0:
            start = 0
        if end >= len(normalized):
            break
    return chunks


class RagIndex:
    def __init__(
        self,
        data_dir: str,
        sqlite_store: SQLiteStore,
        faiss_index_path: str,
        faiss_metadata_path: str,
        ollama: OllamaClient,
        rag_top_k: int,
    ):
        self._data_dir = data_dir
        self._sqlite = sqlite_store
        self._faiss_index_path = faiss_index_path
        self._faiss_metadata_path = faiss_metadata_path
        self._ollama = ollama
        self._rag_top_k = rag_top_k
        self._index: Optional[faiss.IndexIDMap2] = None
        self._dim: Optional[int] = None

    def _ensure_dirs(self) -> None:
        os.makedirs(self._data_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self._faiss_index_path), exist_ok=True)

    def _load_faiss(self) -> None:
        if os.path.exists(self._faiss_index_path):
            idx = faiss.read_index(self._faiss_index_path)
            # Ensure id-mapped index.
            if not isinstance(idx, faiss.IndexIDMap2):
                # Wrap if possible.
                # This is best-effort; if it fails, we re-create on next indexing.
                wrapped = faiss.IndexIDMap2(idx)
                idx = wrapped
            self._index = idx
            # Try infer dim.
            if idx.ntotal > 0:
                self._dim = idx.d
        else:
            self._index = None
            self._dim = None

    def _create_index(self, dim: int) -> None:
        base = faiss.IndexFlatIP(dim)
        self._index = faiss.IndexIDMap2(base)
        self._dim = dim

    @staticmethod
    def _normalize(vectors: np.ndarray) -> np.ndarray:
        # Normalize to unit length for cosine similarity if not already normalized.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-12
        return vectors / norms

    async def load(self) -> None:
        self._ensure_dirs()
        self._load_faiss()

    async def index_text_document(
        self,
        file_id: str,
        file_name: str,
        mime_type: str,
        text: str,
        per_page_text: Optional[List[Tuple[int, str]]] = None,
    ) -> None:
        await self.load()
        per_page_text = per_page_text or []

        # If we have per-page text (PDF), chunk per page so we can keep page_num metadata.
        chunk_rows: List[Tuple[int, str, int, Optional[int]]] = []
        if per_page_text:
            chunk_index = 0
            for page_num, page_text in per_page_text:
                for ch in chunk_text(page_text):
                    chunk_rows.append((chunk_index, ch, estimate_tokens(ch), page_num))
                    chunk_index += 1
        else:
            chunks = chunk_text(text)
            for i, ch in enumerate(chunks):
                chunk_rows.append((i, ch, estimate_tokens(ch), None))

        if not chunk_rows:
            return

        # Persist chunks first so we can use their DB ids as FAISS vector ids.
        inserted_ids = await self._sqlite.insert_chunks(
            file_id=file_id,
            chunks=chunk_rows,
        )

        # Embed chunks and add vectors into FAISS.
        # Batch size tuned to keep memory reasonable.
        batch_size = 8
        all_embeddings: List[List[float]] = []
        chunk_texts = [c[1] for c in chunk_rows]
        for i in range(0, len(chunk_texts), batch_size):
            batch = chunk_texts[i : i + batch_size]
            embeddings, _meta = await self._ollama.embed(batch)
            all_embeddings.extend(embeddings)

        vectors = np.array(all_embeddings, dtype=np.float32)
        vectors = self._normalize(vectors)

        if self._index is None or self._dim is None:
            self._create_index(vectors.shape[1])

        assert self._index is not None
        assert len(inserted_ids) == vectors.shape[0]
        ids = np.array(inserted_ids, dtype=np.int64)
        self._index.add_with_ids(vectors, ids)

        # Save to disk.
        faiss.write_index(self._index, self._faiss_index_path)
        with open(self._faiss_metadata_path, "w", encoding="utf-8") as f:
            json.dump({"dim": int(vectors.shape[1]), "ntotal": int(self._index.ntotal)}, f)

        # Store the full file text (optional but useful for later UI).
        await self._sqlite.upsert_file_text(
            file_id=file_id, file_name=file_name, mime_type=mime_type, text_content=text
        )

    async def search(self, query: str, top_k: Optional[int] = None) -> List[Tuple[int, float]]:
        await self.load()
        if self._index is None or self._dim is None or self._index.ntotal == 0:
            return []

        top_k_eff = top_k or self._rag_top_k
        embeddings, _meta = await self._ollama.embed([query])
        if not embeddings:
            return []
        vec = np.array([embeddings[0]], dtype=np.float32)
        vec = self._normalize(vec)
        scores, ids = self._index.search(vec, top_k_eff)
        results: List[Tuple[int, float]] = []
        for score, cid in zip(scores[0].tolist(), ids[0].tolist()):
            if cid == -1:
                continue
            results.append((int(cid), float(score)))
        return results

    async def get_chunks(self, chunk_ids: List[int]) -> List[ChunkRow]:
        return await self._sqlite.get_chunks_by_ids(chunk_ids)

    async def rebuild_index_from_active_files(self) -> None:
        """
        Rebuilds the FAISS index from all active files stored in SQLite.
        Used by DELETE /api/files/* to keep retrieval consistent.
        """
        self._ensure_dirs()
        if os.path.exists(self._faiss_index_path):
            os.remove(self._faiss_index_path)
        if os.path.exists(self._faiss_metadata_path):
            os.remove(self._faiss_metadata_path)

        self._index = None
        self._dim = None

        files = await self._sqlite.list_active_files_for_rebuild()
        for f in files:
            # textContent may be large; RagIndex will chunk/embed it.
            await self.index_text_document(
                file_id=f["id"],
                file_name=f["fileName"],
                mime_type=f["mimeType"],
                text=f["textContent"],
            )

