# Live News Body Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich allowlisted Live news asynchronously with policy-approved normalized body text and render it safely on the internal article detail page with reliable metadata-only fallback.

**Architecture:** Extend each source policy with one content mode, enqueue one durable PostgreSQL content job per eligible Live article, and run a separate worker that selects an official API, RSS, or allowlisted HTML provider. Providers return normalized acquisition results; only the worker persists state. Article API requests remain local database reads and the frontend renders plain text paragraphs without provider HTML.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3, PostgreSQL/Alembic, Trafilatura, urllib/XML parsing, Prometheus client, React 18, TypeScript, Vitest, pytest.

---

## Execution Constraints

The feature depends on the current uncommitted Live V1 implementation. The working tree already contains overlapping user changes, so execution must not stage, commit, reset, stash, or rewrite unrelated files. Verification checkpoints replace per-task commits until the existing V1 work is safely committed by its owner. New files may remain untracked during execution.

## File Map

### New backend files

- `backend/app/live_news/content_policy.py`: validated source content modes and rights.
- `backend/app/live_news/content_types.py`: provider, job, outcome, and failure types.
- `backend/app/live_news/content_normalize.py`: provider-neutral body normalization and quality checks.
- `backend/app/live_news/content_fetch.py`: bounded HTTPS client, redirect validation, IP safety, response limits.
- `backend/app/live_news/content_providers.py`: Guardian, RSS, and HTML provider implementations.
- `backend/app/live_news/content_dao.py`: durable job claiming, retries, stale recovery, and atomic body persistence.
- `backend/app/live_news/content_worker.py`: orchestration loop and failure classification.
- `scripts/run_live_news_content_worker.py`: standalone worker entry point.
- `alembic/versions/20260818_0010_live_news_body_content.py`: content columns and job table.

### Modified backend files

- `backend/app/live_news/allowlist.py`: attach validated `ContentPolicy` to each source.
- `backend/app/live_news/dao.py`: create or refresh eligible content jobs in the metadata transaction.
- `backend/app/live_news/types.py`: carry source policy data only where ingestion needs it.
- `backend/app/config.py`: content worker and fetch bounds.
- `backend/app/db/schema.py`: SQLAlchemy metadata mirror.
- `backend/app/schemas/article.py`: body status/source/rights API fields.
- `backend/app/news_spaces/live.py`: return body fields under rights rules.
- `backend/app/repositories/postgres.py`: preserve source-neutral article contract.
- `backend/app/observability.py`: bounded body acquisition metrics.
- `backend/app/health.py`: optional degraded worker readiness.
- `.env.example`: documented worker configuration.
- `backend/requirements.txt`: pin Trafilatura.
- `config/live_news_sources.json`: explicit content policies.

### Modified frontend files

- `product-frontend/src/api/types.ts`: article body contract.
- `product-frontend/src/pages/ArticleDetailPage.tsx`: safe paragraph rendering and fallback states.
- `product-frontend/src/styles/liveNews.css`: readable article body typography.

### Tests

- `tests/test_live_news_content_policy.py`
- `tests/test_live_news_content_normalize.py`
- `tests/test_live_news_content_fetch.py`
- `tests/test_live_news_content_providers.py`
- `tests/test_live_news_content_dao.py`
- `tests/test_live_news_content_worker.py`
- `tests/test_live_news_body_routes.py`
- `tests/test_dual_space_schema.py`
- `tests/test_health.py`
- `product-frontend/src/pages/ArticleDetailPage.body.test.tsx`

## Task 1: Content Policy Contract

**Files:**
- Create: `backend/app/live_news/content_policy.py`
- Modify: `backend/app/live_news/allowlist.py`
- Modify: `config/live_news_sources.json`
- Test: `tests/test_live_news_content_policy.py`

- [ ] **Step 1: Write failing policy tests**

