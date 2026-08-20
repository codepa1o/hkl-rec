from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from backend.app.live_news.content_policy import ContentPolicy, parse_content_policy


@dataclass(frozen=True)
class SourcePolicy:
    domain: str
    languages: frozenset[Literal["zh", "en"]]
    quality_weight: float
    content: ContentPolicy


@dataclass(frozen=True)
class SourceAllowlist:
    policies: tuple[SourcePolicy, ...]

    def match(self, host: str) -> SourcePolicy | None:
        normalized = host.rstrip(".").lower()
        for policy in self.policies:
            if normalized == policy.domain or normalized.endswith(f".{policy.domain}"):
                return policy
        return None


def load_allowlist(path: Path) -> SourceAllowlist:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError(f"live news allowlist has no sources: {path}")
    policies: list[SourcePolicy] = []
    seen: set[str] = set()
    for raw in raw_sources:
        if not isinstance(raw, dict):
            raise ValueError("each live news source must be an object")
        domain = str(raw.get("domain") or "").strip().lower().rstrip(".")
        languages = raw.get("languages")
        quality_weight = float(raw.get("quality_weight", -1))
        if not domain or domain in seen:
            raise ValueError(f"invalid or duplicate live news domain: {domain!r}")
        if not isinstance(languages, list) or not languages:
            raise ValueError(f"source {domain} must declare languages")
        language_set = frozenset(str(value) for value in languages)
        if not language_set <= {"zh", "en"}:
            raise ValueError(f"source {domain} has unsupported languages")
        if not 0.0 <= quality_weight <= 1.0:
            raise ValueError(f"source {domain} quality_weight must be between 0 and 1")
        seen.add(domain)
        policies.append(
            SourcePolicy(
                domain=domain,
                languages=cast(frozenset[Literal["zh", "en"]], language_set),
                quality_weight=quality_weight,
                content=parse_content_policy(raw.get("content")),
            )
        )
    return SourceAllowlist(tuple(policies))
