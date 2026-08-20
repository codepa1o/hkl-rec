# Live News Body Acquisition Design

**Status:** Approved in conversation; pending written-spec review

**Date:** 2026-08-18

**Scope:** Enrich allowlisted Live news with locally stored, safely rendered article text while preserving metadata-only fallback and the existing MIND/Live isolation model.

## 1. Goal

The Live news detail page displays article body text when the source policy permits acquisition and local display. Body acquisition runs asynchronously after GDELT metadata ingestion and never blocks Feed, Search, or article-detail requests.

Each Live article remains usable when body acquisition is unavailable. The product falls back to the existing title, summary, image, publisher metadata, and **Read original** action.

## 2. Current State

The first Live release intentionally stores GDELT Article List metadata only. `live_news` has `summary` but no body field, and the Live article repository currently maps `summary` to the API `abstract`. GDELT remains the discovery source; it does not become the authority for full article text.

The body feature extends only the `live` news space. It does not change `mind_news`, MIND imports, MIND artifacts, MIND metrics, or the source-space isolation invariants established by the dual-news-space design.

## 3. Confirmed Product Decisions

1. Body acquisition is asynchronous and server-side.
2. An article detail request reads stored content; it never fetches a publisher page on demand.
3. Acquisition is controlled by an explicit per-domain policy in `config/live_news_sources.json`.
4. Source priority is publisher API, full-text RSS, allowlisted HTML extraction, then metadata-only fallback.
5. The first release stores normalized plain text with paragraph breaks, not publisher HTML.
6. Login, CAPTCHA, paywall, or anti-bot controls are never bypassed.
7. A source may be configured as `link_only`; those articles are never queued for body fetching.
8. Body failure does not deactivate an otherwise valid Live article.
9. Existing and newly ingested articles may be enriched through the same idempotent job mechanism.
10. The original publisher URL remains visible and available even when local body text exists.

## 4. Alternatives Considered

### 4.1 Publisher APIs only

This offers the clearest contract and most stable structure, but it requires one adapter and credential arrangement per publisher and leaves most GDELT discoveries without body text.

### 4.2 Generic HTML extraction only

This offers broad coverage with one implementation, but source behavior, extraction quality, paywalls, and display rights vary. Treating every URL as equally fetchable is unsafe and operationally fragile.

### 4.3 Policy-driven multi-provider pipeline — selected

The selected design chooses a provider from an explicit domain policy. Official APIs take precedence, RSS is used where a configured feed exposes permitted full text, and generic HTML extraction is limited to approved domains. All other content remains metadata-only.

This approach preserves a small stable interface while allowing source-specific behavior to grow without changing Feed or detail-page contracts.

## 5. Architecture

```text
GDELT metadata transaction
  -> Upsert live_news
  -> Ensure content job when domain policy permits

LiveNewsContentWorker
  -> Claim due job with FOR UPDATE SKIP LOCKED
  -> Load article and immutable source policy
  -> Select provider
       GuardianContentProvider
       RssContentProvider
       HtmlContentProvider
  -> Fetch and extract
  -> Validate normalized body
  -> Persist body and complete job atomically
  -> Record bounded metrics

GET /articles/live/{article_id}
  -> Read local metadata and body state only
  -> Return body text or metadata-only fallback
```

The components have these responsibilities:

- `ContentPolicy`: parses and validates per-domain acquisition and display rules.
- `ContentProvider`: returns a provider-neutral acquisition result for one article.
- `GuardianContentProvider`: obtains Guardian `fields.body` through the official Content API when a key is configured.
- `RssContentProvider`: loads configured publisher feeds and matches items by canonical URL.
- `HtmlContentProvider`: fetches an approved public HTML page and uses Trafilatura to extract main text.
- `BodyNormalizer`: converts provider output to safe normalized plain text and enforces quality limits.
- `LiveNewsContentStore`: claims jobs and commits content state without exposing SQL to providers.
- `LiveNewsContentWorker`: owns retry classification, orchestration, metrics, and shutdown behavior.

Providers do not write to PostgreSQL and do not know about API schemas. The worker does not contain publisher-specific parsing rules.

