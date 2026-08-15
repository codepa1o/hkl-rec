# MIND News Hard Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy question/answer content model with an exact eight-field `mind_news` source of truth, migrate every product boundary to string `news_id`, load all 65,238 MIND-small articles into PostgreSQL, and serve full-corpus search and recommendation.

**Architecture:** PostgreSQL stores exact MIND news facts in `mind_news`, train-only derived popularity in `mind_news_stats`, and import provenance in `mind_catalog_import`. Runtime APIs, events, sponsored content, search, feed, and frontend use `news_id`; model artifacts may retain internal integers only behind a fingerprint-checked mapping. A direct PostgreSQL bulk importer replaces the legacy MySQL/demo SQL path.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, psycopg, Alembic, PostgreSQL 16, PyArrow/Parquet, FAISS, LightGBM/implicit ALS, React, TypeScript, Vitest, Pytest.

---

## File map

- `alembic/versions/20260815_0002_mind_news_hard_cutover.py`: transactional schema/data migration and legacy table removal.
- `backend/app/db/schema.py`: final SQLAlchemy metadata used by schema parity tests.
- `backend/app/data_contracts/mind.py`: exact `news_id` parsing and MIND row contract.
- `scripts/import_mind_catalog.py`: direct PostgreSQL full-catalog bulk importer.
- `backend/app/repositories/content_dao.py`: all news, topic, search, hotness, and exploration SQL.
- `backend/app/repositories/postgres.py`: feed/search/detail orchestration using `news_id`.
- `backend/app/repositories/{base,unwired,_utils,als_recall,mmr,event_dao,sponsored,sponsored_dao,query_resolver}.py`: repository contracts and supporting paths migrated to `news_id`.
- `backend/app/schemas/{article,feed,search,event,event_track,profile}.py`: public contracts migrated to `news_id: str`.
- `backend/app/events/{schema,consumer}.py`: Kafka/event payload migration.
- `backend/app/search_retrieval.py`, `scripts/build_search_index.py`: full-corpus search artifacts keyed by `news_id`.
- `backend/app/config.py`, `.env.example`, `scripts/init_local.{ps1,sh}`: full-index configuration and direct import workflow.
- `product-frontend/src/api/{types,client}.ts` and article/feed/search components/pages: `newsId` hard cutover.
- `tests/`: unit, schema, import, repository, event, search, and integration coverage.
- `.github/workflows/ci.yml`: PostgreSQL-only integration path.
- `README.md`, `docs/local_runbook.md`, `docs/api_contract.md`: new data and operational contract.
- Remove legacy `sql/schema.sql`, `scripts/import_demo_world.py`, `scripts/apply_demo_mysql.py`, `scripts/migrate_mysql_to_postgres.py`, and MySQL-only integration tests/config once no runtime reference remains.

### Task 1: Lock the exact MIND news contract

**Files:**
- Modify: `backend/app/data_contracts/mind.py`
- Create: `tests/test_mind_news_contract.py`

- [ ] **Step 1: Write failing contract tests**

```python
def test_news_id_round_trips_without_integer_coercion():
    article = parse_news_row("N123\tnews\tlocal\tTitle\t\thttps://example.com\t[]\t[]")
    assert article.news_id == "N123"
    assert article.abstract == ""
    assert article.title_entities == []

def test_entities_must_be_json_arrays():
    with pytest.raises(MindContractError, match="array"):
        parse_news_row("N1\tnews\tlocal\tTitle\tA\thttps://example.com\t{}\t[]")
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/test_mind_news_contract.py -q`  
Expected: FAIL because `MindArticle.news_id` currently exposes an integer-derived identity and entity arrays are stored as strings.

- [ ] **Step 3: Implement the exact contract**

```python
@dataclass(frozen=True)
class MindNews:
    news_id: str
    category: str
    subcategory: str
    title: str
    abstract: str
    url: str
    title_entities: list[dict[str, object]]
    abstract_entities: list[dict[str, object]]
```

Keep `parse_news_id()` as strict string validation. Add a separate `news_internal_id()` helper only for offline artifact mapping.

- [ ] **Step 4: Verify pass**

Run: `python -m pytest tests/test_mind_news_contract.py tests/test_normalize_mind.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/data_contracts/mind.py tests/test_mind_news_contract.py tests/test_normalize_mind.py
git commit -m "refactor: preserve canonical MIND news identifiers"
```

