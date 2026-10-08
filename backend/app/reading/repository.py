"""Persistence and exhaustive selection for personal reading tools."""

import hashlib
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from backend.app.data_contracts.mind import source_domain
from backend.app.live_news.categories import category_clause, live_category_id
from backend.app.live_news.topic_classifier import load_taxonomy
from backend.app.news_spaces.types import LiveLanguage, NewsSpace
from backend.app.repositories.content_dao import news_category_exists
from backend.app.schemas.feed import FeedItem, FeedResponse
from backend.app.schemas.reading import (
    ReadingRuleRequest,
    ReadingStateRequest,
    SavedSearchRequest,
)

from .policy import evaluate_rules, normalize


class ReadingRepository:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.pool = runtime._connection_pool

    @contextmanager
    def connection(self) -> Iterator[Any]:
        connection = self.pool.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def rows(connection: Any, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def states(
        self, connection: Any, user_id: int, space: NewsSpace, ids: list[str] | None = None
    ) -> Any:
        if ids is not None and not ids:
            return []
        sql = "SELECT article_id,saved,read,source_space FROM reading_state WHERE user_id=%s AND source_space=%s"
        params: Sequence[Any]
        if ids is not None:
            sql += " AND article_id=ANY(%s)"
            params = (user_id, space, ids)
        else:
            sql += " ORDER BY article_id"
            params = (user_id, space)
        rows = self.rows(connection, sql, params)
        by_id = {r["article_id"]: r for r in rows}
        if ids is None:
            return by_id
        return [
            by_id.get(aid, dict(article_id=aid, source_space=space, saved=False, read=False))
            for aid in ids
        ]

    def rules(self, connection: Any, user_id: int, space: NewsSpace) -> list[dict[str, Any]]:
        return self.rows(
            connection,
            "SELECT id,source_space,target_type,value,effect,enabled FROM reading_rule WHERE user_id=%s AND source_space=%s ORDER BY id",
            (user_id, space),
        )

    def revision(self, connection: Any, user_id: int, space: NewsSpace) -> str:
        value = [self.rules(connection, user_id, space), self.states(connection, user_id, space)]
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    def write_state(self, user_id: int, payload: ReadingStateRequest) -> dict[str, Any]:
        with self.connection() as conn:
            # Unknown/deleted articles may retain or clear existing state, but cannot be newly saved.
            table, key = (
                ("mind_news", "news_id")
                if payload.source_space == "mind"
                else ("live_news", "article_id")
            )
            exists = self.rows(
                conn, f"SELECT {key} FROM {table} WHERE {key}=%s", (payload.article_id,)
            )
            old = self.rows(
                conn,
                "SELECT article_id FROM reading_state WHERE user_id=%s AND source_space=%s AND article_id=%s",
                (user_id, payload.source_space, payload.article_id),
            )
            if not exists and not old:
                raise HTTPException(404, "新闻不存在或已失效")
            rows = self.rows(
                conn,
                """INSERT INTO reading_state(user_id,source_space,article_id,saved,read)
                VALUES(%s,%s,%s,COALESCE(%s,false),COALESCE(%s,false))
                ON CONFLICT(user_id,source_space,article_id) DO UPDATE SET
                saved=COALESCE(%s,reading_state.saved),read=COALESCE(%s,reading_state.read),updated_at=CURRENT_TIMESTAMP
                RETURNING article_id,source_space,saved,read""",
                (
                    user_id,
                    payload.source_space,
                    payload.article_id,
                    payload.saved,
                    payload.read,
                    payload.saved,
                    payload.read,
                ),
            )
            return rows[0]

    def write_rule(self, user_id: int, payload: ReadingRuleRequest) -> dict[str, Any]:
        with self.connection() as conn:
            if payload.target_type == "source":
                value = normalize(payload.value).rstrip(".")
                parsed = urlparse("https://" + value)
                if parsed.hostname != value or "." not in value or parsed.path or parsed.port:
                    raise HTTPException(422, "请输入完整来源域名，例如 news.example.com")
                payload.value = value
            if payload.target_type == "topic":
                keys = self.rows(
                    conn,
                    "SELECT topic_key,display_name FROM topic WHERE source_space=%s",
                    (payload.source_space,),
                )
                valid = {
                    normalize(str(row[k] or ""))
                    for row in keys
                    for k in ("topic_key", "display_name")
                }
                if payload.source_space == "live":
                    valid.update(
                        normalize(t["key"].replace("live:", "live-", 1))
                        for t in load_taxonomy()["topics"]
                    )
                else:
                    valid.update(
                        normalize(r["category"])
                        for r in self.rows(conn, "SELECT DISTINCT category FROM mind_news")
                    )
                if payload.value not in valid:
                    raise HTTPException(422, "请选择当前空间中的有效主题")
            params = (payload.target_type, payload.value, payload.effect, payload.enabled)
            if payload.id is not None:
                duplicate = self.rows(
                    conn,
                    "SELECT id FROM reading_rule WHERE user_id=%s AND source_space=%s AND target_type=%s AND value=%s AND id<>%s",
                    (user_id, payload.source_space, payload.target_type, payload.value, payload.id),
                )
                if duplicate:
                    raise HTTPException(409, "相同规则已经存在，请修改已有规则")
                rows = self.rows(
                    conn,
                    """UPDATE reading_rule SET target_type=%s,value=%s,effect=%s,enabled=%s
                    WHERE id=%s AND user_id=%s AND source_space=%s RETURNING id,source_space,target_type,value,effect,enabled""",
                    (*params, payload.id, user_id, payload.source_space),
                )
            else:
                rows = self.rows(
                    conn,
                    """INSERT INTO reading_rule(user_id,source_space,target_type,value,effect,enabled)
                    VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,source_space,target_type,value)
                    DO UPDATE SET effect=EXCLUDED.effect,enabled=EXCLUDED.enabled
                    RETURNING id,source_space,target_type,value,effect,enabled""",
                    (user_id, payload.source_space, *params),
                )
            if not rows:
                raise HTTPException(404, "规则不存在")
            return rows[0]

    def validate_category(self, conn: Any, space: NewsSpace, category: str | None) -> None:
        if space == "live":
            live_category_id(category)
        elif category is not None and not news_category_exists(conn, category):
            raise HTTPException(422, "请选择有效新闻分类")

    def searches(self, conn: Any, user_id: int, space: NewsSpace) -> list[dict[str, Any]]:
        return self.rows(
            conn,
            "SELECT id,source_space,query,language,NULLIF(category,'') AS category FROM reading_search WHERE user_id=%s AND source_space=%s ORDER BY id DESC",
            (user_id, space),
        )

    def write_search(self, user_id: int, payload: SavedSearchRequest) -> dict[str, Any]:
        with self.connection() as conn:
            self.validate_category(conn, payload.source_space, payload.category)
            return self.rows(
                conn,
                """INSERT INTO reading_search(user_id,source_space,query,language,category)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT(user_id,source_space,query,language,category)
                DO UPDATE SET query=EXCLUDED.query RETURNING id,source_space,query,language,NULLIF(category,'') AS category""",
                (
                    user_id,
                    payload.source_space,
                    payload.query,
                    payload.language,
                    payload.category or "",
                ),
            )[0]

    def delete(
        self, user_id: int, space: NewsSpace, kind: Literal["rule", "search"], identifier: int
    ) -> dict[str, bool]:
        table = {"rule": "reading_rule", "search": "reading_search"}[kind]
        with self.connection() as conn:
            rows = self.rows(
                conn,
                f"DELETE FROM {table} WHERE id=%s AND user_id=%s AND source_space=%s RETURNING id",
                (identifier, user_id, space),
            )
            if not rows:
                raise HTTPException(404, "记录不存在")
            return {"deleted": True}

    def catalog(
        self,
        conn: Any,
        space: NewsSpace,
        language: LiveLanguage = "all",
        category: str | None = None,
        *,
        available_only: bool = True,
    ) -> list[dict[str, Any]]:
        self.validate_category(conn, space, category)
        if space == "live":
            if not self.runtime._settings.live_news_enabled:
                raise HTTPException(503, "实时新闻空间尚未启用")
            clause, category_params = category_clause(category)
            lang_clause = "" if language == "all" else "AND language=%s"
            params = ([] if language == "all" else [language]) + list(category_params)
            active = (
                "AND status='active' AND discovered_at>=CURRENT_TIMESTAMP-INTERVAL '30 days'"
                if available_only
                else ""
            )
            rows = self.rows(
                conn,
                f"""SELECT *,summary AS abstract,canonical_url AS url FROM live_news WHERE TRUE {active} {lang_clause} {clause}""",
                tuple(params),
            )
            article_ids = [row["article_id"] for row in rows]
            topic_rows = (
                self.rows(
                    conn,
                    """SELECT m.article_id,t.topic_key,t.display_name FROM live_news_topic m JOIN topic t USING(topic_id)
                JOIN live_topic_enrichment_job j ON j.article_id=m.article_id WHERE j.status='completed' AND m.article_id=ANY(%s) """,
                    (article_ids,),
                )
                if article_ids
                else []
            )
        else:
            if language != "all":
                raise HTTPException(422, "历史新闻空间暂不支持语言筛选")
            clause = "WHERE n.category=%s" if category else ""
            rows = self.rows(
                conn,
                f"""SELECT n.*,n.news_id AS article_id,COALESCE(s.hot_score,0) AS hot_score
                FROM mind_news n LEFT JOIN mind_news_stats s USING(news_id) {clause}""",
                (category,) if category else (),
            )
            article_ids = [row["article_id"] for row in rows]
            topic_rows = (
                self.rows(
                    conn,
                    "SELECT m.news_id AS article_id,t.topic_key,t.display_name FROM mind_news_topic m JOIN topic t USING(topic_id) WHERE m.news_id=ANY(%s)",
                    (article_ids,),
                )
                if article_ids
                else []
            )
        topics: dict[str, list[str]] = {}
        for row in topic_rows:
            topics.setdefault(row["article_id"], []).extend(
                [
                    row["topic_key"],
                    row["display_name"] or "",
                    row["topic_key"].replace("live:", "live-", 1),
                ]
            )
        for row in rows:
            row["source_space"] = space
            row["source_domain"] = row.get("source_domain") or source_domain(row.get("url") or "")
            row["topics"] = topics.get(row["article_id"], [])
        return rows

    def library(
        self,
        user_id: int,
        space: NewsSpace,
        saved_only: bool,
        unread_only: bool,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        with self.connection() as conn:
            if space == "live":
                join = "LEFT JOIN live_news article ON article.article_id=state.article_id"
                title = "COALESCE(article.title,'新闻已失效')"
                url = "COALESCE(article.canonical_url,'')"
                domain = "COALESCE(article.source_domain,'')"
                available = "COALESCE(article.status='active',false)"
            else:
                join = "LEFT JOIN mind_news article ON article.news_id=state.article_id"
                title = "COALESCE(article.title,'新闻已失效')"
                url = "COALESCE(article.url,'')"
                domain = "CASE WHEN article.url IS NOT NULL THEN split_part(split_part(article.url,'//',2),'/',1) ELSE '' END"
                available = "article.news_id IS NOT NULL"
            saved_clause = "AND state.saved" if saved_only else ""
            unread_clause = "AND NOT state.read" if unread_only else ""
            rows = self.rows(
                conn,
                f"""SELECT state.article_id,state.source_space,state.saved,state.read,
                    {title} AS title,{url} AS url,{domain} AS source_domain,{available} AS available
                FROM reading_state state {join} WHERE state.user_id=%s AND state.source_space=%s
                  {saved_clause} {unread_clause} ORDER BY state.updated_at DESC,state.article_id ASC
                OFFSET %s LIMIT %s""",
                (user_id, space, offset, limit + 1),
            )
            return {"items": rows[:limit], "has_more": len(rows) > limit}

    def feed(
        self,
        user_id: int,
        space: NewsSpace,
        language: LiveLanguage,
        category: str | None,
        unread_only: bool,
        page_size: int,
        request_id: str,
        cursor: str | None,
    ) -> FeedResponse:
        context = dict(
            language=language, category=category, unread_only=unread_only, page_size=page_size
        )
        with self.connection() as conn:
            revision = self.revision(conn, user_id, space)
            offset = 0
            snapshot = None
            if cursor:
                try:
                    sid, position = cursor.split(".")
                    offset = int(position)
                    if offset < 0 or len(sid) != 32:
                        raise ValueError()
                except ValueError as exc:
                    raise HTTPException(422, "分页标记无效，请刷新") from exc
                found = self.rows(
                    conn,
                    "SELECT * FROM reading_feed WHERE id=%s AND user_id=%s AND source_space=%s AND created_at>CURRENT_TIMESTAMP-INTERVAL '1 day'",
                    (sid, user_id, space),
                )
                if not found:
                    raise HTTPException(409, "阅读列表已过期，请刷新")
                snapshot = found[0]
            elif request_id:
                found = self.rows(
                    conn,
                    "SELECT * FROM reading_feed WHERE request_id=%s AND user_id=%s AND source_space=%s",
                    (request_id, user_id, space),
                )
                snapshot = found[0] if found else None
            if snapshot and (snapshot["context"] != context or snapshot["revision"] != revision):
                raise HTTPException(409, "阅读规则或已读状态已变化，请刷新列表")
            if not snapshot:
                rules = self.rules(conn, user_id, space)
                states = self.states(conn, user_id, space)
                rows = self.catalog(conn, space, language, category)
                eligible = []
                effects = {}
                for row in rows:
                    if unread_only and states.get(row["article_id"], {}).get("read"):
                        continue
                    blocked, boost, reasons = evaluate_rules(row, rules)
                    if not blocked:
                        eligible.append(row)
                        effects[row["article_id"]] = (boost, reasons)
                if space == "mind" and len(eligible) > 3000:
                    eligible = sorted(
                        eligible,
                        key=lambda row: (-float(row.get("hot_score") or 0.0), row["article_id"]),
                    )[:3000]
                real_request_id = (
                    "reading-"
                    + hashlib.sha256(f"{user_id}:{space}:{request_id}".encode()).hexdigest()[:32]
                )
                if space == "mind" and eligible:
                    response = self.runtime.get_feed(
                        user_id=user_id,
                        page_size=len(eligible),
                        debug=False,
                        include_sponsored=False,
                        request_id=real_request_id,
                        category=category,
                        reading_candidates=eligible,
                    )
                    items = response.items
                elif space == "live":
                    live = self.runtime._live_news_space
                    now = datetime.now(UTC)
                    items = [live._feed_item(live._candidate(row), now=now) for row in eligible]
                    # Register every snapshot article against its real feed request for click attribution.
                    from backend.app.repositories.sponsored_dao import (
                        claim_feed_request,
                        complete_feed_request,
                    )

                    claim_feed_request(
                        conn,
                        request_id=real_request_id,
                        source_space=space,
                        user_id=user_id,
                        page_size=max(1, len(items)),
                        debug=False,
                        include_sponsored=False,
                        experiment_arm="default",
                        as_of_ts=None,
                        category=category,
                        cursor_token=None,
                    )
                    complete_feed_request(
                        conn,
                        request_id=real_request_id,
                        source_space=space,
                        news_ids=[i.article_id for i in items],
                        next_cursor=None,
                    )
                else:
                    items = []
                for item in items:
                    boost, reasons = effects[item.article_id]
                    item.scores.final_score += boost
                    if reasons:
                        item.selected_reason = "；".join(reasons)
                items.sort(key=lambda item: (-item.scores.final_score, item.article_id))
                sid = uuid4().hex
                snapshot = dict(
                    id=sid,
                    items=[i.model_dump(mode="json") for i in items],
                    request_id=real_request_id,
                )
                # Store caller id separately in context is unnecessary: external idempotency key is the row request_id.
                stored_items = {"request_id": real_request_id, "items": snapshot["items"]}
                inserted = self.rows(
                    conn,
                    """INSERT INTO reading_feed(id,user_id,source_space,context,revision,items,request_id)
                    VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,source_space,request_id) DO NOTHING RETURNING id""",
                    (
                        sid,
                        user_id,
                        space,
                        Jsonb(context),
                        revision,
                        Jsonb(stored_items),
                        request_id or real_request_id,
                    ),
                )
                if inserted:
                    snapshot["items"] = stored_items
                else:
                    snapshot = self.rows(
                        conn,
                        "SELECT * FROM reading_feed WHERE user_id=%s AND source_space=%s AND request_id=%s",
                        (user_id, space, request_id or real_request_id),
                    )[0]
            data = snapshot["items"]
            items = data["items"]
            has_more = offset + page_size < len(items)
            return FeedResponse(
                user_id=user_id,
                source_space=space,
                request_id=data["request_id"],
                items=[FeedItem.model_validate(i) for i in items[offset : offset + page_size]],
                has_more=has_more,
                next_cursor=f"{snapshot['id']}.{offset + page_size}" if has_more else None,
            )
