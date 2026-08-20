from __future__ import annotations

import re
from typing import Literal

from backend.app.observability import CROSS_SPACE_VALIDATION_FAILURES

type NewsSpace = Literal["mind", "live"]
type LiveLanguage = Literal["all", "zh", "en"]

DEFAULT_NEWS_SPACE: NewsSpace = "mind"

_MIND_ARTICLE_ID_PATTERN = re.compile(r"^N[0-9]+$")
_LIVE_ARTICLE_ID_PATTERN = re.compile(r"^L[0-9a-f]{32}$")


def validate_article_id_shape(source_space: NewsSpace | str, article_id: str) -> str:
    if source_space == "mind":
        pattern = _MIND_ARTICLE_ID_PATTERN
    elif source_space == "live":
        pattern = _LIVE_ARTICLE_ID_PATTERN
    else:
        CROSS_SPACE_VALIDATION_FAILURES.inc()
        raise ValueError(f"unsupported source_space: {source_space}")

    if not pattern.fullmatch(article_id):
        CROSS_SPACE_VALIDATION_FAILURES.inc()
        raise ValueError(
            f"article_id {article_id!r} does not belong to source_space {source_space!r}"
        )
    return article_id