### Task 2: Add the PostgreSQL hard-cutover schema

**Files:**
- Create: `alembic/versions/20260815_0002_mind_news_hard_cutover.py`
- Modify: `backend/app/db/schema.py`
- Modify: `tests/test_alembic_schema.py`

- [ ] **Step 1: Write failing schema assertions**

Assert that `mind_news` has exactly the eight MIND business columns, that auxiliary tables exist, that event/sponsored tables contain `news_id`, and that all six legacy content tables are absent.

```python
assert business_columns("mind_news") == {
    "news_id", "category", "subcategory", "title", "abstract", "url",
    "title_entities", "abstract_entities",
}
for legacy in ("question", "answer", "author", "question_topic", "answer_topic", "hot_answer_snapshot"):
    assert legacy not in inspector.get_table_names()
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/test_alembic_schema.py -q`  
Expected: FAIL because only the legacy baseline exists.

- [ ] **Step 3: Implement migration and metadata**

Create `mind_news`, `mind_news_stats`, and `mind_catalog_import`; add and backfill `news_id` on referencing tables; migrate existing numeric IDs to `N<digits>`; replace foreign keys; then drop legacy columns/tables in dependency order. Use JSONB array checks and a regex check on `news_id`.

- [ ] **Step 4: Verify upgrade and parity**

Run: `python -m pytest tests/test_alembic_schema.py -q`  
Expected: PASS on an empty PostgreSQL database and metadata parity.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/20260815_0002_mind_news_hard_cutover.py backend/app/db/schema.py tests/test_alembic_schema.py
git commit -m "feat: add canonical MIND news schema"
```

### Task 3: Build the direct PostgreSQL full-catalog importer

**Files:**
- Create: `scripts/import_mind_catalog.py`
- Create: `tests/test_import_mind_catalog.py`
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Write importer tests**

Cover exact news values, train-only aggregation, duplicate train/dev metadata validation, invalid JSON rejection, fingerprint recording, idempotent reruns, preservation of `user_event`, and transaction rollback.

```python
result = import_catalog(normalized_root, connection)
assert result.news_rows == 3
assert result.stats_rows == 3
assert fetch_scalar(connection, "SELECT COUNT(*) FROM user_event") == event_count_before
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/test_import_mind_catalog.py -q`  
Expected: FAIL because the importer module does not exist.

- [ ] **Step 3: Implement bounded-memory staging and upsert**

Read Parquet in batches, reverse `id_maps.json`, aggregate train impressions, parse entity JSON, `COPY` rows into temporary staging tables, validate counts, and upsert in one transaction. Require database name `newsrec_demo` or a name ending `_test`; require `--replace-catalog` when the stored fingerprint differs.

- [ ] **Step 4: Verify importer tests**

Run: `python -m pytest tests/test_import_mind_catalog.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/import_mind_catalog.py tests/test_import_mind_catalog.py backend/requirements.txt
git commit -m "feat: import full MIND catalog into PostgreSQL"
```

### Task 4: Replace content DAO SQL with `mind_news`

**Files:**
- Rewrite: `backend/app/repositories/content_dao.py`
- Modify: `backend/app/repositories/query_resolver.py`
- Modify: `tests/test_search_candidates.py`
- Modify: `tests/test_content_as_of_postgres.py`
- Create: `tests/test_mind_news_dao.py`

- [ ] **Step 1: Write failing DAO tests**

Test batch news loading, category/subcategory recall, train-stat hot fallback, lexical lookup, and a deterministic exploration bucket that can select zero-stat news.

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/test_mind_news_dao.py tests/test_search_candidates.py -q`  
Expected: FAIL on legacy `answer` SQL.

- [ ] **Step 3: Implement new DAO functions**

