def test_reading_requires_session_even_research_mode(unwired_client):
    response = unwired_client.get("/reading/states?article_ids=N1")
    assert response.status_code in (401, 503)


def test_chinese_normalization_and_hard_block_precedence():
    from backend.app.reading.policy import evaluate_rules

    article = dict(
        title="中国ＡＩ产业发展", abstract="", source_domain="news.example.com", topics=["科技"]
    )
    rules = [
        dict(target_type="keyword", value="ai", effect="prefer", enabled=True),
        dict(target_type="keyword", value="中国ai", effect="block", enabled=True),
    ]
    assert evaluate_rules(article, rules)[0] is True
    rules[1]["enabled"] = False
    blocked, boost, reasons = evaluate_rules(article, rules)
    assert not blocked and boost > 0 and "ai" in "".join(reasons)
    assert not evaluate_rules(
        article, [dict(target_type="source", value="example.com", effect="block", enabled=True)]
    )[0]


def test_reading_crud_and_isolation(postgres_client, seeded_live_articles):
    from backend.app.auth.service import AuthenticatedUser
    from backend.app.routers.auth import get_current_user

    client = postgres_client
    uid = seeded_live_articles.user_id
    client.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        uid, "test@example.com", "Test"
    )
    aid = seeded_live_articles.article_ids[1]
    payload = dict(source_space="live", article_id=aid, saved=True)
    response = client.post("/reading/state", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["saved"] and not response.json()["read"]
    assert client.post("/reading/state", json={**payload, "read": True}).json()["read"]
    assert client.get("/reading/library?source_space=live").json()["items"][0]["article_id"] == aid
    assert (
        client.get("/reading/states?source_space=mind&article_ids=N1").json()["items"][0]["saved"]
        is False
    )
    assert (
        client.post(
            "/reading/state", json=payload, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    rule = dict(
        source_space="live", target_type="keyword", value="中文", effect="block", enabled=True
    )
    first = client.post("/reading/rules", json=rule)
    assert first.status_code == 200, first.text
    assert client.post("/reading/rules", json=rule).json()["id"] == first.json()["id"]
    assert client.post("/reading/rules", json={**rule, "value": "  "}).status_code == 422
    search = dict(source_space="live", query="中国科技", language="zh", category=None)
    first_search = client.post("/reading/searches", json=search)
    assert first_search.status_code == 200, first_search.text
    assert client.post("/reading/searches", json=search).json()["id"] == first_search.json()["id"]
    assert (
        client.post(
            f"/reading/rules/{first.json()['id']}/delete", json={"source_space": "mind"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/reading/rules/{first.json()['id']}/delete", json={"source_space": "live"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/reading/searches/{first_search.json()['id']}/delete", json={"source_space": "live"}
        ).status_code
        == 200
    )


def test_personal_live_feed_applies_chinese_block_before_pagination(
    postgres_client, seeded_live_articles
):
    from backend.app.auth.service import AuthenticatedUser
    from backend.app.routers.auth import get_current_user

    uid = seeded_live_articles.user_id
    postgres_client.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        uid, "test@example.com", "Test"
    )
    created = postgres_client.post(
        "/reading/rules",
        json={
            "source_space": "live",
            "target_type": "keyword",
            "value": "中文",
            "effect": "block",
            "enabled": True,
        },
    )
    assert created.status_code == 200, created.text

    response = postgres_client.get(
        "/reading/feed",
        params={
            "source_space": "live",
            "page_size": 10,
            "request_id": "reading-live-test",
            "language": "all",
            "unread_only": False,
        },
    )
    assert response.status_code == 200, response.text
    assert [item["article_id"] for item in response.json()["items"]] == [
        seeded_live_articles.article_ids[0]
    ]
    assert response.json()["has_more"] is False


def test_personal_live_search_reports_hidden_results_and_can_include_them(
    postgres_client, seeded_live_articles
):
    from backend.app.auth.service import AuthenticatedUser
    from backend.app.routers.auth import get_current_user

    uid = seeded_live_articles.user_id
    postgres_client.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        uid, "test@example.com", "Test"
    )
    postgres_client.post(
        "/reading/rules",
        json={
            "source_space": "live",
            "target_type": "keyword",
            "value": "中文",
            "effect": "block",
            "enabled": True,
        },
    )
    hidden = postgres_client.post(
        "/reading/search",
        json={
            "source_space": "live",
            "query": "实时中文测试新闻",
            "language": "zh",
            "category": None,
            "include_hidden": False,
            "page_size": 10,
        },
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["items"] == []
    assert hidden.json()["hidden_count"] == 1
    included = postgres_client.post(
        "/reading/search",
        json={
            "source_space": "live",
            "query": "实时中文测试新闻",
            "language": "zh",
            "category": None,
            "include_hidden": True,
            "page_size": 10,
        },
    )
    assert included.status_code == 200, included.text
    assert included.json()["items"][0]["article_id"] == seeded_live_articles.article_ids[1]


def test_personal_feed_cursor_is_idempotent_and_invalidates_after_read_change(
    postgres_client, seeded_live_articles
):
    from backend.app.auth.service import AuthenticatedUser
    from backend.app.routers.auth import get_current_user

    uid = seeded_live_articles.user_id
    postgres_client.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        uid, "test@example.com", "Test"
    )
    first = postgres_client.get(
        "/reading/feed",
        params={"source_space": "live", "page_size": 1, "request_id": "reading-cursor-first"},
    )
    assert first.status_code == 200, first.text
    page_one = first.json()
    assert page_one["has_more"] is True
    repeated = postgres_client.get(
        "/reading/feed",
        params={"source_space": "live", "page_size": 1, "request_id": "reading-cursor-first"},
    )
    assert repeated.json()["items"] == page_one["items"]
    second = postgres_client.get(
        "/reading/feed",
        params={
            "source_space": "live",
            "page_size": 1,
            "request_id": "reading-cursor-second",
            "cursor": page_one["next_cursor"],
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["items"][0]["article_id"] != page_one["items"][0]["article_id"]
    changed = postgres_client.post(
        "/reading/state",
        json={
            "source_space": "live",
            "article_id": page_one["items"][0]["article_id"],
            "read": True,
        },
    )
    assert changed.status_code == 200, changed.text
    stale = postgres_client.get(
        "/reading/feed",
        params={
            "source_space": "live",
            "page_size": 1,
            "request_id": "reading-cursor-after-change",
            "cursor": page_one["next_cursor"],
        },
    )
    assert stale.status_code == 409
