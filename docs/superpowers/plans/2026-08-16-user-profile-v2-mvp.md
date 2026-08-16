# User Profile V2 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a session-bound, explainable short/long-term topic profile with negative and dwell feedback, reset support, and an opt-in `profile_v2` feed arm while preserving V1 and default feed behavior.

**Architecture:** PostgreSQL `user_event` remains the fact log, `user_profile` remains the V1 compatibility projection, and a normalized `user_topic_profile` table becomes the V2 projection. Pure signal math is isolated from SQL; the existing event consumer updates V1 and V2 in one transaction. Formal profile APIs use the authenticated session, while the feed reads V2 only for the explicit experiment arm and rolls back failed reads to a savepoint.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, psycopg, PostgreSQL/Alembic, Prometheus client, pytest, React 18, TypeScript, Vitest, Testing Library.

---

## File map

- Create `backend/app/profiles/__init__.py`: profile-domain package marker.
- Create `backend/app/profiles/signals.py`: decay, event weights, confidence, status, and combined-score pure functions.
- Create `backend/app/repositories/profile_v2_dao.py`: V2 projection reads, topic UPSERTs, reset, and replay helpers.
- Create `backend/app/routers/profile.py`: authenticated `GET /profile` and `POST /profile/reset`.
- Create `alembic/versions/20260816_0003_user_profile_v2.py`: V2 table and user-level projection columns.
- Create `scripts/rebuild_profile_v2.py`: deterministic `user_event` replay CLI.
- Create `product-frontend/src/components/ProfilePanel.tsx`: formal profile display and reset UX.
- Create `product-frontend/src/profile/visibleDwell.ts`: visible-time accumulator and stable dwell event ID.
- Modify `backend/app/config.py`: V2 flag, half-lives, long-term factor, and feed boost.
- Modify `backend/app/db/schema.py`: SQLAlchemy metadata mirror for the migration.
- Modify `backend/app/events/consumer.py`: call V2 projection in the existing event transaction.
- Modify `backend/app/observability.py`: V2 update, late-event, fallback, reset, and duration metrics.
- Modify `backend/app/repositories/{base,postgres,unwired}.py`: formal profile methods and experiment scoring.
- Modify `backend/app/schemas/{profile,feed}.py`: formal response types and `profile_v2` arm/debug score.
- Modify `backend/app/services/profile.py`, `backend/app/dependencies.py`, and `backend/app/main.py`: formal use cases and route registration.
- Modify `product-frontend/src/api/{types,client}.ts`: formal profile and reset contracts.
- Modify `product-frontend/src/components/RightRail.tsx`: current-user panel versus alternate demo debug panel.
- Modify `product-frontend/src/pages/ArticleDetailPage.tsx`: visible dwell delivery.
- Modify `product-frontend/src/styles/global.css`: profile states, topic evidence, and reset controls.
- Create focused backend and frontend tests listed below; retain all existing tests unchanged.

### Task 1: Pure profile signal rules

**Files:**
- Create: `backend/app/profiles/__init__.py`
- Create: `backend/app/profiles/signals.py`
- Test: `tests/test_profile_signals.py`

- [ ] **Step 1: Write failing tests for decay, event weights, confidence, and ordering**

