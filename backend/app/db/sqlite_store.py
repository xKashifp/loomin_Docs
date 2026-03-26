import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import aiosqlite


@dataclass(frozen=True)
class ChunkRow:
    chunk_id: int
    file_id: str
    chunk_index: int
    chunk_text: str
    tokens_est: int
    page_num: Optional[int] = None


class SQLiteStore:
    def __init__(self, sqlite_path: str):
        self._path = sqlite_path

    async def init(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA synchronous=NORMAL;")

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                  id TEXT PRIMARY KEY,
                  file_name TEXT NOT NULL,
                  mime_type TEXT,
                  uploaded_at INTEGER NOT NULL,
                  deleted INTEGER NOT NULL DEFAULT 0,
                  text_content TEXT
                );
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                  chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  file_id TEXT NOT NULL,
                  chunk_index INTEGER NOT NULL,
                  chunk_text TEXT NOT NULL,
                  tokens_est INTEGER NOT NULL,
                  page_num INTEGER,
                  FOREIGN KEY(file_id) REFERENCES files(id)
                );
                """
            )

            # Lightweight migrations for existing DBs.
            cur = await db.execute("PRAGMA table_info(chunks);")
            cols = [r[1] for r in await cur.fetchall()]
            if "page_num" not in cols:
                await db.execute("ALTER TABLE chunks ADD COLUMN page_num INTEGER;")

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS doc_versions (
                  doc_id TEXT NOT NULL,
                  version_id TEXT PRIMARY KEY,
                  created_at INTEGER NOT NULL,
                  markdown TEXT NOT NULL
                );
                """
            )

            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_file_id ON chunks(file_id);
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_history (
                  chat_id TEXT PRIMARY KEY,
                  doc_id TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  request_id TEXT NOT NULL,
                  model_id TEXT NOT NULL,
                  messages_json TEXT NOT NULL,
                  answer TEXT NOT NULL,
                  citations_json TEXT NOT NULL,
                  retrieval_time_ms REAL NOT NULL,
                  token_generation_speed_tokens_per_second REAL NOT NULL
                );
                """
            )

            await db.commit()

    async def get_latest_doc_markdown(self, doc_id: str) -> str:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                """
                SELECT markdown
                FROM doc_versions
                WHERE doc_id = ?
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (doc_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else ""

    async def create_doc_version(self, doc_id: str, markdown: str, version_id: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO doc_versions (doc_id, version_id, created_at, markdown)
                VALUES (?, ?, ?, ?);
                """,
                (doc_id, version_id, int(time.time() * 1000), markdown),
            )
            await db.commit()

    async def upsert_file_text(
        self, file_id: str, file_name: str, mime_type: str, text_content: str
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO files (id, file_name, mime_type, uploaded_at, deleted, text_content)
                VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT(id) DO UPDATE SET
                  file_name=excluded.file_name,
                  mime_type=excluded.mime_type,
                  deleted=0,
                  text_content=excluded.text_content;
                """,
                (file_id, file_name, mime_type, int(time.time() * 1000), text_content),
            )
            await db.commit()

    async def insert_chunks(
        self, file_id: str, chunks: Iterable[Tuple[int, str, int, Optional[int]]]
    ) -> List[int]:
        # chunks: (chunk_index, chunk_text, tokens_est, page_num)
        inserted_ids: List[int] = []
        async with aiosqlite.connect(self._path) as db:
            for chunk_index, chunk_text, tokens_est, page_num in chunks:
                cur = await db.execute(
                    """
                    INSERT INTO chunks (file_id, chunk_index, chunk_text, tokens_est, page_num)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (file_id, chunk_index, chunk_text, tokens_est, page_num),
                )
                inserted_ids.append(int(cur.lastrowid))
            await db.commit()
        return inserted_ids

    async def get_chunks_by_ids(self, chunk_ids: List[int]) -> List[ChunkRow]:
        if not chunk_ids:
            return []
        placeholders = ",".join(["?"] * len(chunk_ids))
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                f"""
                SELECT chunk_id, file_id, chunk_index, chunk_text, tokens_est, page_num
                FROM chunks
                WHERE chunk_id IN ({placeholders});
                """,
                chunk_ids,
            )
            rows = await cur.fetchall()
            # Preserve order of input.
            by_id = {
                int(r[0]): ChunkRow(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows
            }
            return [by_id[cid] for cid in chunk_ids if cid in by_id]

    async def list_files(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                """
                SELECT id, file_name, mime_type, uploaded_at
                FROM files
                WHERE deleted = 0
                ORDER BY uploaded_at DESC;
                """
            )
            rows = await cur.fetchall()
            return [
                {
                    "id": r[0],
                    "fileName": r[1],
                    "mimeType": r[2],
                    "uploadedAt": r[3],
                }
                for r in rows
            ]

    async def mark_file_deleted(self, file_id: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                UPDATE files
                SET deleted = 1
                WHERE id = ?;
                """,
                (file_id,),
            )
            await db.execute("DELETE FROM chunks WHERE file_id = ?;", (file_id,))
            await db.commit()

    async def list_active_files_for_rebuild(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                """
                SELECT id, file_name, mime_type, text_content
                FROM files
                WHERE deleted = 0;
                """
            )
            rows = await cur.fetchall()
            return [
                {
                    "id": str(r[0]),
                    "fileName": str(r[1]),
                    "mimeType": str(r[2]),
                    "textContent": r[3] or "",
                }
                for r in rows
            ]

    async def get_file_names(self, file_ids: List[str]) -> Dict[str, str]:
        if not file_ids:
            return {}
        placeholders = ",".join(["?"] * len(file_ids))
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                f"""
                SELECT id, file_name
                FROM files
                WHERE id IN ({placeholders});
                """,
                file_ids,
            )
            rows = await cur.fetchall()
        return {str(r[0]): str(r[1]) for r in rows}

    async def insert_chat_history(
        self,
        chat_id: str,
        doc_id: str,
        request_id: str,
        model_id: str,
        messages: List[Dict[str, Any]],
        answer: str,
        citations: List[Dict[str, Any]],
        retrieval_time_ms: float,
        token_generation_speed_tokens_per_second: float,
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO chat_history (
                  chat_id, doc_id, created_at, request_id, model_id,
                  messages_json, answer, citations_json,
                  retrieval_time_ms, token_generation_speed_tokens_per_second
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    chat_id,
                    doc_id,
                    int(time.time() * 1000),
                    request_id,
                    model_id,
                    json.dumps(messages, ensure_ascii=False),
                    answer,
                    json.dumps(citations, ensure_ascii=False),
                    float(retrieval_time_ms),
                    float(token_generation_speed_tokens_per_second),
                ),
            )
            await db.commit()

