from __future__ import annotations

from backend.app.news_spaces.types import LiveLanguage, NewsSpace
from backend.app.repositories.base import RuntimeRepository
from backend.app.schemas.feed import FeedExperimentArm, FeedResponse


class FeedService:
    def __init__(self, repository: RuntimeRepository) -> None:
        self._repository = repository

    def get_feed(
        self,
        user_id: int,
        page_size: int,
        debug: bool,
        experiment_arm: FeedExperimentArm = "default",
        include_sponsored: bool = True,
        request_id: str | None = None,
        cursor: str | None = None,
        as_of_ts: int | None = None,
        category: str | None = None,
        source_space: NewsSpace = "mind",
        language: LiveLanguage = "all",
    ) -> FeedResponse:
        return self._repository.get_feed(
            user_id=user_id,
            page_size=page_size,
            debug=debug,
            experiment_arm=experiment_arm,
            include_sponsored=include_sponsored,
            request_id=request_id,
            cursor=cursor,
            as_of_ts=as_of_ts,
            category=category,
            source_space=source_space,
            language=language,
        )