```python
from math import isclose

from backend.app.profiles.signals import (
    TopicProfileState,
    confidence_from_evidence,
    dwell_signal_strength,
    event_signal_strength,
    profile_status,
    project_topic_signal,
)


def test_short_and_long_scores_decay_independently() -> None:
    state = TopicProfileState(short_positive_score=8.0, long_positive_score=8.0, last_event_ts=100)
    projected = project_topic_signal(
        state, signal=0.0, event_type="feed_impression", event_ts=200,
        short_half_life_seconds=100, long_half_life_seconds=200, long_term_factor=0.25,
    )
    assert projected is not None
    assert isclose(projected.short_positive_score, 4.0)
    assert isclose(projected.long_positive_score, 8.0 * 2 ** -0.5)


def test_negative_signal_updates_only_negative_components() -> None:
    projected = project_topic_signal(
        TopicProfileState(), signal=-2.0, event_type="downvote", event_ts=100,
        short_half_life_seconds=21_600, long_half_life_seconds=2_592_000,
        long_term_factor=0.25,
    )
    assert projected is not None
    assert projected.short_negative_score == 2.0
    assert projected.long_negative_score == 0.5
    assert projected.negative_evidence_count == 1


def test_dwell_boundaries_and_profile_confidence() -> None:
    assert [dwell_signal_strength(ms) for ms in (9_999, 10_000, 30_000, 120_000)] == [0, .25, .5, .75]
    assert event_signal_strength("upvote") == 2.0
    assert event_signal_strength("downvote") == -2.0
    assert confidence_from_evidence(0) == 0.0
    assert profile_status(confidence_from_evidence(1)) == "cold"
    assert profile_status(confidence_from_evidence(8)) == "learning"
    assert profile_status(confidence_from_evidence(12)) == "established"


def test_older_event_is_rejected_without_mutation() -> None:
    state = TopicProfileState(short_positive_score=1.0, last_event_ts=200)
    assert project_topic_signal(
        state, signal=1.0, event_type="recommendation_click", event_ts=199,
        short_half_life_seconds=21_600, long_half_life_seconds=2_592_000,
        long_term_factor=0.25,
    ) is None
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_signals.py -q`

Expected: collection fails with `ModuleNotFoundError: backend.app.profiles`.

- [ ] **Step 3: Implement the pure signal module**

```python
@dataclass(frozen=True, slots=True)
class TopicProfileState:
    short_positive_score: float = 0.0
    short_negative_score: float = 0.0
    long_positive_score: float = 0.0
    long_negative_score: float = 0.0
    positive_evidence_count: int = 0
    negative_evidence_count: int = 0
    signal_counts: Mapping[str, int] = field(default_factory=dict)
    last_signal_type: str | None = None
    last_event_ts: int | None = None


@dataclass(frozen=True, slots=True)
class ProfileSignalConfig:
    short_half_life_seconds: int
    long_half_life_seconds: int
    long_term_factor: float


def decayed_score(score: float, elapsed_seconds: int, half_life_seconds: int) -> float:
    return score * 2 ** (-max(elapsed_seconds, 0) / half_life_seconds)


def confidence_from_evidence(evidence_count: int) -> float:
    return 1.0 - exp(-max(evidence_count, 0) / 8.0)


def profile_status(confidence: float) -> Literal["cold", "learning", "established"]:
    return "cold" if confidence < 0.25 else "learning" if confidence < 0.75 else "established"
```

Use these exact boundaries and score composition; a zero signal may decay an existing row but must not add evidence or change `last_signal_type`, and an older event returns `None`.

```python
def dwell_signal_strength(dwell_ms: int | None) -> float:
    if dwell_ms is None or dwell_ms < 10_000:
        return 0.0
    if dwell_ms < 30_000:
        return 0.25
    if dwell_ms < 120_000:
        return 0.50
    return 0.75


def event_signal_strength(event_type: str, dwell_ms: int | None = None) -> float:
    return {
        "recommendation_click": 1.0,
        "search_result_click": 1.25,
        "upvote": 2.0,
        "downvote": -2.0,
    }.get(event_type, dwell_signal_strength(dwell_ms) if event_type == "dwell" else 0.0)


def combined_topic_score(state: TopicProfileState) -> float:
    short_net = state.short_positive_score - state.short_negative_score
    long_net = state.long_positive_score - state.long_negative_score
    return 0.70 * tanh(short_net) + 0.30 * tanh(long_net)
```

- [ ] **Step 4: Run RED tests until GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_signals.py -q`

Expected: `4 passed` or more after boundary cases are split.

- [ ] **Step 5: Commit Task 1**

```powershell
git add backend/app/profiles tests/test_profile_signals.py
git commit -m "feat: add profile v2 signal rules"
```

### Task 2: V2 database schema

**Files:**
- Create: `alembic/versions/20260816_0003_user_profile_v2.py`
- Modify: `backend/app/db/schema.py`
- Test: `tests/test_alembic_schema.py`

- [ ] **Step 1: Add failing metadata and migration contract tests**

```python
def test_profile_v2_metadata_has_normalized_topic_projection() -> None:
    table = db_schema.metadata.tables["user_topic_profile"]
    assert list(table.primary_key.columns.keys()) == ["user_id", "topic_id"]
    assert {"short_positive_score", "short_negative_score", "long_positive_score",
            "long_negative_score", "evidence_counts_json", "last_event_ts"} <= set(table.c)


