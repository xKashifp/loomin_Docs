from __future__ import annotations

import io
import re
from typing import List, Tuple

from pypdf import PdfReader
from starlette.datastructures import UploadFile


def _guess_kind(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith(".md") or lower.endswith(".markdown"):
        return "md"
    if lower.endswith(".txt"):
        return "txt"
    return "text"


async def extract_text_with_pages(
    file: UploadFile, max_chars: int = 400_000
) -> Tuple[str, List[Tuple[int, str]]]:
    kind = _guess_kind(file.filename or "unknown")
    raw = await file.read()
    if not raw:
        return "", []

    if kind == "pdf":
        reader = PdfReader(io.BytesIO(raw))
        per_page: List[Tuple[int, str]] = []
        total = 0
        for idx, page in enumerate(reader.pages, start=1):
            txt = (page.extract_text() or "").strip()
            if not txt:
                continue
            per_page.append((idx, txt))
            total += len(txt)
            if total > max_chars:
                break
        combined = "\n\n".join([t for _, t in per_page]).strip()
        return combined[:max_chars], per_page

    # For md/txt: decode as UTF-8 (best effort).
    text = raw.decode("utf-8", errors="ignore")
    text = re.sub(r"\r\n?", "\n", text)
    return text[:max_chars], []

