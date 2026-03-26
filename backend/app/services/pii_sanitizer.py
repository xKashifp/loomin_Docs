from __future__ import annotations

import re
from typing import List, Tuple


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_GENERIC_KEY_RE = re.compile(
    r"(?i)\b(api[_ -]?key|secret|password|token)\b\s*[:=]\s*([A-Za-z0-9_\-]{8,})"
)
# Long base64-ish blocks (avoid false positives by requiring length).
_BASE64_RE = re.compile(r"\b[A-Za-z0-9+/]{32,}={0,2}\b")
_LONG_DIGITS_RE = re.compile(r"\b\d{9,}\b")


def mask_pii(text: str) -> Tuple[str, List[str]]:
    """
    Redacts common sensitive patterns before the prompt hits the LLM.
    Returns (masked_text, matched_pattern_names).
    """

    matched: List[str] = []

    masked = text

    def _mask(regex: re.Pattern, name: str, repl: str) -> None:
        nonlocal masked, matched
        if regex.search(masked) is not None:
            matched.append(name)
            masked = regex.sub(repl, masked)

    _mask(_EMAIL_RE, "email", "[REDACTED_EMAIL]")
    _mask(_UUID_RE, "uuid", "[REDACTED_UUID]")
    _mask(_GENERIC_KEY_RE, "credential_kv", lambda m: f"{m.group(1)}:[REDACTED_VALUE]")
    _mask(_BASE64_RE, "base64_block", "[REDACTED_B64]")
    _mask(_LONG_DIGITS_RE, "long_digits", "[REDACTED_NUMBER]")

    return masked, matched