def test_profile_v2_user_state_columns_exist() -> None:
    columns = set(db_schema.user_profile.c.keys())
    assert {"profile_v2_evidence_count", "profile_v2_last_event_ts",
            "profile_reset_before_ts", "profile_v2_updated_at"} <= columns
```

- [ ] **Step 2: Run tests and verify missing table/columns failures**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alembic_schema.py -q`

Expected: assertions fail because V2 metadata is absent.

- [ ] **Step 3: Add the migration and metadata mirror**

The migration must add the four `user_profile` columns, create `user_topic_profile` with non-null score/count defaults, JSONB `{}` evidence counts, foreign keys to `app_user` and `topic`, a composite primary key, and `idx_user_topic_profile_user`. Downgrade drops the table, then the four columns.

```python
op.add_column("user_profile", sa.Column("profile_v2_evidence_count", sa.Integer(), server_default="0", nullable=False))
op.add_column("user_profile", sa.Column("profile_v2_last_event_ts", sa.BigInteger()))
op.add_column("user_profile", sa.Column("profile_reset_before_ts", sa.BigInteger()))
op.add_column("user_profile", sa.Column("profile_v2_updated_at", sa.DateTime(timezone=True)))
op.create_table(
    "user_topic_profile",
    sa.Column("user_id", sa.BigInteger(), nullable=False),
    sa.Column("topic_id", sa.BigInteger(), nullable=False),
    sa.Column("short_positive_score", sa.DOUBLE_PRECISION(), server_default="0", nullable=False),
    sa.Column("short_negative_score", sa.DOUBLE_PRECISION(), server_default="0", nullable=False),
    sa.Column("long_positive_score", sa.DOUBLE_PRECISION(), server_default="0", nullable=False),
    sa.Column("long_negative_score", sa.DOUBLE_PRECISION(), server_default="0", nullable=False),
    sa.Column("positive_evidence_count", sa.Integer(), server_default="0", nullable=False),
    sa.Column("negative_evidence_count", sa.Integer(), server_default="0", nullable=False),
    sa.Column("evidence_counts_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column("last_signal_type", sa.String(32)),
    sa.Column("last_event_ts", sa.BigInteger(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    sa.ForeignKeyConstraint(["user_id"], ["app_user.user_id"], name="fk_user_topic_profile_user"),
    sa.ForeignKeyConstraint(["topic_id"], ["topic.topic_id"], name="fk_user_topic_profile_topic"),
    sa.PrimaryKeyConstraint("user_id", "topic_id", name="pk_user_topic_profile"),
)
```

- [ ] **Step 4: Verify metadata plus upgrade/downgrade tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alembic_schema.py -q`

- [ ] **Step 5: Commit Task 2**

```powershell
git add alembic/versions/20260816_0003_user_profile_v2.py backend/app/db/schema.py tests/test_alembic_schema.py
git commit -m "feat: add profile v2 database schema"
```

### Task 3: V2 projection DAO and explainable read model

**Files:**
- Create: `backend/app/repositories/profile_v2_dao.py`
- Modify: `backend/app/schemas/profile.py`
- Modify: `backend/app/config.py`
- Test: `tests/test_profile_v2_dao.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing DAO tests with recording fake connections**

Cover: one user-level evidence increment per event, multi-topic topic counts, pre-reset skip, per-topic late-event skip, read-time decay without UPDATE, ±0.01 filtering, top-10 per polarity, and topic display names.

