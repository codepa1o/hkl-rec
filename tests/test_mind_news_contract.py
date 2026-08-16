from __future__ import annotations

import pytest

from backend.app.data_contracts.mind import (
    MindContractError,
    news_internal_id,
    parse_news_id,
    parse_news_row,
)


def test_news_row_preserves_the_exact_eight_mind_fields() -> None:
    news = parse_news_row("N123\tNews\tLocal\tTitle\t\thttps://example.com/story\t[]\t[]")

    assert news.news_id == "N123"
    assert news.category == "News"
    assert news.subcategory == "Local"
    assert news.title == "Title"
    assert news.abstract == ""
    assert news.url == "https://example.com/story"
    assert news.title_entities == []
    assert news.abstract_entities == []
    assert set(vars(news)) == {
        "news_id",
        "category",
        "subcategory",
        "title",
        "abstract",
        "url",
        "title_entities",
        "abstract_entities",
    }


def test_news_id_validation_does_not_coerce_the_canonical_identifier() -> None:
    assert parse_news_id("N00123") == "N00123"
    assert news_internal_id("N00123") == 123

    with pytest.raises(MindContractError, match="Invalid MIND news ID"):
        parse_news_id("123")


@pytest.mark.parametrize("entities", ["{}", '"entity"', "null", "1"])
def test_entities_must_be_json_arrays(entities: str) -> None:
    with pytest.raises(MindContractError, match="array"):
        parse_news_row(
            [
                "N1",
                "News",
                "Local",
                "Title",
                "Abstract",
                "https://example.com/story",
                entities,
                "[]",
            ]
        )


def test_entity_array_members_must_be_objects() -> None:
    with pytest.raises(MindContractError, match="objects"):
        parse_news_row("N1\tNews\tLocal\tTitle\tAbstract\thttps://example.com\t[1]\t[]")


def test_malformed_entity_json_is_rejected() -> None:
    with pytest.raises(MindContractError, match="valid JSON"):
        parse_news_row("N1\tNews\tLocal\tTitle\tAbstract\thttps://example.com\t[\t[]")