```python
def test_load_allowlist_parses_html_content_policy(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": [{
        "domain": "example.com",
        "languages": ["en"],
        "quality_weight": 0.8,
        "content": {"mode": "html", "display": "full_text", "feed_urls": []},
    }]}), encoding="utf-8")
    policy = load_allowlist(path).match("www.example.com").content
    assert policy.mode == "html"
    assert policy.display == "full_text"


@pytest.mark.parametrize("content", [
    {"mode": "rss", "display": "full_text", "feed_urls": []},
    {"mode": "rss", "display": "full_text", "feed_urls": ["http://example.com/feed"]},
    {"mode": "link_only", "display": "full_text", "feed_urls": []},
])
def test_invalid_content_policy_fails_fast(tmp_path, content):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": [{
        "domain": "example.com",
        "languages": ["en"],
        "quality_weight": 0.8,
        "content": content,
    }]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_allowlist(path)
```

- [ ] **Step 2: Run tests and confirm contract failure**

Run: `python -m pytest tests/test_live_news_content_policy.py -q`

Expected: collection or assertion failure because `ContentPolicy` and `SourcePolicy.content` do not exist.

- [ ] **Step 3: Implement immutable policy types and parser**

```python
ContentMode = Literal["guardian_api", "rss", "html", "link_only"]
ContentRights = Literal["full_text", "excerpt_only", "link_only"]

@dataclass(frozen=True)
class ContentPolicy:
    mode: ContentMode
    display: ContentRights
    feed_urls: Sequence[str] = ()

    def __post_init__(self) -> None:
        if self.mode == "rss" and not self.feed_urls:
            raise ValueError("rss content mode requires feed_urls")
        if any(urlsplit(url).scheme != "https" for url in self.feed_urls):
            raise ValueError("content feed URLs must use HTTPS")
        if self.mode == "link_only" and self.display != "link_only":
            raise ValueError("link_only mode requires link_only display")
```

Default any source without a `content` object to `ContentPolicy("link_only", "link_only")` so existing configurations remain safe.

- [ ] **Step 4: Assign explicit policies to the current source list**

Use `guardian_api/full_text` for `theguardian.com`. Keep every other source `link_only/link_only` initially; HTML or RSS is enabled only after a tested source-specific decision.

- [ ] **Step 5: Run policy and existing allowlist tests**

Run: `python -m pytest tests/test_live_news_content_policy.py tests/test_live_news_config.py -q`

Expected: all tests pass.

## Task 2: Configuration and API-neutral Content Types

**Files:**
- Create: `backend/app/live_news/content_types.py`
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

- [ ] **Step 1: Add failing settings and type tests**

```python
def test_live_content_settings_have_safe_defaults(monkeypatch):
    clear_settings_cache()
    settings = get_settings()
    assert settings.live_content_worker_enabled is False
    assert settings.live_content_max_response_bytes == 2 * 1024 * 1024
    assert settings.live_content_worker_batch_size == 20
    assert settings.guardian_api_key == ""
```

- [ ] **Step 2: Run the targeted config test and confirm failure**

Run: `python -m pytest tests/test_config.py::test_live_content_settings_have_safe_defaults -q`

Expected: FAIL because settings fields are absent.

- [ ] **Step 3: Add validated settings**

Add the exact environment-backed fields from the design. Validate positive timeouts, response limit, batch size, and concurrency in `get_settings`; reject invalid values rather than silently clamping them.

- [ ] **Step 4: Define provider-neutral types**

```python
@dataclass(frozen=True)
class ContentRequest:
    article_id: str
    canonical_url: str
    expected_domain: str
    language: Literal["zh", "en"]
    policy: ContentPolicy

@dataclass(frozen=True)
class AcquiredContent:
    source: Literal["guardian_api", "rss", "html"]
    body_text: str
    fetched_at: datetime
    extraction_version: str

class ContentAcquisitionError(RuntimeError):
    def __init__(self, code: str, detail: str, *, retryable: bool):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.retryable = retryable
```

- [ ] **Step 5: Run config tests**

Run: `python -m pytest tests/test_config.py -q`

Expected: pass.

## Task 3: PostgreSQL Schema and Durable Queue

**Files:**
- Create: `alembic/versions/20260818_0010_live_news_body_content.py`
- Modify: `backend/app/db/schema.py`
- Create: `backend/app/live_news/content_dao.py`
- Test: `tests/test_dual_space_schema.py`
- Test: `tests/test_live_news_content_dao.py`

- [ ] **Step 1: Write failing schema assertions**