```python
updated = apply_profile_v2_event(
    connection,
    user_id=7,
    event_type="upvote",
    event_ts=1_000,
    topic_strengths={10: 2.0, 20: 2.0},
    config=ProfileSignalConfig(short_half_life_seconds=21_600, long_half_life_seconds=2_592_000, long_term_factor=.25),
)
assert updated is True
assert connection.user_profile["profile_v2_evidence_count"] == 1
assert connection.topic_rows[10]["positive_evidence_count"] == 1
assert connection.topic_rows[20]["positive_evidence_count"] == 1
```

- [ ] **Step 2: Run DAO tests and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_v2_dao.py tests/test_config.py -q`

- [ ] **Step 3: Implement settings, schemas, projection, read, and reset DAO functions**

Add settings defaults: enabled `False`, short half-life `21_600`, long half-life `2_592_000`, long factor `0.25`, boost `0.10`.

Add schemas `ProfileTopicEvidence`, `ProfileTermLayer`, and `ProfileResponse` with the exact API fields from the spec. The DAO control flow is:

```python
def apply_profile_v2_event(connection: Any, *, user_id: int, event_type: str,
                           event_ts: int, topic_strengths: Mapping[int, float],
                           config: ProfileSignalConfig) -> bool:
    user_state = fetch_profile_v2_user_state(connection, user_id=user_id, for_update=True)
    reset_before = user_state.get("profile_reset_before_ts")
    if reset_before is not None and event_ts <= int(reset_before):
        return False
    updated = 0
    for topic_id, strength in sorted(topic_strengths.items()):
        current = fetch_topic_profile_state(
            connection, user_id=user_id, topic_id=topic_id, for_update=True
        )
        projected = project_topic_signal(
            current, signal=strength, event_type=event_type, event_ts=event_ts,
            short_half_life_seconds=config.short_half_life_seconds,
            long_half_life_seconds=config.long_half_life_seconds,
            long_term_factor=config.long_term_factor,
        )
        if projected is None:
            continue
        upsert_topic_profile_state(
            connection, user_id=user_id, topic_id=topic_id, state=projected
        )
        updated += 1
    if updated:
        increment_profile_v2_evidence(
            connection, user_id=user_id, event_ts=event_ts
        )
    return updated > 0

def load_profile_v2(connection: Any, *, user_id: int, now_ts: int,
                    config: ProfileSignalConfig) -> ProfileResponse:
    user_state = fetch_profile_v2_user_state(connection, user_id=user_id)
    rows = load_topic_profile_rows(connection, user_id=user_id)
    decayed = [decayed_topic_state(topic_state_from_row(row), now_ts=now_ts,
                                  short_half_life_seconds=config.short_half_life_seconds,
                                  long_half_life_seconds=config.long_half_life_seconds)
               for row in rows]
    return profile_response_from_states(user_state, rows, decayed)

def reset_profile_projections(connection: Any, *, user_id: int, reset_ts: int) -> None:
    profile = fetch_profile_v2_user_state(connection, user_id=user_id, for_update=True)
    seed = load_profile_seed(connection, seed_key=str(profile["cold_start_seed_key"]))
    restore_v1_profile_from_seed(connection, user_id=user_id, seed=seed, reset_ts=reset_ts)
    delete_topic_profile_rows(connection, user_id=user_id)
```

Define every helper named above in the same DAO file. SQL must use `%s` parameters, explicit column lists with `FOR UPDATE`, and an `INSERT INTO user_topic_profile` statement containing all score/count fields followed by `ON CONFLICT (user_id, topic_id) DO UPDATE`. Reads must contain no INSERT/UPDATE/DELETE.

- [ ] **Step 4: Run DAO/config tests until GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_v2_dao.py tests/test_config.py -q`

- [ ] **Step 5: Commit Task 3**

```powershell
git add backend/app/config.py backend/app/schemas/profile.py backend/app/repositories/profile_v2_dao.py tests/test_profile_v2_dao.py tests/test_config.py
git commit -m "feat: add profile v2 projection repository"
```

### Task 4: Transactional consumer integration and metrics

**Files:**
- Modify: `backend/app/events/consumer.py`
- Modify: `backend/app/observability.py`
- Test: `tests/test_event_stream.py`
- Test: `tests/test_postgres_smoke.py`

