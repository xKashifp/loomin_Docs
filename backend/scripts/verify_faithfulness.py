#!/usr/bin/env python3
"""
RAG Faithfulness Verification (offline-friendly)

What this script checks:
1) The backend answers a question that IS supported by local uploaded text.
2) The backend answers a question that is NOT supported with an "I don't know"
   style response.

How it works:
- Uploads a small Markdown fixture via `POST /api/files/upload`.
- Calls `POST /api/assistant/chat` for two questions.
- Validates:
  - supported question: `used_citations` non-empty and the answer contains
    an expected keyword (e.g., "Paris" / "Eiffel Tower").
  - unsupported question: answer contains "don't know" / "I don't know" style text.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Tuple


def _post_json(url: str, payload: Dict[str, Any], timeout_s: int = 600) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        return json.loads(body)


def _wait_for_backend(base_url: str, timeout_s: int = 120) -> None:
    health_url = f"{base_url.rstrip('/')}/health"
    import time

    start = time.time()
    last_err: str = ""
    while time.time() - start < timeout_s:
        try:
            with urllib.request.urlopen(health_url, timeout=5) as resp:
                if resp.status == 200:
                    return
        except Exception as e:
            last_err = str(e)
            time.sleep(1)
    raise RuntimeError(f"Backend did not become healthy in time. Last error: {last_err}")


def _upload_file_multipart(
    url: str,
    field_name: str,
    filename: str,
    content_type: str,
    content: bytes,
    timeout_s: int = 600,
) -> Dict[str, Any]:
    boundary = "----loominboundary"
    parts = []
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(content)
    parts.append(f"\r\n".encode("utf-8"))
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))

    body = b"".join(parts)
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        resp_body = resp.read().decode("utf-8", errors="ignore")
        return json.loads(resp_body)


def _contains_any(haystack: str, needles: List[str]) -> bool:
    h = haystack.lower()
    return any(n.lower() in h for n in needles)


def main() -> int:
    backend_base = os.getenv("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")
    _wait_for_backend(backend_base)

    model_id = os.getenv("VERIFY_MODEL_ID", "loomin-llama3")
    fixture_markdown = (
        "# Loomin-Docs Faithfulness Fixture\n\n"
        "Facts:\n"
        "- The Eiffel Tower is located in Paris.\n"
        "- Python is a programming language.\n"
    )

    doc_id = os.getenv("VERIFY_DOC_ID", "doc-verify")
    expected_keywords = [
        "eiffel tower",
        "paris",
        "python",
        "programming language",
    ]
    print(f"[verify] Backend: {backend_base}")
    print(f"[verify] Uploading fixture to docId={doc_id} (backend indexes globally)")

    upload_url = f"{backend_base}/api/files/upload"
    _upload_file_multipart(
        url=upload_url,
        field_name="file",
        filename="fixture.md",
        content_type="text/markdown",
        content=fixture_markdown.encode("utf-8"),
    )

    # Supported query
    supported_question = "Where is the Eiffel Tower located?"
    chat_url = f"{backend_base}/api/assistant/chat"

    print("[verify] Supported query...")
    supported_resp = _post_json(
        chat_url,
        {
            "docId": doc_id,
            "modelId": model_id,
            "messages": [{"role": "user", "content": supported_question}],
        },
        timeout_s=600,
    )

    if not isinstance(supported_resp, dict):
        print("[verify] FAIL: supported_resp was not a JSON object")
        return 2

    answer_1 = str(supported_resp.get("answer", ""))
    used_citations_1 = supported_resp.get("used_citations") or []
    supported_answer_ok = _contains_any(answer_1, ["paris", "eiffel tower"])
    supported_citations_ok = isinstance(used_citations_1, list) and len(used_citations_1) > 0
    supported_ok = supported_answer_ok and supported_citations_ok

    # Unsupported query
    unsupported_question = "What is the capital of Neverland?"
    print("[verify] Unsupported query...")
    unsupported_resp = _post_json(
        chat_url,
        {
            "docId": doc_id,
            "modelId": model_id,
            "messages": [{"role": "user", "content": unsupported_question}],
        },
        timeout_s=600,
    )

    if not isinstance(unsupported_resp, dict):
        print("[verify] FAIL: unsupported_resp was not a JSON object")
        return 2

    answer_2 = str(unsupported_resp.get("answer", ""))
    used_citations_2 = unsupported_resp.get("used_citations") or []

    unknown_ok = _contains_any(
        answer_2,
        [
            "don't know",
            "i don't know",
            "do not know",
            "unknown",
            "cannot determine",
            "not present",
        ],
    )

    # Also ensure it doesn't hallucinate known facts from the fixture.
    hallucinated_known_facts = _contains_any(answer_2, ["paris", "eiffel tower", "python"])
    refusal_ok = unknown_ok and not hallucinated_known_facts

    print("[verify] Results")
    print(f"- supported_used_citations_nonempty: {bool(used_citations_1)}")
    print(
        f"- supported_answer_grounded_keywords: {_contains_any(answer_1, expected_keywords)}"
    )
    print(f"- unsupported_refusal_ok: {refusal_ok}")
    if used_citations_2:
        print(
            f"- note: unsupported query still retrieved citations: {used_citations_2}"
        )

    if supported_ok and refusal_ok:
        print("[verify] PASS")
        return 0

    print("[verify] FAIL")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