## 6. Source Policy

Each existing allowlist entry gains a `content` object:

```json
{
  "domain": "theguardian.com",
  "languages": ["en"],
  "quality_weight": 0.95,
  "content": {
    "mode": "guardian_api",
    "display": "full_text",
    "feed_urls": []
  }
}
```

Supported values are:

```text
mode:     guardian_api | rss | html | link_only
display:  full_text | excerpt_only | link_only
```

Rules are explicit:

- `link_only` never creates a fetch job.
- `excerpt_only` may acquire content for extraction validation and future indexing, but the API returns at most the configured excerpt length.
- `full_text` permits the locally stored normalized text to be returned by the detail API.
- `rss` requires at least one HTTPS `feed_urls` entry.
- `guardian_api` requires `NEWSREC_GUARDIAN_API_KEY`; a missing key produces a visible disabled dependency state and leaves jobs pending rather than silently falling back to scraping.
- `html` never escalates to a browser or another provider when extraction fails.

Configuration is validated at startup. Invalid modes, display values, non-HTTPS feed URLs, or incompatible combinations fail fast.

## 7. Database Design

`live_news` gains nullable content fields:

```text
body_text                TEXT
body_source              VARCHAR(32)
body_status              VARCHAR(24) not null default 'metadata_only'
body_fetched_at          TIMESTAMPTZ
body_content_hash        VARCHAR(64)
body_extraction_version  VARCHAR(32)
content_rights           VARCHAR(24) not null default 'link_only'
```

Allowed values are:

```text
body_source:    guardian_api | rss | html
body_status:    metadata_only | pending | available | blocked | failed
content_rights: full_text | excerpt_only | link_only
```

Invariants:

- `available` requires non-empty `body_text`, `body_source`, `body_fetched_at`, `body_content_hash`, and `body_extraction_version`.
- Any state other than `available` has `body_text = NULL`.
- `link_only` always returns `body_text = NULL`, regardless of stored internal state.
- Body hash is SHA256 of the normalized UTF-8 body text.

A separate `live_news_content_job` table provides a durable work queue:

```text
article_id          VARCHAR(64) primary key references live_news(article_id)
status              VARCHAR(16) not null
attempt_count       INTEGER not null default 0
next_attempt_at     TIMESTAMPTZ not null
claimed_at          TIMESTAMPTZ
worker_id           VARCHAR(128)
last_error_code     VARCHAR(64)
last_error_detail   TEXT
created_at          TIMESTAMPTZ not null
updated_at          TIMESTAMPTZ not null
```

Job status is `pending`, `fetching`, `completed`, `blocked`, or `failed`. One article has at most one job. Re-enrichment resets a terminal job to `pending` only through an explicit operator command or an extraction-version backfill.

The metadata Upsert and initial job creation occur in the same transaction. Job completion and body persistence also occur in one transaction.

## 8. Provider Behavior

### 8.1 Guardian API

The adapter derives the Guardian content ID from the canonical URL path and requests the official Content API with `show-fields=body,headline,thumbnail`. It accepts only a successful response whose returned canonical URL belongs to the expected Guardian domain.

The returned HTML is converted to normalized plain text. The raw API HTML and API key are not persisted or logged.

Authentication failures are classified as configuration failures and exposed in readiness. Rate limiting honors `Retry-After` and remains retryable.

### 8.2 Full-text RSS

The RSS adapter fetches only configured HTTPS feeds. It matches an item after canonicalizing the item link with the same URL rules used by GDELT ingestion.

Content precedence is `content:encoded`, then `description`. A candidate must pass the same body quality checks as HTML extraction. A missing matching item is retryable for a bounded freshness window and then becomes `metadata_only`; it does not fall back to HTML unless the source policy is explicitly changed to `html`.

### 8.3 Allowlisted HTML extraction

The HTML adapter requests only the article's stored canonical URL after source policy validation. It accepts `text/html` responses only and passes the bounded response body to Trafilatura with comments and tables disabled and precision favored.

The adapter does not execute JavaScript, submit forms, send cookies, authenticate, follow paywall prompts, or invoke a headless browser. A page that requires those mechanisms becomes `blocked` or `failed` according to the failure classification.