```python
def load_news_rows(connection: Any, news_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not news_ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT n.news_id, n.title, n.abstract, n.url, n.category, n.subcategory,
                   s.hot_score, s.click_count, s.impression_count, s.first_seen_ts
            FROM mind_news n
            JOIN mind_news_stats s USING (news_id)
            WHERE n.news_id = ANY(%s)
            """,
            (news_ids,),
        )
        return {str(row["news_id"]): row for row in cursor.fetchall()}

def load_news_ids_for_topics(
    connection: Any, topic_ids: list[int], limit: int
) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT n.news_id, s.hot_score
            FROM mind_news n
            JOIN mind_news_stats s USING (news_id)
            JOIN topic t ON t.topic_id = ANY(%s)
              AND LOWER(t.display_name) IN (LOWER(n.category), LOWER(n.subcategory))
            ORDER BY s.hot_score DESC, n.news_id
            LIMIT %s
            """,
            (topic_ids, limit),
        )
        return list(cursor.fetchall())

def load_catalog_exploration(
    connection: Any, topic_ids: list[int], bucket: int, limit: int
) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT n.news_id, s.hot_score
            FROM mind_news n
            JOIN mind_news_stats s USING (news_id)
            JOIN topic t ON t.topic_id = ANY(%s)
              AND LOWER(t.display_name) IN (LOWER(n.category), LOWER(n.subcategory))
            WHERE MOD(('x' || SUBSTR(MD5(n.news_id), 1, 8))::bit(32)::bigint, 64) = %s
            ORDER BY n.news_id
            LIMIT %s
            """,
            (topic_ids, bucket, limit),
        )
        return list(cursor.fetchall())
```

Resolve profile topic IDs through `topic.display_name` and indexed `mind_news.category/subcategory`. Eliminate all SQL references to old content tables.

- [ ] **Step 4: Verify DAO tests**

Run: `python -m pytest tests/test_mind_news_dao.py tests/test_search_candidates.py tests/test_content_as_of_postgres.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/repositories/content_dao.py backend/app/repositories/query_resolver.py tests/test_mind_news_dao.py tests/test_search_candidates.py tests/test_content_as_of_postgres.py
git commit -m "refactor: query canonical MIND news content"
```

### Task 5: Hard-cut repository and public schemas to `news_id`

**Files:**
- Modify: `backend/app/repositories/{base,unwired,postgres,_utils,mmr}.py`
- Modify: `backend/app/services/product.py`
- Modify: `backend/app/routers/articles.py`
- Modify: `backend/app/schemas/{article,feed,search,event,event_track,profile}.py`
- Modify: `tests/test_{unwired_contract,article_card_route,search_route,event_track_route,mmr}.py`

- [ ] **Step 1: Change tests to require string IDs and fail on legacy output**

```python
assert response.json()["news_id"] == "N123"
assert client.get("/articles/N123").status_code == 200
assert "article_id" not in response.json()
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/test_unwired_contract.py tests/test_article_card_route.py tests/test_search_route.py tests/test_event_track_route.py tests/test_mmr.py -q`  
Expected: FAIL while contracts expose integer `article_id`.

- [ ] **Step 3: Implement repository and schema cutover**

Rename public fields and internal content keys to `news_id: str`; make `/articles/{news_id}` strict; batch-load from `mind_news`; preserve external response semantics for headline/abstract/source/category.

- [ ] **Step 4: Verify repository/API tests**

Run the same test command.  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/repositories backend/app/services/product.py backend/app/routers/articles.py backend/app/schemas tests
git commit -m "refactor: expose news identifiers across runtime APIs"
```

### Task 6: Migrate events, Outbox, Kafka, and sponsored content

**Files:**
- Modify: `backend/app/events/{schema,consumer}.py`
- Modify: `backend/app/repositories/{event_dao,sponsored,sponsored_dao,postgres}.py`
- Modify: `tests/test_{event_stream,kafka_integration,sponsored,sponsored_postgres}.py`

- [ ] **Step 1: Write failing string-ID event tests**

Test v3 payload creation with `news_id`, rejection of legacy v2 content at the hard-cut boundary, idempotency fingerprints, sponsored attribution, and profile recent-click storage.

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/test_event_stream.py tests/test_sponsored.py -q`  
Expected: FAIL on `answer_id`/integer fields.

- [ ] **Step 3: Implement v4 event schema**

Use `news_id: str | None` throughout; compute fingerprints from the canonical string; update all SQL columns and JSON debug payloads; ensure online profile updates resolve category/subcategory from `mind_news`.

- [ ] **Step 4: Verify event and sponsored suites**

Run: `python -m pytest tests/test_event_stream.py tests/test_sponsored.py tests/test_sponsored_postgres.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/events backend/app/repositories/event_dao.py backend/app/repositories/sponsored.py backend/app/repositories/sponsored_dao.py backend/app/repositories/postgres.py tests
git commit -m "refactor: key online events by MIND news id"
```

