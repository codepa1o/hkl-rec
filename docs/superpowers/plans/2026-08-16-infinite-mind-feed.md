# MIND Infinite Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MIND 首页升级为每批 20 篇、会话内去重的游标式无限滚动，并在详情页展示解析后的实体标签。

**Architecture:** 扩展现有 `feed_request` 保存分页会话状态，`/feed` 通过不透明游标连接相邻页面并在候选不足时从完整目录补齐。前端按页面保存请求 ID，使用 IntersectionObserver 追加数据；详情接口将两个 MIND 实体 JSON 字段解析成类型安全的标签。

**Tech Stack:** FastAPI、Pydantic、PostgreSQL/psycopg、Alembic、React、TypeScript、Vitest、Testing Library

---

### Task 1: 扩展信息流分页数据契约

**Files:**
- Modify: `backend/app/schemas/feed.py`
- Modify: `backend/app/routers/feed.py`
- Modify: `backend/app/repositories/base.py`
- Modify: `product-frontend/src/api/types.ts`
- Modify: `product-frontend/src/api/client.ts`
- Test: `tests/test_postgres_smoke.py`
- Test: `product-frontend/src/pages/FeedPage.test.tsx`

- [ ] 先写失败测试：断言 `/feed` 接受 `cursor`，响应包含 `next_cursor` 与 `has_more`；断言前端 `getFeed` 传递游标和 20 条页面大小。
- [ ] 运行目标测试并确认因字段和参数尚不存在而失败。
- [ ] 在 `FeedResponse` 增加 `next_cursor: str | None = None`、`has_more: bool = False`，在路由和仓储协议中传递 `cursor: str | None`。
- [ ] 更新 TypeScript `FeedResponse` 与 `getFeed(userId, pageSize, debug, requestId, cursor)`。
- [ ] 运行目标测试并确认契约测试通过。

### Task 2: 在现有 feed_request 中实现游标和会话去重

**Files:**
- Create: `alembic/versions/20260816_0004_feed_pagination.py`
- Modify: `backend/app/db/schema.py`
- Modify: `backend/app/repositories/sponsored_dao.py`
- Modify: `backend/app/repositories/content_dao.py`
- Modify: `backend/app/repositories/postgres.py`
- Test: `tests/test_sponsored_postgres.py`
- Test: `tests/test_postgres_smoke.py`

- [ ] 先写失败的 PostgreSQL 测试：连续三页各 20 篇，游标连续、60 个 `news_id` 唯一；错误用户或不兼容页面大小复用游标时拒绝。
- [ ] 运行目标测试并确认重复新闻或缺少游标字段导致失败。
- [ ] 给 `feed_request` 增加 `session_id`、`page_number`、`cursor_token`、`returned_news_ids_json`；迁移时为旧行填入安全默认值并建立游标唯一索引。
- [ ] 将 `claim_feed_request` 扩展为解析上一游标、校验请求形状、返回会话上下文，并增加保存本页新闻与下一游标的函数。
- [ ] 在候选选择前加载会话已见新闻并排除；候选不足时从 `mind_news`、`mind_news_stats`、`mind_news_topic` 中选择未见新闻补齐。
- [ ] 根据目录总数和会话已见数量计算 `has_more`，生成下一不透明游标并写入当前请求行。
- [ ] 运行 PostgreSQL 目标测试，确认分页、幂等、赞助归因和会话去重通过。

### Task 3: 解析并返回 MIND 实体

**Files:**
- Modify: `backend/app/schemas/article.py`
- Modify: `backend/app/repositories/content_dao.py`
- Modify: `backend/app/repositories/postgres.py`
- Test: `tests/test_article_card_route.py`
- Test: `tests/test_mind_news_dao.py`

- [ ] 先写失败测试：详情响应包含规范化的标题和摘要实体，`P/O/G` 映射正确，非法元素被忽略。
- [ ] 运行目标测试并确认响应当前缺少实体字段。
- [ ] 定义 `ArticleEntity`，并让 `load_news_rows` 读取 `title_entities`、`abstract_entities`。
- [ ] 增加纯函数解析实体对象，保留 label、type code、Wikidata ID、confidence、surface forms，并把未知类型归为 `other`。
- [ ] 在 `get_article_card` 中填充两个实体数组。
- [ ] 运行目标测试并确认实体解析与八字段数据库契约同时通过。

### Task 4: 实现前端无限滚动和逐页归因

**Files:**
- Modify: `product-frontend/src/pages/FeedPage.tsx`
- Modify: `product-frontend/src/pages/FeedPage.test.tsx`
- Modify: `product-frontend/src/index.css`

- [ ] 先写失败测试：首次请求 20 篇；观察哨兵后携带游标请求下一页；追加后去重；加载失败保留旧列表并可重试；旧新闻曝光和点击仍使用所属页请求 ID。
- [ ] 运行 `npm test -- --run src/pages/FeedPage.test.tsx` 并确认测试因无限滚动尚未实现而失败。
- [ ] 将状态改为页面数组，添加 `nextCursor`、`hasMore`、`loadingMore`、`loadMoreError`，用 `news_id` 生成可见去重列表。
- [ ] 添加 IntersectionObserver 尾部哨兵，接近底部时调用 `getFeed(..., 20, ..., newRequestId, nextCursor)`。
- [ ] 添加已加载数量、追加骨架、重试按钮和全部加载终态；画像或刷新变化时重置信息流会话。
- [ ] 以每条新闻所属页的 request ID 记录曝光、点击和赞助归因。
- [ ] 运行目标测试并确认全部通过。

### Task 5: 在详情页展示实体标签

**Files:**
- Modify: `product-frontend/src/api/types.ts`
- Modify: `product-frontend/src/pages/ArticleDetailPage.tsx`
- Modify: `product-frontend/src/pages/ArticleDetailPage.test.tsx`
- Modify: `product-frontend/src/index.css`

- [ ] 先写失败测试：详情页合并实体并按人物、机构、地点、其他实体分组；同一 Wikidata ID 去重；空实体不显示区域。
- [ ] 运行详情页测试并确认缺少实体区域导致失败。
- [ ] 定义 `ArticleEntity` 类型，增加实体规范化和分组的纯函数。
- [ ] 在摘要下方渲染“相关实体”分组标签，并保持小屏布局可换行。
- [ ] 运行详情页与 PostCard 测试并确认通过。

### Task 6: 文档、迁移、完整验证与真实页面验收

**Files:**
- Modify: `README.md`
- Modify: `backend/README.md`
- Modify: `docs/api_contract.md`
- Modify: `docs/local_runbook.md`

- [ ] 更新接口文档，说明 20 条批次、cursor、has_more、实体响应和八字段渲染矩阵。
- [ ] 在正式 PostgreSQL 执行 `python -m alembic upgrade head`，确认新闻数仍为 65,238 且 `mind_news` 仍只有八个源字段。
- [ ] 运行 `python -m pytest -m "not postgres and not kafka" -q`，期望全部通过。
- [ ] 运行 `python -m pytest -m "postgres and not kafka" -q`，期望除正式库禁止的破坏性导入测试外全部通过。
- [ ] 运行 `npm test -- --run` 与 `npm run build`，期望测试和生产构建通过。
- [ ] 启动本地前后端，用真实浏览器验证首屏 20 篇、触底追加、无重复、详情实体标签和无失败业务请求。
- [ ] 保持全部改动为工作区未暂存状态，不创建提交。