- [ ] **Step 1: Add failing tests for each projected and skipped event**

Tests assert exact strengths, search query-only topics at 50%, `feed_impression/detail_view/share` log-only behavior, sub-10-second dwell skip, downvote negative projection, duplicate idempotency, reset cutoff, and rollback when V2 UPSERT fails.

- [ ] **Step 2: Run focused consumer tests and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_event_stream.py tests/test_postgres_smoke.py -q`

- [ ] **Step 3: Integrate V2 after each event is durably recorded**

Use one helper that derives topic strengths and calls `apply_profile_v2_event` only when `profile_v2_enabled` is true. Keep the call inside the existing `begin/commit` block. For `search_result_click`, article topics receive `1.25`; query-only topics receive `0.625`; overlaps receive `1.25`. A V2 exception propagates so the existing rollback/retry/DLQ path remains authoritative.

- [ ] **Step 4: Add and increment metrics**

Define the five metric families named in the spec. Observe projection duration around the DAO call, count updated event types, and count `pre_reset`/`out_of_order` skips separately.

- [ ] **Step 5: Verify focused and existing event tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_event_stream.py tests/test_event_track_route.py tests/test_postgres_smoke.py -q`

- [ ] **Step 6: Commit Task 4**

```powershell
git add backend/app/events/consumer.py backend/app/observability.py tests/test_event_stream.py tests/test_postgres_smoke.py
git commit -m "feat: project profile v2 from user events"
```

### Task 5: Formal session profile and reset APIs

**Files:**
- Create: `backend/app/routers/profile.py`
- Modify: `backend/app/repositories/base.py`
- Modify: `backend/app/repositories/postgres.py`
- Modify: `backend/app/repositories/unwired.py`
- Modify: `backend/app/services/profile.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/errors.py`
- Test: `tests/test_profile_routes.py`

- [ ] **Step 1: Write failing route tests**

Cover missing session `401`, own-session identity with no accepted `user_id`, initialized response, `PROFILE_NOT_INITIALIZED` `404`, reset success, missing seed `503`, and unchanged `/debug/profile?user_id=` behavior.

```python
@router.get("", response_model=ProfileResponse)
def get_profile(current_user: AuthenticatedUser = Depends(get_current_user),
                service: ProfileService = Depends(get_profile_service)) -> ProfileResponse:
    return service.get_profile(current_user.user_id)


@router.post("/reset", response_model=ProfileResponse)
def reset_profile(current_user: AuthenticatedUser = Depends(get_current_user),
                  service: ProfileService = Depends(get_profile_service)) -> ProfileResponse:
    return service.reset_profile(current_user.user_id)
```

- [ ] **Step 2: Run route tests and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_routes.py -q`

- [ ] **Step 3: Implement repository/service/router methods and typed errors**

`PostgresRuntimeRepository.reset_profile` begins once, calls `reset_profile_projections`, commits, then performs a fresh read. Roll back any exception. Register `profile_router` without the research-mode auth dependency because its own handlers always require `get_current_user`.

- [ ] **Step 4: Verify API and legacy debug tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_routes.py tests/test_auth_routes.py tests/test_unwired_contract.py -q`

- [ ] **Step 5: Commit Task 5**

```powershell
git add backend/app/routers/profile.py backend/app/repositories/base.py backend/app/repositories/postgres.py backend/app/repositories/unwired.py backend/app/services/profile.py backend/app/main.py backend/app/errors.py tests/test_profile_routes.py
git commit -m "feat: add authenticated profile v2 APIs"
```

### Task 6: Opt-in `profile_v2` feed experiment

**Files:**
- Modify: `backend/app/schemas/feed.py`
- Modify: `backend/app/repositories/postgres.py`
- Modify: `backend/app/repositories/base.py`
- Modify: `backend/app/repositories/unwired.py`
- Test: `tests/test_profile_v2_feed.py`
- Test: `tests/test_unwired_contract.py`

- [ ] **Step 1: Write failing score, fallback, and arm contract tests**