```python
def test_live_news_has_body_columns(postgres_connection):
    columns = table_columns(postgres_connection, "live_news")
    assert {"body_text", "body_source", "body_status", "body_fetched_at",
            "body_content_hash", "body_extraction_version", "content_rights"} <= columns


def test_live_news_content_job_exists(postgres_connection):
    assert primary_key(postgres_connection, "live_news_content_job") == ["article_id"]
```

- [ ] **Step 2: Run migration tests and confirm failure**

Run: `python -m pytest tests/test_dual_space_schema.py -q`

Expected: FAIL because migration `0010` and table are absent.

- [ ] **Step 3: Add migration and SQLAlchemy mirror**

Use `20260817_0009` as `down_revision`. Add the columns, constraints, index on `(status, next_attempt_at)`, and `ON DELETE CASCADE` job foreign key exactly as specified. Backfill existing articles:

```sql
UPDATE live_news
SET content_rights = 'link_only', body_status = 'metadata_only';
```

- [ ] **Step 4: Write failing DAO concurrency and atomicity tests**

```python
def test_ensure_job_is_idempotent(connection, live_article):
    ensure_content_job(connection, live_article, "full_text", now=NOW)
    ensure_content_job(connection, live_article, "full_text", now=NOW)
    assert content_job_count(connection, live_article) == 1


def test_claim_due_jobs_uses_skip_locked(two_connections, live_article):
    first, second = two_connections
    ensure_content_job(first, live_article, "full_text", now=NOW)
    first.commit()
    claimed = claim_due_content_jobs(first, "worker-a", 1, now=NOW)
    assert [job.article_id for job in claimed] == [live_article]
    assert claim_due_content_jobs(second, "worker-b", 1, now=NOW) == []


def test_complete_job_writes_available_body_atomically(connection, live_article):
    acquired = AcquiredContent("html", VALID_BODY, NOW, "trafilatura-2.1")
    complete_content_job(connection, live_article, acquired, "full_text")
    row = load_live_news(connection, live_article)
    assert row["body_status"] == "available"
    assert row["body_text"] == VALID_BODY


def test_stale_fetching_job_returns_to_pending(connection, live_article):
    mark_job_fetching(connection, live_article, claimed_at=NOW - timedelta(hours=1))
    assert recover_stale_content_jobs(connection, NOW - timedelta(minutes=10)) == 1
    assert load_content_job(connection, live_article)["status"] == "pending"
```

- [ ] **Step 5: Implement minimal queue DAO**

Expose focused functions:

```python
ensure_content_job(connection, article_id, rights, *, now)
claim_due_content_jobs(connection, worker_id, limit, *, now)
complete_content_job(connection, article_id, acquired, rights)
retry_content_job(connection, article_id, code, detail, next_attempt_at)
finish_content_job(connection, article_id, status, code, detail)
recover_stale_content_jobs(connection, stale_before)
```

Use a due-job `SELECT` with `FOR UPDATE SKIP LOCKED` inside one transaction and never hold a database transaction during an external request.

- [ ] **Step 6: Run schema and DAO tests**

Run: `python -m pytest tests/test_dual_space_schema.py tests/test_live_news_content_dao.py -q`

Expected: pass.

## Task 4: Body Normalization and Validation

**Files:**
- Create: `backend/app/live_news/content_normalize.py`
- Test: `tests/test_live_news_content_normalize.py`

- [ ] **Step 1: Write failing normalization tests**

```python
def test_normalize_body_preserves_paragraphs_and_removes_controls():
    value = normalize_body("  First  paragraph.\r\n\r\nSecond\x00 paragraph.  ")
    assert value == "First paragraph.\n\nSecond paragraph."


def test_validate_body_rejects_too_short():
    with pytest.raises(ContentAcquisitionError, match="extraction_too_short"):
        validate_body("short", language="en")


def test_hash_uses_normalized_text():
    assert body_hash(" First  paragraph. ") == body_hash("First paragraph.")
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m pytest tests/test_live_news_content_normalize.py -q`

Expected: import failure.

- [ ] **Step 3: Implement normalization and quality bounds**

Normalize Unicode with NFKC, remove disallowed controls, collapse horizontal whitespace, collapse more than two newlines to a paragraph boundary, and enforce 300–200,000 Unicode characters. Implement a deterministic lightweight `zh/en` compatibility check that returns uncertainty rather than rejecting mixed short text; do not add a model dependency.

