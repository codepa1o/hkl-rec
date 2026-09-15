from __future__ import annotations

import pytest

from backend.app.config import Settings, local_research_content_allowed
from backend.app.live_news.content_policy import ContentPolicy


def test_local_research_gate_requires_development_and_explicit_flag() -> None:
    assert local_research_content_allowed(
        Settings(environment="development", local_research_fulltext_enabled=True)
    )
    assert not local_research_content_allowed(
        Settings(environment="development", local_research_fulltext_enabled=False)
    )
    assert not local_research_content_allowed(
        Settings(environment="production", local_research_fulltext_enabled=True)
    )


def test_insecure_http_requires_local_research_scope() -> None:
    with pytest.raises(ValueError, match="local_research"):
        ContentPolicy(
            mode="html",
            display="full_text",
            access_scope="public",
            adapter="xinhuanet",
            target_extraction_version="zh-xinhua-1",
            allow_insecure_http=True,
        )