Assert `profile_v2` is accepted, default scores are byte-for-byte unchanged, positive V2 topics add recall, negative topics only rerank, empty V2 matches default ordering, and SQL read failure rolls back to a savepoint before V1 continues.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_v2_feed.py tests/test_unwired_contract.py -q`

- [ ] **Step 3: Implement experiment scoring**

Add optional `profile_v2_score` to `FeedItemScores`. For the arm only, read decayed topic scores inside `SAVEPOINT profile_v2_read`; on query error execute `ROLLBACK TO SAVEPOINT profile_v2_read`, increment fallback metric, and use an empty map. Merge positive top-10 topics into recall. Add `profile_v2_boost * sum(topic_scores)` to each existing final score and preserve the existing tie breaker.

- [ ] **Step 4: Verify feed regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_v2_feed.py tests/test_mmr.py tests/test_als_recall.py tests/test_unwired_contract.py -q`

- [ ] **Step 5: Commit Task 6**

```powershell
git add backend/app/schemas/feed.py backend/app/repositories/postgres.py backend/app/repositories/base.py backend/app/repositories/unwired.py tests/test_profile_v2_feed.py tests/test_unwired_contract.py
git commit -m "feat: add profile v2 feed experiment arm"
```

### Task 7: Deterministic rebuild CLI

**Files:**
- Create: `scripts/rebuild_profile_v2.py`
- Test: `tests/test_rebuild_profile_v2.py`

- [ ] **Step 1: Write failing CLI and replay tests**

Cover exactly-one-of `--user-id/--all`, dry-run counts, `(user_id,event_ts,event_id)` ordering, repeatability, per-user rollback, and reset cutoff filtering.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rebuild_profile_v2.py -q`

- [ ] **Step 3: Implement CLI using the production signal/DAO functions**

The CLI may adapt stored event rows into `UserEventMessage`, but must call the same topic derivation and `apply_profile_v2_event` functions used online. Dry-run performs SELECTs only. Live mode uses one transaction per user.

- [ ] **Step 4: Verify CLI tests and help output**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rebuild_profile_v2.py -q`

Run: `.venv/Scripts/python.exe scripts/rebuild_profile_v2.py --help`

- [ ] **Step 5: Commit Task 7**

```powershell
git add scripts/rebuild_profile_v2.py tests/test_rebuild_profile_v2.py
git commit -m "feat: add profile v2 rebuild command"
```

### Task 8: Formal profile panel and reset UX

**Files:**
- Create: `product-frontend/src/components/ProfilePanel.tsx`
- Create: `product-frontend/src/components/ProfilePanel.test.tsx`
- Modify: `product-frontend/src/api/types.ts`
- Modify: `product-frontend/src/api/client.ts`
- Modify: `product-frontend/src/components/RightRail.tsx`
- Modify: `product-frontend/src/styles/global.css`
- Test: `product-frontend/src/components/ProfileDebugPanel.test.tsx`

- [ ] **Step 1: Write failing component and API tests**

Cover confidence/status, short/long positive topics, reduced topics, localized evidence counts, top-5 expansion, empty state, two-step reset confirmation, pending/error recovery, current-user formal endpoint, and alternate demo debug endpoint.

- [ ] **Step 2: Run tests and verify RED**

Run: `npm test -- src/components/ProfilePanel.test.tsx src/components/ProfileDebugPanel.test.tsx`

- [ ] **Step 3: Add typed client functions and ProfilePanel**

```typescript
export function getProfile(): Promise<ProfileResponse> {
  return request<ProfileResponse>("/profile");
}

export function resetProfile(): Promise<ProfileResponse> {
  return request<ProfileResponse>("/profile/reset", { method: "POST" });
}
```

Generate explanations locally from `signal_counts` and `last_signal_type`; never render server-provided prose. Reset must require a first click to reveal confirmation and a second click to submit.

- [ ] **Step 4: Switch RightRail by identity**

Use `useAuth().user` and `usePersona().selectedPersona`: render `ProfilePanel` when IDs match, otherwise retain `ProfileDebugPanel` for the selected demo persona. After reset, refresh the panel and invoke the existing feed refresh callback.

- [ ] **Step 5: Verify focused frontend tests and build**