- [ ] **Step 4: Run normalization tests**

Run: `python -m pytest tests/test_live_news_content_normalize.py -q`

Expected: pass.

## Task 5: Safe HTTPS Fetcher

**Files:**
- Create: `backend/app/live_news/content_fetch.py`
- Test: `tests/test_live_news_content_fetch.py`

- [ ] **Step 1: Write failing SSRF and bound tests**

```python
@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_rejects_non_global_addresses(address):
    with pytest.raises(ContentAcquisitionError, match="unsafe_address"):
        validate_resolved_addresses([address])

def test_revalidates_redirect_target(fake_http):
    fake_http.redirect("https://example.com/a", "https://example.com/b")
    response = make_fetcher(fake_http).get("https://example.com/a", "example.com", {"text/html"})
    assert response.final_url == "https://example.com/b"
    assert fake_http.resolved_hosts == ["example.com", "example.com"]


def test_rejects_cross_domain_redirect(fake_http):
    fake_http.redirect("https://example.com/a", "https://evil.test/b")
    with pytest.raises(ContentAcquisitionError, match="invalid_redirect"):
        make_fetcher(fake_http).get("https://example.com/a", "example.com", {"text/html"})


def test_stops_reading_after_max_response_bytes(fake_http):
    fake_http.respond(b"x" * 33)
    with pytest.raises(ContentAcquisitionError, match="response_too_large"):
        make_fetcher(fake_http, max_bytes=32).get(
            "https://example.com/a", "example.com", {"text/html"}
        )


def test_does_not_log_authorization_or_body(caplog, fake_http):
    fake_http.respond(b"secret article body")
    make_fetcher(fake_http).get(
        "https://example.com/a", "example.com", {"text/html"},
        headers={"Authorization": "secret-key"},
    )
    assert "secret-key" not in caplog.text
    assert "secret article body" not in caplog.text
```

- [ ] **Step 2: Run fetch tests and confirm failure**

Run: `python -m pytest tests/test_live_news_content_fetch.py -q`

Expected: import failure.

- [ ] **Step 3: Implement a small injectable transport**

Define a `SafeFetcher` whose DNS resolver and HTTP transport are injectable in tests. Validate HTTPS, exact source-domain boundary, global resolved addresses, redirects, content type, timeouts, and streaming byte limit. Return:

```python
@dataclass(frozen=True)
class FetchResponse:
    final_url: str
    status: int
    content_type: str
    body: bytes
    retry_after: str | None
```

Never accept a URL from an API request; only call the fetcher with a stored `ContentRequest`.

- [ ] **Step 4: Run fetch tests**

Run: `python -m pytest tests/test_live_news_content_fetch.py -q`

Expected: pass.

## Task 6: Guardian, RSS, and HTML Providers

**Files:**
- Create: `backend/app/live_news/content_providers.py`
- Modify: `backend/requirements.txt`
- Test: `tests/test_live_news_content_providers.py`

- [ ] **Step 1: Add Trafilatura dependency and lock-compatible install input**

Add a bounded compatible version such as `trafilatura>=2.1,<2.2` to runtime requirements.

- [ ] **Step 2: Write failing provider tests using local fixtures**

```python
def test_guardian_provider_extracts_fields_body(fake_fetcher, guardian_fixture):
    fake_fetcher.respond_json(guardian_fixture)
    result = GuardianContentProvider(fake_fetcher, "api-key").acquire(GUARDIAN_REQUEST)
    assert result.source == "guardian_api"
    assert result.body_text.startswith("Published paragraph")


def test_guardian_provider_rejects_returned_url_mismatch(fake_fetcher):
    fake_fetcher.respond_json(guardian_payload(web_url="https://evil.test/article"))
    with pytest.raises(ContentAcquisitionError, match="invalid_redirect"):
        GuardianContentProvider(fake_fetcher, "api-key").acquire(GUARDIAN_REQUEST)


def test_rss_provider_prefers_content_encoded(fake_fetcher, rss_fixture):
    fake_fetcher.respond(rss_fixture)
    result = RssContentProvider(fake_fetcher).acquire(RSS_REQUEST)
    assert "Full encoded body" in result.body_text
    assert "Short description only" not in result.body_text


def test_rss_provider_matches_canonical_url(fake_fetcher):
    fake_fetcher.respond(rss_payload(link="https://example.com/article?utm_source=feed"))
    result = RssContentProvider(fake_fetcher).acquire(RSS_REQUEST)
    assert result.source == "rss"


def test_html_provider_uses_trafilatura_without_comments_or_tables(fake_fetcher):
    fake_fetcher.respond(ARTICLE_HTML)
    result = HtmlContentProvider(fake_fetcher).acquire(HTML_REQUEST)
    assert "Article paragraph" in result.body_text
    assert "Reader comment" not in result.body_text


def test_html_provider_classifies_paywall_marker_as_blocked(fake_fetcher):
    fake_fetcher.respond(PAYWALL_HTML)
    with pytest.raises(ContentAcquisitionError) as raised:
        HtmlContentProvider(fake_fetcher).acquire(HTML_REQUEST)
    assert raised.value.code == "paywall_or_login"
    assert raised.value.retryable is False
```