## 9. Fetch Security

All external content requests enforce:

- `https` only;
- an exact allowlisted hostname boundary;
- DNS resolution immediately before each request;
- rejection of loopback, private, link-local, multicast, reserved, unspecified, and otherwise non-global addresses;
- redirect limits and complete URL, domain, and resolved-address validation after every redirect;
- a fixed identifiable User-Agent;
- separate connect and read timeouts;
- maximum compressed and decompressed response sizes;
- accepted content types restricted to provider-specific JSON/XML or `text/html`;
- per-domain concurrency and request-rate limits;
- no forwarding of credentials across hosts;
- no response body, API key, cookie, or authorization header in logs.

The article URL is never taken directly from a client request. It must be the canonical URL stored for an allowlisted Live article.

## 10. Body Normalization and Quality

All providers produce one normalized plain-text representation:

- Unicode is normalized consistently.
- Line endings become `\n`.
- Paragraph boundaries are represented by one blank line.
- Navigation text, comments, scripts, styles, and empty paragraphs are removed before normalization.
- Repeated internal whitespace is collapsed without joining paragraphs.
- Leading and trailing whitespace is removed.
- NUL and disallowed control characters are removed.

The first release accepts bodies between 300 and 200,000 Unicode characters. Text above the maximum is rejected instead of silently truncated so the stored hash always represents a complete accepted body. The detected language must be compatible with the article's `zh` or `en` language, allowing configured uncertainty for short bodies.

No generated summary is presented as publisher text. Existing GDELT `summary` remains a separately labeled metadata description.

## 11. Retry and Failure Classification

Retryable failures include network timeouts, DNS failures, HTTP 408/425/429, HTTP 5xx, feed propagation delay, and temporary provider errors. The worker applies bounded exponential backoff with jitter and honors a valid `Retry-After` header.

Permanent outcomes include:

```text
blocked_by_policy
authentication_required
paywall_or_login
unsupported_content_type
response_too_large
invalid_redirect
unsafe_address
extraction_too_short
extraction_too_long
language_mismatch
article_not_found
```

HTTP 404/410 may continue through the existing link-health path, but body failure alone never marks the article inactive. After five retryable attempts, the job becomes `failed`; an operator may requeue it later.

Workers recover `fetching` jobs whose `claimed_at` exceeds the stale-claim threshold.

## 12. API and Frontend Contract

`ArticleCardResponse` gains:

```text
body_text: str | null
body_status: metadata_only | pending | available | blocked | failed
body_source: guardian_api | rss | html | null
content_rights: full_text | excerpt_only | link_only
```

For `mind`, these fields return `null`, `metadata_only`, `null`, and `link_only` respectively unless a later MIND-specific feature explicitly changes that contract.

For `live`:

- `full_text + available` returns the complete normalized body.
- `excerpt_only + available` returns a server-derived excerpt no longer than 1,000 Unicode characters and never returns the full stored body.
- every other combination returns `body_text = null`.

The detail page:

1. Displays title, publisher, timestamps, image, and metadata description as today.
2. Renders `body_text` as safe text paragraphs when present.
3. Shows a neutral loading message for `pending` without polling faster than 30 seconds.
4. Shows the metadata description for `metadata_only`, `blocked`, or `failed`.
5. Always retains **Read original** and the existing `outbound_click` event behavior.

The frontend never renders provider HTML with `dangerouslySetInnerHTML`.

## 13. Worker Operation and Rollout

New settings are:

```text
NEWSREC_LIVE_CONTENT_WORKER_ENABLED=0
NEWSREC_GUARDIAN_API_KEY=
NEWSREC_LIVE_CONTENT_CONNECT_TIMEOUT_SECONDS=5
NEWSREC_LIVE_CONTENT_READ_TIMEOUT_SECONDS=15
NEWSREC_LIVE_CONTENT_MAX_RESPONSE_BYTES=2097152
NEWSREC_LIVE_CONTENT_WORKER_BATCH_SIZE=20
NEWSREC_LIVE_CONTENT_WORKER_CONCURRENCY=4
```

