# Category Feed Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在左侧栏展示 MIND-small 的 18 个一级新闻分类，并让用户按分类筛选后端个性化信息流；“全部新闻”保持现有行为，分类切换后分页、兜底、广告和幂等请求均严格限定在所选分类内。

**Architecture:** 后端新增只读 `/categories` 目录接口，并为 `/feed` 增加可选 `category` 查询参数。分类约束在候选召回 SQL、ALS 白名单、兜底和广告候选阶段执行，同时写入 `feed_request` 的请求形状以保护幂等与游标语义。前端将分类保存在 URL 查询参数中，左侧分类区独立滚动，分类变化会创建新的信息流会话并丢弃旧请求的迟到响应。

**Tech Stack:** FastAPI、Pydantic、PostgreSQL/psycopg、Alembic、pytest、React 18、TypeScript、React Router、Vitest、Testing Library、CSS。

---

## 文件映射

- 新增 `backend/app/schemas/category.py`：分类目录响应模型。
- 新增 `backend/app/routers/categories.py`：`GET /categories`。
- 修改 `backend/app/repositories/content_dao.py`：分类目录查询与所有自然候选源的分类条件。
- 修改 `backend/app/repositories/sponsored_dao.py`：请求形状记录分类，广告候选按分类过滤。
- 修改 `backend/app/repositories/base.py`、`unwired.py`、`postgres.py`：扩展仓储契约并贯穿分类参数。
- 修改 `backend/app/services/feed.py`、`product.py`、`backend/app/routers/feed.py`、`backend/app/main.py`、`backend/app/errors.py`：分类参数、接口与错误处理。
- 新增 `alembic/versions/20260816_0005_feed_category_filter.py`：给 `feed_request` 增加可空分类字段和索引。
- 新增/修改 `tests/test_categories_route.py`、`tests/test_feed_pagination_contract.py`、`tests/test_sponsored.py`、`tests/test_sponsored_postgres.py`：后端契约、筛选和幂等测试。
- 修改 `product-frontend/src/api/types.ts`、`api/client.ts`、`localization.ts`：分类类型、接口和中文名称。
- 修改 `product-frontend/src/components/LeftSidebar.tsx`、新增 `LeftSidebar.test.tsx`、修改 `styles/global.css`：18 类单列独立滚动与选中态。
- 修改 `product-frontend/src/pages/FeedPage.tsx`、`FeedPage.test.tsx`：URL 分类、会话重置、迟到响应隔离和错误态。

## Task 1：建立分类目录 API

**Files:**

- Create: `backend/app/schemas/category.py`
- Create: `backend/app/routers/categories.py`
- Create: `tests/test_categories_route.py`
- Modify: `backend/app/repositories/content_dao.py`
- Modify: `backend/app/repositories/base.py`
- Modify: `backend/app/repositories/unwired.py`
- Modify: `backend/app/repositories/postgres.py`
- Modify: `backend/app/services/product.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: 写失败的分类目录路由测试**

在 `tests/test_categories_route.py` 中使用现有应用依赖覆盖方式，断言路由保持认证保护、响应使用原始分类键、数量非负并按 `news_count DESC, key ASC` 排序：

```python
from fastapi.testclient import TestClient

from backend.app.dependencies import get_product_service
from backend.app.main import app
from backend.app.schemas.category import CategoryItem, CategoryListResponse


class StubProductService:
    def list_categories(self) -> CategoryListResponse:
        return CategoryListResponse(
            items=[
                CategoryItem(key="news", news_count=20039),
                CategoryItem(key="sports", news_count=19368),
            ]
        )


def test_categories_returns_raw_keys_and_counts(authenticated_client: TestClient) -> None:
    app.dependency_overrides[get_product_service] = lambda: StubProductService()
    try:
        response = authenticated_client.get("/categories")
    finally:
        app.dependency_overrides.pop(get_product_service, None)

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"key": "news", "news_count": 20039},
            {"key": "sports", "news_count": 19368},
        ]
    }
```

- [ ] **Step 2: 运行测试并确认因接口不存在而失败**

Run: `python -m pytest tests/test_categories_route.py -q`

Expected: `404` 或 `ModuleNotFoundError: backend.app.schemas.category`。

- [ ] **Step 3: 实现响应模型、DAO、仓储、服务和路由**

`backend/app/schemas/category.py`：

```python
from backend.app.schemas.base import ApiModel