- [ ] **Step 3: Run provider tests and confirm failure**

Run: `python -m pytest tests/test_live_news_content_providers.py -q`

Expected: provider imports or assertions fail.

- [ ] **Step 4: Implement provider protocol and Guardian provider**

```python
class ContentProvider(Protocol):
    def acquire(self, request: ContentRequest) -> AcquiredContent:
        raise NotImplementedError
```

Guardian must call `https://content.guardianapis.com/{url_path}` with `show-fields=body` and an authorization-safe key parameter, validate the returned URL/domain, convert HTML to text, and pass the result through shared normalization.

- [ ] **Step 5: Implement RSS provider**

Use `xml.etree.ElementTree` with external entity/network expansion unavailable. Match canonicalized links, prefer `{http://purl.org/rss/1.0/modules/content/}encoded`, then description, strip/convert HTML, and classify feed propagation misses as retryable within the freshness window.

- [ ] **Step 6: Implement HTML provider**

Call Trafilatura on the fetched bounded HTML with `include_comments=False`, `include_tables=False`, `favor_precision=True`, and `output_format="txt"`. Check configured paywall/login markers before accepting the result.

- [ ] **Step 7: Run provider and normalization tests**

Run: `python -m pytest tests/test_live_news_content_providers.py tests/test_live_news_content_normalize.py -q`

Expected: pass.

## Task 7: Worker, Retry, and CLI

**Files:**
- Create: `backend/app/live_news/content_worker.py`
- Create: `scripts/run_live_news_content_worker.py`
- Test: `tests/test_live_news_content_worker.py`

- [ ] **Step 1: Write failing worker tests**

```python
def test_worker_completes_successful_job(fake_store, fake_provider):
    fake_store.jobs = [JOB]
    fake_provider.result = ACQUIRED
    LiveNewsContentWorker(fake_store, provider_registry(fake_provider), CLOCK).run_once()
    assert fake_store.completed == [(JOB.article_id, ACQUIRED)]


def test_worker_retries_transient_failure_with_bounded_backoff(fake_store, fake_provider):
    fake_store.jobs = [JOB]
    fake_provider.error = ContentAcquisitionError("timeout", "timed out", retryable=True)
    LiveNewsContentWorker(fake_store, provider_registry(fake_provider), CLOCK).run_once()
    assert fake_store.retried[0].article_id == JOB.article_id
    assert fake_store.retried[0].next_attempt_at > CLOCK.now()


def test_worker_blocks_permanent_failure(fake_store, fake_provider):
    fake_store.jobs = [JOB]
    fake_provider.error = ContentAcquisitionError(
        "paywall_or_login", "login required", retryable=False
    )
    LiveNewsContentWorker(fake_store, provider_registry(fake_provider), CLOCK).run_once()
    assert fake_store.finished == [(JOB.article_id, "blocked", "paywall_or_login")]


def test_worker_recovers_stale_claims_before_poll(fake_store, fake_provider):
    LiveNewsContentWorker(fake_store, provider_registry(fake_provider), CLOCK).run_once()
    assert fake_store.calls[:2] == ["recover_stale", "claim_due"]


def test_worker_shutdown_stops_before_claiming_next_batch(fake_store, fake_provider):
    worker = LiveNewsContentWorker(fake_store, provider_registry(fake_provider), CLOCK)
    worker.stop()
    assert worker.run_once().claimed_count == 0
    assert "claim_due" not in fake_store.calls
```

