from __future__ import annotations

from backend.app.news_spaces.types import NewsSpace
from backend.app.repositories.base import RuntimeRepository
from backend.app.schemas.profile import DebugProfileResponse, ProfileResponse


class ProfileService:
    def __init__(self, repository: RuntimeRepository) -> None:
        self._repository = repository

    def get_debug_profile(
        self, user_id: int, source_space: NewsSpace = "mind"
    ) -> DebugProfileResponse:
        return self._repository.get_debug_profile(user_id, source_space)

    def get_profile(self, user_id: int, source_space: NewsSpace = "mind") -> ProfileResponse:
        return self._repository.get_profile(user_id, source_space)

    def reset_profile(self, user_id: int, source_space: NewsSpace = "mind") -> ProfileResponse:
        return self._repository.reset_profile(user_id, source_space)