The worker is a separate process with graceful shutdown and a unique worker ID. CI and request-serving processes never start it implicitly.

Rollout order:

1. Add schema, policy validation, API fields, and metadata-only frontend behavior with the worker disabled.
2. Add provider-neutral queue, worker, normalizer, security checks, and fixture-based tests.
3. Enable one `guardian_api` source in a non-production environment when a key is available.
4. Enable selected `rss` and `html` policies one source at a time.
5. Backfill current active Live articles within the existing maximum-age window.
6. Enable body rendering after monitoring coverage, failure reasons, latency, and extraction samples.

Disabling the worker preserves already stored bodies and leaves pending jobs durable. Removing full-text display permission from a policy immediately suppresses body output; an operator cleanup can erase previously stored text.

## 14. Observability

Bounded metrics are:

```text
live_content_jobs_total{provider,result}
live_content_fetch_duration_seconds{provider}
live_content_fetch_bytes{provider}
live_content_queue_depth{status}
live_content_available_total{domain}
live_content_failure_total{provider,reason}
live_content_last_success_timestamp{provider}
```

Readiness reports configuration failures and stale worker progress only when the content worker feature is enabled. A content-worker failure does not make the core API unready; it is reported as a degraded optional dependency because metadata-only serving remains valid.

Logs contain article ID, bounded provider name, bounded result/reason code, attempt number, duration, and response size. They do not contain body text or secrets.

## 15. Testing Strategy

### 15.1 Policy and security tests

- Invalid policy combinations fail startup validation.
- Exact host matching rejects suffix tricks and user-info URLs.
- Private, loopback, link-local, reserved, and redirect-to-private targets are rejected.
- Credentials are not forwarded across redirects or emitted in logs.
- Oversized and unsupported responses are rejected before extraction.

### 15.2 Provider tests

- Guardian fixtures cover success, missing fields, authentication error, 429, malformed JSON, and URL mismatch.
- RSS fixtures cover `content:encoded`, description fallback, canonical link matching, malformed XML, and delayed appearance.
- HTML fixtures cover clean articles, navigation noise, insufficient content, wrong language, paywall markers, and extraction exceptions.
- CI uses fixtures and never contacts real publishers.

### 15.3 Queue and persistence tests

- Metadata Upsert creates one idempotent job only when policy permits.
- Concurrent workers cannot claim the same job.
- Job completion and body persistence are atomic.
- Retry scheduling, stale-claim recovery, terminal failure, and explicit requeue are deterministic.
- Reprocessing an unchanged body does not change its hash or create duplicate jobs.
- Policy downgrade suppresses or clears body output as specified.

### 15.4 API and frontend tests

- Available full text is returned and rendered as safe paragraphs.
- Excerpt-only content never exposes the full body.
- Metadata-only, pending, blocked, and failed states retain summary and original link.
- The detail route performs no outbound network request.
- Existing MIND detail behavior and Live source-space routing remain unchanged.
- No provider HTML is inserted into the DOM.

### 15.5 Optional smoke tests

Real Guardian or publisher connectivity checks are manual, credential-aware, bounded, and non-blocking. They are excluded from the deterministic CI suite.

## 16. Acceptance Criteria

1. GDELT ingestion remains metadata-first and continues when all body providers are unavailable.
2. Every body request is initiated by the asynchronous worker from a stored allowlisted article, never from a user-facing request.
3. Per-domain policy determines provider, acquisition permission, and display permission.
4. The detail API and frontend expose normalized text only according to `content_rights`.
5. Metadata-only fallback and **Read original** work for every failure and policy state.
6. Login, CAPTCHA, paywall, JavaScript rendering, and anti-bot bypass are outside the implementation.
7. SSRF, redirects, response size, timeout, rate limit, secret handling, and content-type controls are covered by tests.
8. Queue claims, retries, stale recovery, and content persistence are idempotent and concurrency-safe.
9. Content metrics and degraded dependency health make coverage and failures observable without leaking body text or credentials.
10. Existing MIND behavior, Live Feed/Search, source-space isolation, event semantics, and deterministic CI tests remain intact.