- [ ] **Step 2: Run worker tests and confirm failure**

Run: `python -m pytest tests/test_live_news_content_worker.py -q`

Expected: import failure.

- [ ] **Step 3: Implement one-batch orchestration**

```python
class LiveNewsContentWorker:
    def run_once(self) -> WorkerBatchResult:
        self.store.recover_stale(self.clock.now() - self.stale_claim_after)
        jobs = self.store.claim_due(self.worker_id, self.batch_size, self.clock.now())
        for job in jobs:
            try:
                acquired = self.providers.for_mode(job.policy.mode).acquire(job.request)
                self.store.complete(job, acquired)
            except ContentAcquisitionError as exc:
                self._finish_failure(job, exc)
        return WorkerBatchResult(claimed_count=len(jobs), completed_count=completed)
```

Backoff is deterministic under an injectable clock/random source in tests, capped, and limited to five attempts.

- [ ] **Step 4: Add standalone CLI**

Follow `scripts/run_live_news_collector.py`: load settings, refuse to start when disabled or PostgreSQL is unavailable, construct providers, handle SIGINT/SIGTERM, and loop with a short idle wait. Never start the worker from FastAPI startup.

- [ ] **Step 5: Run worker and CLI import tests**

Run: `python -m pytest tests/test_live_news_content_worker.py -q`

Expected: pass.

## Task 8: Link Metadata Ingestion to Content Jobs

**Files:**
- Modify: `backend/app/live_news/dao.py`
- Modify: `scripts/run_live_news_collector.py`
- Test: `tests/test_live_news_dao.py`
- Test: `tests/test_live_news_collector.py`

- [ ] **Step 1: Write failing ingestion-to-job tests**

```python
def test_persist_batch_ensures_job_for_guardian_policy(connection, batch, allowlist):
    persist_batch(connection, batch, allowlist=allowlist)
    assert load_content_job(connection, batch.articles[0].article_id)["status"] == "pending"


def test_persist_batch_keeps_link_only_article_metadata_only(connection, batch, allowlist):
    persist_batch(connection, batch, allowlist=link_only_allowlist())
    row = load_live_news(connection, batch.articles[0].article_id)
    assert row["body_status"] == "metadata_only"
    assert load_content_job(connection, batch.articles[0].article_id) is None


def test_replayed_batch_does_not_duplicate_content_job(connection, batch, allowlist):
    persist_batch(connection, batch, allowlist=allowlist)
    persist_batch(connection, batch, allowlist=allowlist)
    assert content_job_count(connection, batch.articles[0].article_id) == 1
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m pytest tests/test_live_news_dao.py tests/test_live_news_collector.py -q`

Expected: no job exists after accepted metadata Upsert.

- [ ] **Step 3: Pass policy decisions into persistence**

Resolve policy before persistence and set `content_rights` plus initial `body_status`. In the same transaction as `live_news` Upsert, call `ensure_content_job` for `guardian_api`, `rss`, or `html`. Never requeue an unchanged terminal job unless extraction version or explicit policy changes require it.

- [ ] **Step 4: Add explicit backfill command option**

Add `--enqueue-content-backfill` to the collector CLI. It queues only active, policy-eligible articles within `live_news_max_age_hours`, and remains idempotent.

- [ ] **Step 5: Run ingestion regression tests**

Run: `python -m pytest tests/test_live_news_dao.py tests/test_live_news_collector.py tests/test_live_news_normalize.py -q`

Expected: pass.

## Task 9: Article API Rights Enforcement

**Files:**
- Modify: `backend/app/schemas/article.py`
- Modify: `backend/app/news_spaces/live.py`
- Modify: `backend/app/repositories/postgres.py`
- Test: `tests/test_live_news_body_routes.py`

- [ ] **Step 1: Write failing route tests**

