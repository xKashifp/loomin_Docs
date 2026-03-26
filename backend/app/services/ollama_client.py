from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import httpx


class OllamaClient:
    def __init__(self, base_url: str, chat_model: str, embed_model: str):
        self._base_url = base_url.rstrip("/")
        self._chat_model = chat_model
        self._embed_model = embed_model

    async def embed(self, texts: List[str]) -> Tuple[List[List[float]], Dict[str, Any]]:
        url = f"{self._base_url}/api/embed"
        payload: Dict[str, Any] = {"model": self._embed_model}
        # Ollama supports string or array input.
        payload["input"] = texts if len(texts) > 1 else texts[0]

        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        embeddings = data.get("embeddings") or []
        meta = {
            "total_duration": data.get("total_duration", 0),
            "load_duration": data.get("load_duration", 0),
            "prompt_eval_count": data.get("prompt_eval_count", 0),
        }
        return embeddings, meta

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        url = f"{self._base_url}/api/generate"
        use_model = model or self._chat_model

        payload: Dict[str, Any] = {
            "model": use_model,
            "prompt": prompt,
            "stream": False,
        }
        if system_prompt:
            # Ollama's /api/generate supports a dedicated `system` field.
            # This keeps the user prompt clean and lets Modelfile system
            # prompting work as intended.
            payload["system"] = system_prompt
        if options:
            payload["options"] = options

        async with httpx.AsyncClient(timeout=1200) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        return data.get("response", ""), data