### Task 7: Migrate full search artifacts and runtime configuration

**Files:**
- Modify: `backend/app/search_retrieval.py`
- Modify: `scripts/build_search_index.py`
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Modify: `tests/test_{search_artifacts,search_retrieval,config,health}.py`

- [ ] **Step 1: Write failing full-index tests**

Require `SearchDocument.news_id`, `news_id_map.json`, explicit source fingerprint override, and readiness metadata count/fingerprint validation.

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/test_search_artifacts.py tests/test_search_retrieval.py tests/test_config.py tests/test_health.py -q`  
Expected: FAIL on integer artifact IDs and demo-derived fingerprint.

- [ ] **Step 3: Implement artifact/config cutover**

Build full documents from `articles.parquet.news_id`; change runtime default to `build/mind_search/full`; add `NEWSREC_SEARCH_SOURCE_FINGERPRINT`; return `news_id` hits.

- [ ] **Step 4: Verify search tests**

Run the same command.  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/search_retrieval.py scripts/build_search_index.py backend/app/config.py .env.example tests
git commit -m "feat: serve the full MIND search corpus"
```

### Task 8: Preserve ALS/LightGBM internal mapping behind the boundary

**Files:**
- Modify: `backend/app/repositories/{als_recall,ranker,postgres}.py`
- Modify: `scripts/train_eval_mind.py`
- Modify: `tests/test_{als_recall,train_eval_mind}.py`

- [ ] **Step 1: Write mapping and mismatch tests**

Require model metadata to carry a normalized fingerprint plus both mapping directions; reject an artifact whose fingerprint differs from the imported catalog.

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/test_als_recall.py tests/test_train_eval_mind.py -q`  
Expected: FAIL because runtime candidates currently expose integers directly.

- [ ] **Step 3: Implement mapping boundary**

Return `tuple[tuple[str, float], ...]` from online ALS recall after converting internal IDs to `news_id`; keep training matrices integer-indexed; make ranker features use news stats loaded by string ID.

- [ ] **Step 4: Verify model tests**

Run the same command.  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/repositories/als_recall.py backend/app/repositories/ranker.py backend/app/repositories/postgres.py scripts/train_eval_mind.py tests
git commit -m "refactor: isolate model ids from canonical news ids"
```

### Task 9: Cut the React product to `newsId`

**Files:**
- Modify: `product-frontend/src/api/{types,client}.ts`
- Modify: `product-frontend/src/components/{PostCard,VoteActions,ProfileDebugPanel}.tsx`
- Modify: `product-frontend/src/pages/{FeedPage,SearchPage,ArticleDetailPage}.tsx`
- Modify: corresponding `*.test.tsx`

- [ ] **Step 1: Update tests to require `newsId` and `/articles/N…` routes**

- [ ] **Step 2: Verify failure**

Run: `npm test -- --run` in `product-frontend`  
Expected: FAIL while components require numeric `articleId`.

- [ ] **Step 3: Implement TypeScript hard cutover**

Use `newsId: string`; remove `articleId`; update event bodies, keys, routes, labels, and debug rendering.

- [ ] **Step 4: Verify frontend**

Run: `npm test -- --run && npm run build` in `product-frontend`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add product-frontend/src
git commit -m "refactor: use MIND news ids in the frontend"
```

### Task 10: Remove the legacy MySQL/demo content pipeline

**Files:**
- Remove: `sql/schema.sql`
- Remove: `scripts/{import_demo_world,apply_demo_mysql,migrate_mysql_to_postgres}.py`
- Remove or rewrite: `backend/app/db/migration.py`
- Modify: `scripts/build_mind_demo_world.py`
- Modify: `scripts/mind_demo_pack.py`
- Modify: `scripts/reset_demo_user.py`
- Modify: `scripts/init_local.{ps1,sh}`
- Modify: `.github/workflows/ci.yml`
- Remove/replace: `tests/test_mysql_to_postgres_migration.py`, legacy demo import assertions

- [ ] **Step 1: Add a repository-wide forbidden-symbol test**

Reject executable runtime references to legacy content tables and public identifiers while allowing migration-history comments only.

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/test_unwired_contract.py -q`  
Expected: FAIL with listed legacy references.

- [ ] **Step 3: Remove obsolete paths and switch CI/init**

