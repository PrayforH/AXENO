from __future__ import annotations

import re
import unicodedata

from harness.memory_bank.models import MemorySensitivity

_PROHIBITED = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret)\b",
        r"\b(?:authorization|bearer)\s*[:= ]\s*\S+",
        r"\bsk-(?:lf-|live-)?[A-Za-z0-9_-]{16,}\b",
        r"\bdtn_[A-Fa-f0-9]{24,}\b",
        r"\btvly-[A-Za-z0-9_-]{16,}\b",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"\bignore (?:all |the )?(?:previous|prior|system) instructions\b",
        r"\b(?:reveal|print|exfiltrate) (?:the )?(?:system prompt|secrets?|credentials?)\b",
    )
)

_SENSITIVE = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(?:\b(?:diagnosis|medical)\b|病历|疾病|过敏|用药)",
        r"(?:身份证|护照|银行卡|\bbank account\b|\bsocial security\b)",
        r"\b1[3-9]\d{9}\b",
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    )
)


def normalize_memory_content(content: str) -> str:
    normalized = unicodedata.normalize("NFKC", content)
    return " ".join(normalized.strip().split())


def classify_memory(content: str) -> MemorySensitivity:
    if any(pattern.search(content) for pattern in _PROHIBITED):
        return MemorySensitivity.PROHIBITED
    if any(pattern.search(content) for pattern in _SENSITIVE):
        return MemorySensitivity.SENSITIVE
    return MemorySensitivity.PERSONAL


def safe_terms(value: str) -> tuple[str, ...]:
    normalized = normalize_memory_content(value).lower()
    values = re.findall(r"[a-z0-9_]{2,}", normalized)
    for segment in re.findall(r"[\u4e00-\u9fff]+", normalized):
        values.append(segment)
        values.extend(segment[index : index + 2] for index in range(len(segment) - 1))
    return tuple(dict.fromkeys(values))[:32]