Run: `npm test -- src/components/ProfilePanel.test.tsx src/components/ProfileDebugPanel.test.tsx src/pages/FeedPage.test.tsx`

Run: `npm run build`

- [ ] **Step 6: Commit Task 8**

```powershell
git add product-frontend/src/api product-frontend/src/components/ProfilePanel.tsx product-frontend/src/components/ProfilePanel.test.tsx product-frontend/src/components/RightRail.tsx product-frontend/src/styles/global.css product-frontend/src/components/ProfileDebugPanel.test.tsx
git commit -m "feat: show explainable profile v2 panel"
```

### Task 9: Visible dwell feedback

**Files:**
- Create: `product-frontend/src/profile/visibleDwell.ts`
- Create: `product-frontend/src/profile/visibleDwell.test.ts`
- Modify: `product-frontend/src/pages/ArticleDetailPage.tsx`
- Create or modify: `product-frontend/src/pages/ArticleDetailPage.test.tsx`

- [ ] **Step 1: Write failing timer tests**

Use a fake clock to prove visible accumulation, hidden pause, at-most-once send on unmount/pagehide, stable event ID, and non-blocking rejected delivery.

- [ ] **Step 2: Run timer tests and verify RED**

Run: `npm test -- src/profile/visibleDwell.test.ts src/pages/ArticleDetailPage.test.tsx`

- [ ] **Step 3: Implement the pure accumulator and page integration**

`VisibleDwellAccumulator` stores accumulated visible milliseconds, the start timestamp when visible, and a sent flag. The page uses a stable ID of `dwell-${userId}:${articleId}:${routeLoadId}`, listens to `visibilitychange` and `pagehide`, and submits only when total visible time is at least 10 seconds.

- [ ] **Step 4: Verify tests and build**

Run: `npm test -- src/profile/visibleDwell.test.ts src/pages/ArticleDetailPage.test.tsx`

Run: `npm run build`

- [ ] **Step 5: Commit Task 9**

```powershell
git add product-frontend/src/profile product-frontend/src/pages/ArticleDetailPage.tsx product-frontend/src/pages/ArticleDetailPage.test.tsx
git commit -m "feat: track visible article dwell feedback"
```

### Task 10: Full verification, docs, and rollout evidence

**Files:**
- Modify: `.env.example`
- Modify: `docs/api_contract.md`
- Modify: `backend/README.md`
- Modify: `README.md`
- Modify or create: evaluation output only when generated by existing scripts.

- [ ] **Step 1: Document all five V2 settings and API contracts**

Document defaults, `profile_v2` opt-in semantics, reset audit preservation, error codes, rebuild examples, and the fact that MIND validates mechanisms rather than real downvote/dwell uplift.

- [ ] **Step 2: Run complete backend quality gates**

Run: `.venv/Scripts/python.exe -m ruff check backend tests scripts`

Run: `.venv/Scripts/python.exe -m mypy backend/app`

Run: `.venv/Scripts/python.exe -m pytest -q`

Expected: all non-PostgreSQL tests pass; configured PostgreSQL/Kafka markers remain governed by existing environment skips.

- [ ] **Step 3: Run complete frontend gates**

Run: `npm test`

Run: `npm run build`

Expected: all Vitest files pass and TypeScript/Vite build exits zero.

- [ ] **Step 4: Run migration and opt-in smoke tests when PostgreSQL is configured**

Run: `.venv/Scripts/python.exe -m pytest -m postgres tests/test_alembic_schema.py tests/test_postgres_smoke.py tests/test_profile_routes.py tests/test_profile_v2_feed.py -q`

If `NEWSREC_DATABASE_URL` is absent, record the skip explicitly; do not claim database integration was executed.

- [ ] **Step 5: Inspect exact diff and commit documentation**

```powershell
git status --short
git diff --check
git add .env.example README.md backend/README.md docs/api_contract.md
git commit -m "docs: document profile v2 rollout"
```

- [ ] **Step 6: Finish the branch**

Use `finishing-a-development-branch` only after fresh verification evidence and present merge/PR/keep-worktree options to the user.