CI starts PostgreSQL, runs Alembic, builds the deterministic fixture/normalized data, imports via `import_mind_catalog.py`, builds full search artifacts, and runs integration tests. Local init follows the same order.

- [ ] **Step 4: Verify no executable legacy references**

Run: `rg -n "answer_id|question_id|answer_topic|hot_answer_snapshot|apply_demo_mysql|migrate_mysql_to_postgres" backend scripts tests product-frontend .github`  
Expected: no matches except explicitly approved historical migration text.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove legacy content and MySQL runtime paths"
```

### Task 11: Update documentation and operational commands

**Files:**
- Modify: `README.md`
- Modify: `docs/{local_runbook,api_contract,metrics}.md`
- Modify: `backend/README.md`

- [ ] **Step 1: Replace old schema/import/API documentation**

Document the exact eight fields, direct PostgreSQL import, full search build, `news_id` endpoints, Parquet behavior boundary, and destructive migration backup requirement.

- [ ] **Step 2: Scan docs for contradictory active guidance**

Run: `rg -n "MySQL is|answer_id|question_id|import_demo_world|mind_search/demo" README.md docs backend/README.md`  
Expected: no active runtime instruction uses the old model.

- [ ] **Step 3: Commit**

```bash
git add README.md docs backend/README.md
git commit -m "docs: document canonical MIND news operations"
```

### Task 12: Run complete static and unit verification

**Files:** none beyond fixes required by failures.

- [ ] **Step 1: Python quality gates**

Run:

```bash
python -m ruff check backend scripts tests
python -m mypy
python -m pytest -q -m "not postgres and not kafka"
```

Expected: zero Ruff errors, zero Mypy errors, all selected tests pass.

- [ ] **Step 2: Frontend gates**

Run in `product-frontend`:

```bash
npm test -- --run
npm run build
```

Expected: all tests and TypeScript production build pass.

- [ ] **Step 3: Fix only failures caused by this migration and rerun the full commands**

- [ ] **Step 4: Commit verification fixes if any**

```bash
git add -A
git commit -m "test: complete MIND news cutover verification"
```

### Task 13: Apply to the local PostgreSQL and import all MIND-small news

**Files/data:**
- Read: `build/mind_normalized/*`
- Write: local PostgreSQL `newsrec_demo`
- Write: `build/mind_search/full/*`

- [ ] **Step 1: Resolve and verify the exact destructive target**

Run `docker compose ps`, inspect `NEWSREC_DATABASE_URL` without printing passwords, and query `current_database()`, `inet_server_addr()`, and current table counts. Require local host, port 5432, and database `newsrec_demo`.

- [ ] **Step 2: Create a recoverable database backup**

Run `pg_dump` inside the PostgreSQL container to a timestamped file under `build/backups/` and verify the dump is non-empty.

- [ ] **Step 3: Apply Alembic**

Run: `python -m alembic upgrade head`  
Expected: current revision is `20260815_0002`; new tables exist and legacy tables do not.

- [ ] **Step 4: Import the full catalog**

Run:

```bash
python scripts/import_mind_catalog.py \
  --normalized-root build/mind_normalized \
  --replace-catalog
```

Expected: `news_rows=65238`, `stats_rows=65238`, fingerprint `a0144602f29ee9e07f91d4a67eca0cda5e2ee016f910a62a4a75aeae072f2e9d`.

- [ ] **Step 5: Build the full search index**

Run:

```bash
python scripts/build_search_index.py \
  --corpus full \
  --model-revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
  --config evaluation/search_relevance/selected_config.json
```

Expected: metadata `document_count=65238` and the same source fingerprint.

- [ ] **Step 6: Run PostgreSQL integration and smoke tests**

Run:

```bash
python -m pytest -q -m "postgres and not kafka"
python scripts/smoke_local.py --base-url http://127.0.0.1:8000
```

Expected: all integration tests pass; search, feed, article detail, profile, and event smoke checks succeed.

- [ ] **Step 7: Query final invariants**

Verify 65,238 news/stats rows, JSON array constraints, zero orphan foreign keys, full-index count, access to train/dev-only/non-demo news, non-demo search/feed results, unchanged online event count across a second idempotent catalog import, and absence of all legacy tables.

- [ ] **Step 8: Record final verification evidence**

Save only non-sensitive counts, fingerprints, durations, and test summaries in the final response; do not commit generated MIND data, search indexes, dumps, or credentials.
