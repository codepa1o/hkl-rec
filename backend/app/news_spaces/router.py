from __future__ import annotations

from dataclasses import dataclass

from backend.app.news_spaces.types import NewsSpace


@dataclass(frozen=True)
class NewsSpaceRouter[T]:
    mind: T
    live: T

    def for_space(self, source_space: NewsSpace) -> T:
        if source_space == "mind":
            return self.mind
        if source_space == "live":
            return self.live
        raise ValueError(f"unsupported source_space: {source_space}")