```python
def test_full_text_article_returns_body(client, live_article_with_body):
    response = client.get(f"/articles/live/{live_article_with_body}")
    assert response.status_code == 200
    assert response.json()["body_text"] == VALID_BODY


def test_excerpt_only_never_returns_more_than_1000_characters(client, live_excerpt_article):
    body = client.get(f"/articles/live/{live_excerpt_article}").json()["body_text"]
    assert body is not None
    assert len(body) <= 1000


def test_link_only_suppresses_stored_body(client, live_link_only_article):
    payload = client.get(f"/articles/live/{live_link_only_article}").json()
    assert payload["body_text"] is None
    assert payload["content_rights"] == "link_only"


def test_pending_article_returns_summary_without_network(client, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("network"))
    payload = client.get(f"/articles/live/{PENDING_ARTICLE_ID}").json()
    assert payload["body_status"] == "pending"
    assert payload["abstract"] == "Stored GDELT description"


def test_mind_article_returns_metadata_only_body_contract(client):
    payload = client.get("/articles/mind/N1").json()
    assert payload["body_text"] is None
    assert payload["body_status"] == "metadata_only"
```

- [ ] **Step 2: Run route tests and confirm failure**

Run: `python -m pytest tests/test_live_news_body_routes.py -q`

Expected: response model lacks body fields.

- [ ] **Step 3: Extend the response model**

```python
body_text: str | None = None
body_status: Literal["metadata_only", "pending", "available", "blocked", "failed"] = "metadata_only"
body_source: Literal["guardian_api", "rss", "html"] | None = None
content_rights: Literal["full_text", "excerpt_only", "link_only"] = "link_only"
```

- [ ] **Step 4: Enforce rights in the repository**

Return full normalized text only for `full_text + available`. Return a deterministic 1,000-character Unicode excerpt for `excerpt_only + available`; prefer a paragraph boundary but never exceed the limit. Return `None` otherwise. Perform no network I/O.

- [ ] **Step 5: Run article and API contract tests**

Run: `python -m pytest tests/test_live_news_body_routes.py tests/test_live_news_routes.py tests/test_article_card_route.py -q`

Expected: pass.

## Task 10: Safe Frontend Body Rendering

**Files:**
- Modify: `product-frontend/src/api/types.ts`
- Modify: `product-frontend/src/pages/ArticleDetailPage.tsx`
- Modify: `product-frontend/src/styles/liveNews.css`
- Create: `product-frontend/src/pages/ArticleDetailPage.body.test.tsx`

- [ ] **Step 1: Write failing rendering tests**

```tsx
it("renders available body as text paragraphs", async () => {
  mockArticle({ bodyText: "First paragraph.\n\nSecond paragraph.", bodyStatus: "available" });
  renderArticle();
  expect(await screen.findByText("First paragraph.")).toBeInTheDocument();
  expect(screen.getByText("Second paragraph.")).toBeInTheDocument();
});

it("does not interpret provider markup", async () => {
  mockArticle({ bodyText: '<script>alert("x")</script>', bodyStatus: "available" });
  renderArticle();
  expect(await screen.findByText('<script>alert("x")</script>')).toBeInTheDocument();
  expect(document.querySelector("script")).toBeNull();
});

it("keeps summary and read-original fallback for failed content", async () => {
  mockArticle({ bodyText: null, bodyStatus: "failed", abstract: "Stored description" });
  renderArticle();
  expect(await screen.findByText("Stored description")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /read original/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `npm test -- --run src/pages/ArticleDetailPage.body.test.tsx`

Working directory: `product-frontend`

Expected: type or rendering assertions fail.

- [ ] **Step 3: Extend TypeScript article fields**

Use the API client's existing snake-to-camel conversion conventions. Add `bodyText`, `bodyStatus`, `bodySource`, and `contentRights` without making older fixtures invalid.

- [ ] **Step 4: Render safe body states**

Split normalized body text on blank lines, trim empty values, and render each paragraph as React text nodes. Do not use `dangerouslySetInnerHTML`. Show:

- available body when present;
- a neutral pending message for `pending`;
- existing abstract for metadata-only, blocked, or failed;
- **Read original** in every Live state.

- [ ] **Step 5: Add readable responsive typography**

Constrain body width, use comfortable line height, preserve wrapping, and provide dark-theme colors through existing variables. Do not redesign unrelated page sections.

- [ ] **Step 6: Run focused frontend tests**

Run: `npm test -- --run src/pages/ArticleDetailPage.body.test.tsx src/pages/ArticleDetailPage.test.tsx`

Working directory: `product-frontend`

Expected: pass.

## Task 11: Metrics and Optional Dependency Health

**Files:**
- Modify: `backend/app/observability.py`
- Modify: `backend/app/health.py`
- Test: `tests/test_health.py`
- Test: `tests/test_live_news_content_worker.py`

- [ ] **Step 1: Write failing metric and health tests**

```python
def test_content_worker_disabled_health_is_disabled():
    health = check_readiness(Settings(live_content_worker_enabled=False))
    assert health.dependencies["live_content_worker"].status == "disabled"