class CategoryItem(ApiModel):
    key: str
    news_count: int


class CategoryListResponse(ApiModel):
    items: list[CategoryItem]
```

在 `content_dao.py` 增加稳定排序查询：

```python
def list_news_categories(connection: Connection) -> list[dict[str, object]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT category AS key, COUNT(*)::BIGINT AS news_count
            FROM mind_news
            WHERE category IS NOT NULL AND category <> ''
            GROUP BY category
            ORDER BY news_count DESC, key ASC
            """
        )
        return list(cursor.fetchall())
```

在仓储协议和两个实现中增加 `list_categories() -> CategoryListResponse`；PostgreSQL 实现把 DAO 行转换为 `CategoryItem`。`ProductService.list_categories()` 只委托仓储。路由实现为：

```python
router = APIRouter(tags=["categories"])


@router.get("/categories", response_model=CategoryListResponse)
def list_categories(
    service: ProductService = Depends(get_product_service),
) -> CategoryListResponse:
    return service.list_categories()
```

在 `main.py` 使用与 `/personas` 相同的认证依赖挂载路由。

- [ ] **Step 4: 运行分类目录测试**

Run: `python -m pytest tests/test_categories_route.py -q`

Expected: `1 passed`。

- [ ] **Step 5: 提交分类目录 API**

```powershell
git add backend/app/schemas/category.py backend/app/routers/categories.py backend/app/repositories/content_dao.py backend/app/repositories/base.py backend/app/repositories/unwired.py backend/app/repositories/postgres.py backend/app/services/product.py backend/app/main.py tests/test_categories_route.py
git commit -m "feat: 新增新闻分类目录接口"
```

## Task 2：把分类纳入信息流契约、校验和幂等形状

**Files:**

- Create: `alembic/versions/20260816_0005_feed_category_filter.py`
- Modify: `backend/app/errors.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/routers/feed.py`
- Modify: `backend/app/services/feed.py`
- Modify: `backend/app/repositories/base.py`
- Modify: `backend/app/repositories/unwired.py`
- Modify: `backend/app/repositories/postgres.py`
- Modify: `backend/app/repositories/sponsored_dao.py`
- Modify: `tests/test_feed_pagination_contract.py`
- Modify: `tests/test_sponsored_postgres.py`

- [ ] **Step 1: 扩展服务转发测试**

在 `tests/test_feed_pagination_contract.py` 的服务调用中加入 `category="sports"`，并把期望调用扩展为：

```python
repository.get_feed.assert_called_once_with(
    user_id=7001,
    page_size=20,
    debug=True,
    experiment_arm="default",
    include_sponsored=True,
    request_id="feed-page-2",
    cursor="cursor-page-2",
    as_of_ts=None,
    category="sports",
)
```

新增路由测试：合法分类被转发；不存在分类返回 `422` 和 `unknown_category`；同一 `request_id` 从 `sports` 改为 `finance` 返回 `409 idempotency_conflict`。

- [ ] **Step 2: 运行测试并确认参数/迁移缺失**

Run: `python -m pytest tests/test_feed_pagination_contract.py -q`

Expected: `FeedService.get_feed() got an unexpected keyword argument 'category'`。

- [ ] **Step 3: 创建 Alembic 迁移**

迁移 `revision = "20260816_0005"`、`down_revision = "20260816_0004"`：

```python
def upgrade() -> None:
    op.add_column("feed_request", sa.Column("category", sa.String(length=64), nullable=True))
    op.create_index("ix_feed_request_category", "feed_request", ["category"])


def downgrade() -> None:
    op.drop_index("ix_feed_request_category", table_name="feed_request")
    op.drop_column("feed_request", "category")
```

- [ ] **Step 4: 贯穿可选分类参数并在生成请求前校验**

给路由、服务、仓储协议和实现的 `get_feed` 末尾加入 `category: str | None = None`。路由使用 FastAPI 查询约束阻止空串和非法字符：

```python
category: Annotated[
    str | None,
    Query(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$"),
] = None
```

在 `errors.py` 增加 `UnknownCategoryError`，包含 `category`；在 `main.py` 返回：

```python
JSONResponse(
    status_code=422,
    content={
        "detail": f"未知新闻分类：{exc.category}",
        "error_code": "unknown_category",
    },
)
```

在 PostgreSQL 仓储中先执行：

```python
if category is not None and not content_dao.news_category_exists(connection, category):
    raise UnknownCategoryError(category)
```

`news_category_exists` 使用 `SELECT EXISTS (...)` 精确匹配 `mind_news.category`。

- [ ] **Step 5: 把分类加入 feed_request 请求形状**

扩展 `claim_feed_request(..., category: str | None)` 的 SELECT、INSERT 和形状比较。比较必须使用 Python 值或 SQL `IS NOT DISTINCT FROM` 语义，使 `None` 与 `None` 相等、`None` 与具体分类冲突。插入列包含 `category`，父请求/游标续页必须与当前分类一致。

- [ ] **Step 6: 运行契约和 PostgreSQL 幂等测试**

Run: `python -m pytest tests/test_feed_pagination_contract.py -q`

Expected: all passed。

Run（有测试数据库时）: `python -m pytest -m postgres tests/test_sponsored_postgres.py -q`

Expected: 新增的分类形状冲突测试与原有测试全部通过。

- [ ] **Step 7: 提交信息流分类契约**

```powershell
git add alembic/versions/20260816_0005_feed_category_filter.py backend/app/errors.py backend/app/main.py backend/app/routers/feed.py backend/app/services/feed.py backend/app/repositories/base.py backend/app/repositories/unwired.py backend/app/repositories/postgres.py backend/app/repositories/sponsored_dao.py tests/test_feed_pagination_contract.py tests/test_sponsored_postgres.py
git commit -m "feat: 将分类绑定到信息流请求"
```

## Task 3：严格过滤所有自然候选源并保留个性化排序

**Files:**

- Modify: `backend/app/repositories/content_dao.py`
- Modify: `backend/app/repositories/postgres.py`
- Create: `tests/test_feed_category_filter.py`

- [ ] **Step 1: 写 PostgreSQL 集成测试覆盖最终结果与个性化顺序**

新增带 `pytest.mark.postgres` 的测试：请求 `category=sports&include_sponsored=false&debug=true`，断言返回项全部为 `sports`，debug 中仍有画像/查询/ALS 等召回来源或个性化分数；请求不带分类时仍可出现多个分类。再请求一个新闻稀少分类，断言即使触发兜底也不会泄漏其他分类。

核心断言：

```python
assert body["items"]
assert {item["category"] for item in body["items"]} == {"sports"}
assert any(item["scores"]["personalized_topic_score"] >= 0 for item in body["items"])
```

- [ ] **Step 2: 运行测试并确认当前实现泄漏其他分类**

Run: `python -m pytest -m postgres tests/test_feed_category_filter.py -q`

Expected: 分类集合包含非 `sports` 值，测试失败。

- [ ] **Step 3: 给 DAO 查询增加统一的可选分类约束**

新增小型内部辅助函数，避免 SQL 和参数位置分叉：

```python
def _category_clause(category: str | None, *, alias: str = "news") -> tuple[str, tuple[object, ...]]:
    if category is None:
        return "", ()
    return f" AND {alias}.category = %s", (category,)
```

将 `category` 作为仅关键字参数加入以下函数，并在 SQL 中引用实际 `mind_news` 别名：

- `load_news_ids_for_topics`
- `load_hot_fallback_rows`
- `load_exploration_rows`
- `load_unseen_catalog_rows`
- `load_news_ids_available_as_of`

把 `load_news_ids_available_as_of` 扩展为即使 `as_of_ts is None`，只要 `category` 非空也会查询 `mind_news` 并返回允许的 ID 集合。这样 ALS 候选不会绕过分类过滤。

- [ ] **Step 4: 在候选组装阶段传递分类**

给 `_load_feed_candidates` 增加 `category` 并传给画像主题召回、近期查询召回、ALS 允许集、探索、热门/新鲜兜底和未读目录补齐。最终加载新闻行后保留一个防御性断言/过滤：

```python
if category is not None:
    rows = [row for row in rows if str(row["category"]) == category]
```

该检查只是防止未来新增召回源漏传，不能替代候选阶段过滤。

- [ ] **Step 5: 验证严格过滤与无分类回归**

Run: `python -m pytest -m postgres tests/test_feed_category_filter.py tests/test_sponsored_postgres.py -q`

Expected: all passed；稀少分类不足一页时返回较短列表或 `has_more=false`，不跨分类补齐。

- [ ] **Step 6: 提交自然候选过滤**

```powershell
git add backend/app/repositories/content_dao.py backend/app/repositories/postgres.py tests/test_feed_category_filter.py
git commit -m "feat: 按分类约束个性化候选召回"
```

## Task 4：严格过滤广告候选

**Files:**

- Modify: `backend/app/repositories/sponsored_dao.py`
- Modify: `backend/app/repositories/postgres.py`
- Modify: `tests/test_sponsored.py`
- Modify: `tests/test_sponsored_postgres.py`

- [ ] **Step 1: 写失败的广告分类测试**

在 DAO 单元测试中验证带分类时 SQL 参数包含分类；在 PostgreSQL 集成测试中为一个与请求分类不同的创意发送 `/feed?category=sports`，断言所有 `content_type == "sponsored"` 的条目也属于 `sports`。

- [ ] **Step 2: 运行广告测试并确认过滤缺失**

Run: `python -m pytest tests/test_sponsored.py -q`

Expected: `load_sponsored_candidates` 不接受 `category` 或生成 SQL 不含分类条件。

- [ ] **Step 3: 实现广告候选分类约束**

给 `load_sponsored_candidates` 增加 `category: str | None = None`。查询中加入：

```sql
JOIN mind_news AS news ON news.news_id = creative.news_id
```

并在有分类时追加 `AND news.category = %s`。从 `PostgresRuntimeRepository.get_feed` 的广告混排调用传入当前 `category`。已保存投放的幂等重放沿用同一 `feed_request.category`，无需重选广告。

- [ ] **Step 4: 运行广告和信息流测试**

Run: `python -m pytest tests/test_sponsored.py tests/test_feed_pagination_contract.py -q`

Expected: all passed。

Run（有测试数据库时）: `python -m pytest -m postgres tests/test_sponsored_postgres.py tests/test_feed_category_filter.py -q`

Expected: all passed，分类信息流中广告与自然内容均不越界。

- [ ] **Step 5: 提交广告过滤**

```powershell
git add backend/app/repositories/sponsored_dao.py backend/app/repositories/postgres.py tests/test_sponsored.py tests/test_sponsored_postgres.py
git commit -m "feat: 按分类过滤广告候选"
```

## Task 5：接入前端分类目录并实现左侧独立滚动列表

**Files:**

- Modify: `product-frontend/src/api/types.ts`
- Modify: `product-frontend/src/api/client.ts`
- Modify: `product-frontend/src/localization.ts`
- Modify: `product-frontend/src/components/LeftSidebar.tsx`
- Create: `product-frontend/src/components/LeftSidebar.test.tsx`
- Modify: `product-frontend/src/styles/global.css`

- [ ] **Step 1: 写左侧分类列表失败测试**

Mock `listCategories` 返回 18 项，用 `MemoryRouter initialEntries={["/?category=sports"]}` 渲染。断言：

```tsx
expect(await screen.findByRole("link", { name: "体育" })).toHaveAttribute(
  "aria-current",
  "page",
);
expect(screen.getByRole("link", { name: "全部新闻" })).toHaveAttribute("href", "/");
expect(screen.getAllByTestId("news-category-link")).toHaveLength(18);
expect(screen.queryByText("science")).not.toBeInTheDocument();
```

同时测试接口失败时仍显示“全部新闻”和中文重试入口。

- [ ] **Step 2: 运行测试并确认硬编码三分类导致失败**

Run: `npm test -- LeftSidebar.test.tsx`

Workdir: `product-frontend`

Expected: 找不到 18 个分类链接或 `listCategories` 导出。

- [ ] **Step 3: 增加分类 API 类型和客户端方法**

`types.ts`：

```typescript
export interface CategoryItem {
  key: string;
  news_count: number;
}

export interface CategoryListResponse {
  items: CategoryItem[];
}
```

`client.ts`：

```typescript
export function listCategories(): Promise<CategoryListResponse> {
  return request<CategoryListResponse>("/categories");
}
```

在 `localization.ts` 的分类映射补齐精确键 `games: "游戏"`，并确保 18 个原始键都有中文；未知键继续使用已有的人类可读兜底，不直接破坏页面。

- [ ] **Step 4: 将 LeftSidebar 改成后端目录驱动**

组件加载分类后按接口顺序渲染，不在前端重新排序或截断。使用 `useLocation()` 解析 `category`，链接规则固定：

```tsx
const selectedCategory = new URLSearchParams(location.search).get("category");

<Link to="/" aria-current={selectedCategory === null ? "page" : undefined}>
  全部新闻
</Link>

{categories.map((category) => (
  <Link
    key={category.key}
    data-testid="news-category-link"
    to={`/?category=${encodeURIComponent(category.key)}`}
    aria-current={selectedCategory === category.key ? "page" : undefined}
  >
    {localizeCategoryName(category.key)}
  </Link>
))}
```

保留现有首页、搜索、兴趣画像结构与中文界面。加载失败显示“分类加载失败”和“重新加载”，不移除“全部新闻”。

- [ ] **Step 5: 实现单列独立滚动和选中态**

在 `global.css` 增加/调整：

```css
.zr-left__section--categories {
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.zr-left__category-list {
  max-height: min(52vh, 520px);
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.zr-left__item[aria-current="page"] {
  color: var(--color-accent);
  background: var(--color-accent-soft);
  font-weight: 650;
}
```

不要让整个左侧栏跟随主内容滚动，也不要改成双列或折叠菜单。

- [ ] **Step 6: 运行组件测试与类型构建**

Run: `npm test -- LeftSidebar.test.tsx`

Workdir: `product-frontend`

Expected: all passed。

Run: `npm run build`

Expected: TypeScript 和 Vite 构建成功。

- [ ] **Step 7: 提交左侧分类 UI**

```powershell
git add product-frontend/src/api/types.ts product-frontend/src/api/client.ts product-frontend/src/localization.ts product-frontend/src/components/LeftSidebar.tsx product-frontend/src/components/LeftSidebar.test.tsx product-frontend/src/styles/global.css
git commit -m "feat: 展示中文新闻分类侧栏"
```

## Task 6：让 FeedPage 使用 URL 分类并隔离分类会话

**Files:**

- Modify: `product-frontend/src/api/client.ts`
- Modify: `product-frontend/src/pages/FeedPage.tsx`
- Modify: `product-frontend/src/pages/FeedPage.test.tsx`

- [ ] **Step 1: 扩展客户端和首屏分类测试**

给测试中的 `useLocation` mock 增加可变 `search`。在 `?category=sports` 下断言：

```typescript
expect(getFeed).toHaveBeenCalledWith(
  7248,
  20,
  true,
  "feed-load-test",
  undefined,
  "sports",
);
expect(screen.getByRole("heading", { name: "体育新闻" })).toBeInTheDocument();
```

并更新现有下一页断言，确保游标请求继续传 `sports`。

- [ ] **Step 2: 写分类切换迟到响应测试**

先让 `sports` 请求保持 pending，再把 mock location 改为 `?category=finance` 并 rerender；先解析 finance，再解析 sports。最终只应展示 finance 返回项：

```typescript
expect(screen.getByTestId("article-FIN-1")).toBeInTheDocument();
expect(screen.queryByTestId("article-SPORT-1")).not.toBeInTheDocument();
```

同时断言两个初始请求使用不同的稳定逻辑键，分类切换清空旧游标与已加载项目。

- [ ] **Step 3: 运行 FeedPage 测试并确认分类未传递**

Run: `npm test -- FeedPage.test.tsx`

Workdir: `product-frontend`

Expected: `getFeed` 的第六个参数缺失，切换测试失败。

- [ ] **Step 4: 扩展 getFeed 客户端函数**

保持已有调用兼容，在末尾追加分类：

```typescript
export function getFeed(
  userId: number,
  pageSize = 10,
  debug = false,
  requestId?: string,
  cursor?: string,
  category?: string,
): Promise<FeedResponse> {
  return request<FeedResponse>("/feed", {
    params: {
      user_id: userId,
      page_size: pageSize,
      debug,
      request_id: requestId,
      cursor,
      category,
    },
  });
}
```

- [ ] **Step 5: 在 FeedPage 建立分类作用域会话**

从 `location.search` 解析分类，并把分类纳入所有身份/依赖：

```typescript
const category = new URLSearchParams(location.search).get("category") ?? undefined;
const feedScope = `${selectedPersona.user_id}:${refreshTick}:${category ?? "all"}`;
const initialRequestId = stableClientId("feed-load", feedScope);
```

初始加载和下一页均把 `category` 传给 `getFeed`。现有请求序号/active session ref 必须以 `feedScope` 为准；effect 清理函数使旧分类请求变为无效，任何迟到响应在 setState 前检查 scope。分类变化时重置：items、cursor、hasMore、错误、已记录曝光集合和当前 request id。

标题使用 `category ? `${localizeCategoryName(category)}新闻` : "为你推荐"`；副标题说明分类内仍按阅读兴趣推荐。

- [ ] **Step 6: 增加无效分类错误态**

当 `ApiError.status === 422` 时显示“该新闻分类不存在或已不可用”，并提供 `<Link to="/">查看全部新闻</Link>`；其他错误沿用当前中文错误和重试行为。不要静默退回全部新闻，以免用户误以为仍在所选分类。

- [ ] **Step 7: 运行前端全套测试与构建**

Run: `npm test`

Workdir: `product-frontend`

Expected: all passed。

Run: `npm run build`

Expected: `tsc -b && vite build` 成功。

- [ ] **Step 8: 提交分类信息流页面**

```powershell
git add product-frontend/src/api/client.ts product-frontend/src/pages/FeedPage.tsx product-frontend/src/pages/FeedPage.test.tsx
git commit -m "feat: 支持按分类浏览个性化信息流"
```

## Task 7：完整验证和浏览器验收

**Files:**

- Modify only if verification exposes a scoped defect.

- [ ] **Step 1: 运行后端快速测试、静态检查和迁移检查**

```powershell
python -m pytest -q
python -m ruff check backend tests
python -m mypy backend/app
python -m alembic heads
```

Expected: pytest 全绿；Ruff、mypy 无错误；Alembic 只有 `20260816_0005` 一个 head。

- [ ] **Step 2: 在配置了 PostgreSQL 的环境运行集成测试和迁移**

```powershell
python -m alembic upgrade head
python -m pytest -m postgres tests/test_feed_category_filter.py tests/test_sponsored_postgres.py -q
```

Expected: 迁移成功，分类严格过滤、广告过滤、幂等冲突全部通过。

- [ ] **Step 3: 运行前端验证**

```powershell
Set-Location product-frontend
npm test
npm run build
```

Expected: Vitest 全绿，生产构建成功。

- [ ] **Step 4: 在本地浏览器执行可见验收**

启动现有前后端后检查：左侧显示“全部新闻 + 18 个一级分类”；分类区单列独立滚动；选中项高亮；URL 形如 `/?category=sports`；切换分类立即清空旧列表；连续翻页始终只有该分类；新闻标题/正文可以保留英文，所有按钮、状态、结构文案均为中文；刷新后保持当前分类。

- [ ] **Step 5: 检查差异只包含本需求文件**

Run: `git status --short` and `git diff --check`

Expected: 无空白错误；不覆盖用户原有无关修改。

- [ ] **Step 6: 提交仅由验收发现的修正（如有）**

```powershell
git add -p
git commit -m "fix: 完善分类信息流验收细节"
```

若无需修正，不创建空提交。

## 完成标准

- `/categories` 从数据库返回恰好 18 个一级分类，键值保持英文原始值，界面显示中文。
- `/feed` 不带分类时行为不变；带分类时自然候选、ALS、探索、所有兜底和广告均严格匹配分类。
- 个性化画像和现有打分排序继续在分类候选集合内生效。
- 分类参与请求幂等和游标会话；分类不一致不会复用旧请求。
- 左侧为“全部新闻 + 18 类”的单列独立滚动列表，活动项明确，URL 可分享和刷新恢复。
- 分类切换不会混入旧请求迟到响应，分页不会跨分类。
- 后端测试、前端测试、静态检查、构建和浏览器验收全部通过。