def test_content_worker_stale_health_is_degraded_not_api_failure():
    health = readiness_with_content_heartbeat(age_seconds=3600)
    assert health.dependencies["live_content_worker"].status == "degraded"
    assert health.status == "ok"


def test_content_metrics_use_bounded_provider_and_reason_labels():
    record_content_failure("unknown-provider", "unbounded-error-text")
    assert metric_sample("live_content_failure_total", provider="unknown", reason="unknown") == 1
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m pytest tests/test_health.py tests/test_live_news_content_worker.py -q`

Expected: content dependency and metrics are absent.

- [ ] **Step 3: Add bounded metrics and heartbeat state**

Add the design metrics with provider and reason values normalized through fixed literal sets. Persist or derive last success from completed jobs; do not use in-memory-only health for a separate process.

- [ ] **Step 4: Add optional degraded readiness**

When disabled, report `disabled`. When enabled and healthy, report `ok`. When stale or misconfigured, report `degraded` in detail while leaving overall core API readiness true because metadata-only serving remains valid.

- [ ] **Step 5: Run health and observability tests**

Run: `python -m pytest tests/test_health.py tests/test_live_news_content_worker.py -q`

Expected: pass.

## Task 12: Full Verification and Root-Cause Repair Loop

**Files:**
- Modify only files proven necessary by failing tests.

- [ ] **Step 1: Run formatting and static checks**

Run from repository root:

```powershell
python -m ruff check backend scripts tests
python -m ruff format --check backend scripts tests
python -m mypy backend scripts
```

Expected: zero errors. For each failure, identify whether the cause is new content code, an existing V1 conflict, or environment configuration before changing code.

- [ ] **Step 2: Run focused backend suite**

```powershell
python -m pytest tests/test_live_news_content_policy.py tests/test_live_news_content_normalize.py tests/test_live_news_content_fetch.py tests/test_live_news_content_providers.py tests/test_live_news_content_dao.py tests/test_live_news_content_worker.py tests/test_live_news_body_routes.py tests/test_live_news_collector.py tests/test_live_news_dao.py tests/test_health.py -q
```

Expected: all pass.

- [ ] **Step 3: Run PostgreSQL migration/integration suite**

```powershell
python -m pytest tests/test_alembic_schema.py tests/test_dual_space_schema.py tests/test_postgres_smoke.py tests/test_dual_space_acceptance.py -q
```

Expected: all pass against the configured test PostgreSQL. If PostgreSQL is unavailable, record the exact external blocker and still run every unit test that does not require it.

- [ ] **Step 4: Run complete backend test suite**

Run: `python -m pytest -q`

Expected: all pass. Do not dismiss regressions as unrelated without reproducing against the pre-feature state or proving an environment-only cause.

- [ ] **Step 5: Run frontend checks**

Working directory: `product-frontend`

```powershell
npm test -- --run
npm run build
```

Expected: all tests pass and production build succeeds.

- [ ] **Step 6: Run deterministic end-to-end content fixture**

Start the test API and content worker against fixture transport or a local fixture HTTP server. Verify:

```text
metadata article -> pending job -> available body -> GET article returns body -> page renders paragraphs
```

Also verify:

```text
blocked/failing provider -> article remains visible -> summary shown -> Read original works
```

- [ ] **Step 7: Run optional real-provider smoke check**

Only when a Guardian developer key is configured, fetch one allowlisted current article through the official API with bounded logs. Do not make this a CI requirement. Record article ID, provider, result, duration, and body character count without logging text.

- [ ] **Step 8: Inspect final diff and preserve user changes**

Run:

```powershell
git status --short
git diff --check
git diff --stat
```

Expected: no whitespace errors; only intended feature files/hunks plus the user's pre-existing changes. Do not stage or commit overlapping user files.
