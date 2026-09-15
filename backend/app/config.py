from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, cast

from dotenv import dotenv_values

EventMode = Literal["sync_postgres", "kafka_dual_write", "kafka_async"]
SearchRetrievalMode = Literal["lexical_v1", "hybrid_v1"]
_DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"
# Process environment variables still take precedence in _env_optional().
_DOTENV_VALUES: Mapping[str, str | None] = dotenv_values(_DOTENV_PATH)


def parse_event_mode(value: str) -> EventMode:
    normalized = value.strip().lower()
    if normalized in {"sync_postgres", "kafka_dual_write", "kafka_async"}:
        return cast(EventMode, normalized)
    raise ValueError(
        "NEWSREC_EVENT_MODE must be one of: sync_postgres, kafka_dual_write, kafka_async"
    )


def parse_search_retrieval_mode(value: str) -> SearchRetrievalMode:
    normalized = value.strip().lower()
    if normalized in {"lexical_v1", "hybrid_v1"}:
        return cast(SearchRetrievalMode, normalized)
    raise ValueError("NEWSREC_SEARCH_RETRIEVAL_MODE must be lexical_v1 or hybrid_v1")


def _env_optional(name: str) -> str | None:
    for source in (os.environ, _DOTENV_VALUES):
        value = source.get(name)
        if value is not None:
            return value
    return None


def _env(name: str, default: str) -> str:
    value = _env_optional(name)
    if value is not None:
        return value
    return default


def _env_bool(name: str, default: str) -> bool:
    return _env(name, default).lower() in ("1", "true", "yes")


def _env_positive_int(name: str, default: str) -> int:
    value = int(_env(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def environment_value(name: str, default: str = "") -> str:
    return _env(name, default)


def _auth_secret_key() -> str:
    secret = _env("NEWSREC_AUTH_SECRET_KEY", "").strip()
    if secret:
        return secret
    configured_path = _env("NEWSREC_AUTH_SECRET_KEY_FILE", "").strip()
    if not configured_path:
        return ""
    path = Path(configured_path).expanduser()
    if not path.is_absolute():
        path = _DOTENV_PATH.parent / path
    try:
        secret = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"Unable to read NEWSREC_AUTH_SECRET_KEY_FILE {path}: {exc}") from exc
    if not secret:
        raise ValueError(f"NEWSREC_AUTH_SECRET_KEY_FILE is empty: {path}")
    return secret


def _normalized_source_fingerprint(normalized_dir: str) -> str | None:
    path = Path(normalized_dir) / "normalization_manifest.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = str(payload.get("normalized_fingerprint") or "").strip()
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid normalization manifest {path}: {exc}") from exc
    return value or None


@dataclass(frozen=True)
class Settings:
    app_name: str = "NewsIntentRec Backend"
    app_version: str = "0.1.0"
    default_demo_user_id: int = 7001
    database_url: str = ""
    auth_secret_key: str = ""
    auth_access_token_minutes: int = 60
    auth_cookie_name: str = "newsrec_session"
    auth_cookie_secure: bool = False
    environment: str = "development"
    allow_unauthenticated_research_api: bool = False
    auth_rate_limit_attempts: int = 10
    auth_rate_limit_window_seconds: int = 60
    mind_normalized_dir: str = "build/mind_normalized"
    live_news_enabled: bool = False
    live_topics_required: bool = False
    live_news_collector_enabled: bool = False
    live_news_source_config: str = "config/live_news_sources.json"
    live_news_poll_interval_seconds: int = 60
    live_news_replay_minutes: int = 60
    live_news_max_age_hours: int = 72
    live_news_collector_metrics_port: int = 9103
    live_content_worker_enabled: bool = False
    local_research_fulltext_enabled: bool = False
    guardian_api_key: str = ""
    live_content_connect_timeout_seconds: int = 5
    live_content_read_timeout_seconds: int = 15
    live_content_max_response_bytes: int = 2 * 1024 * 1024
    live_content_worker_batch_size: int = 20
    live_content_worker_concurrency: int = 4
    postgres_connect_timeout_seconds: int = 5
    postgres_pool_min_size: int = 1
    postgres_pool_max_connections: int = 10
    request_id_prefix: str = "newsrec"
    search_query_behavior_delta: float = 1.0
    recommendation_click_behavior_delta: float = 3.0
    search_result_click_behavior_delta: float = 5.0
    profile_topic_decay: float = 0.92
    profile_v2_enabled: bool = True
    profile_v2_short_half_life_seconds: int = 21_600
    profile_v2_long_half_life_seconds: int = 2_592_000
    profile_v2_long_term_factor: float = 0.25
    profile_v2_boost: float = 0.10
    recommendation_click_topic_delta: float = 0.08
    search_result_click_topic_delta: float = 0.12
    search_result_overlap_topic_delta: float = 0.2
    cold_start_alpha_floor: float = 0.1
    cold_start_alpha_ceiling: float = 0.95
    cold_start_behavior_score_scale: float = 30.0
    cold_start_default_seed_key: str = "cold_start_default"
    als_recall_top_k: int = 200
    als_recall_enabled: bool = True
    search_retrieval_mode: SearchRetrievalMode = "hybrid_v1"
    search_index_dir: str = "build/mind_search/full"
    search_source_fingerprint: str | None = None
    event_mode: EventMode = "sync_postgres"
    kafka_bootstrap_servers: str = "127.0.0.1:9092"
    kafka_client_id: str = "newsrec-api"
    kafka_profile_group_id: str = "newsrec-profile-consumer"
    kafka_raw_events_topic: str = "newsrec.events.raw"
    kafka_training_topic: str = "newsrec.training.interactions"
    kafka_dlq_topic: str = "newsrec.events.dlq"
    # Enable only after docs/operations/kafka-source-partition-key-rollout.md.
    kafka_source_partition_keys_enabled: bool = False
    kafka_producer_linger_ms: int = 5
    kafka_producer_flush_timeout_seconds: float = 10.0
    kafka_consumer_max_retries: int = 5
    kafka_consumer_retry_backoff_seconds: float = 1.0
    outbox_batch_size: int = 100
    outbox_max_attempts: int = 10
    outbox_poll_interval_seconds: float = 1.0
    outbox_stale_after_seconds: int = 60
    sponsored_enabled: bool = True
    sponsored_slots: tuple[int, ...] = (3, 8)
    sponsored_pacing_headroom_seconds: int = 3600
    readiness_timeout_seconds: float = 2.0
    readiness_outbox_backlog_limit: int = 10000
    readiness_worker_heartbeat_max_age_seconds: int = 15
    readiness_outbox_oldest_pending_max_age_seconds: int = 30
    readiness_consumer_lag_limit: int = 1000
    consumer_metrics_port: int = 9101
    outbox_metrics_port: int = 9102
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:5174",
        "http://localhost:5174",
    )

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url.strip())

    @property
    def kafka_enabled(self) -> bool:
        return self.event_mode in {"kafka_dual_write", "kafka_async"}


def local_research_content_allowed(settings: Settings) -> bool:
    return settings.environment == "development" and settings.local_research_fulltext_enabled


def compute_alpha(behavior_score: float, settings: Settings) -> float:
    score = max(0.0, behavior_score)
    raw = score / (score + settings.cold_start_behavior_score_scale)
    span = settings.cold_start_alpha_ceiling - settings.cold_start_alpha_floor
    return settings.cold_start_alpha_floor + raw * span


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    mind_normalized_dir = _env("NEWSREC_MIND_NORMALIZED_DIR", "build/mind_normalized")
    return Settings(
        app_name=_env("NEWSREC_APP_NAME", "NewsIntentRec Backend"),
        app_version=_env("NEWSREC_APP_VERSION", "0.1.0"),
        default_demo_user_id=int(_env("NEWSREC_DEFAULT_DEMO_USER_ID", "7001")),
        database_url=_env("NEWSREC_DATABASE_URL", ""),
        auth_secret_key=_auth_secret_key(),
        auth_access_token_minutes=int(_env("NEWSREC_AUTH_ACCESS_TOKEN_MINUTES", "60")),
        auth_cookie_name=_env("NEWSREC_AUTH_COOKIE_NAME", "newsrec_session"),
        auth_cookie_secure=_env_bool("NEWSREC_AUTH_COOKIE_SECURE", "0"),
        environment=_env("NEWSREC_ENVIRONMENT", "development").strip().lower(),
        allow_unauthenticated_research_api=_env_bool(
            "NEWSREC_ALLOW_UNAUTHENTICATED_RESEARCH_API", "0"
        ),
        auth_rate_limit_attempts=int(_env("NEWSREC_AUTH_RATE_LIMIT_ATTEMPTS", "10")),
        auth_rate_limit_window_seconds=int(_env("NEWSREC_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")),
        mind_normalized_dir=mind_normalized_dir,
        live_news_enabled=_env_bool("NEWSREC_LIVE_NEWS_ENABLED", "0"),
        live_topics_required=_env_bool("NEWSREC_LIVE_TOPICS_REQUIRED", "0"),
        live_news_collector_enabled=_env_bool("NEWSREC_LIVE_NEWS_COLLECTOR_ENABLED", "0"),
        live_news_source_config=_env(
            "NEWSREC_LIVE_NEWS_SOURCE_CONFIG", "config/live_news_sources.json"
        ),
        live_news_poll_interval_seconds=int(_env("NEWSREC_LIVE_NEWS_POLL_INTERVAL_SECONDS", "60")),
        live_news_replay_minutes=int(_env("NEWSREC_LIVE_NEWS_REPLAY_MINUTES", "60")),
        live_news_max_age_hours=int(_env("NEWSREC_LIVE_NEWS_MAX_AGE_HOURS", "72")),
        live_news_collector_metrics_port=int(
            _env("NEWSREC_LIVE_NEWS_COLLECTOR_METRICS_PORT", "9103")
        ),
        live_content_worker_enabled=_env_bool("NEWSREC_LIVE_CONTENT_WORKER_ENABLED", "0"),
        local_research_fulltext_enabled=_env_bool("NEWSREC_LOCAL_RESEARCH_FULLTEXT_ENABLED", "0"),
        guardian_api_key=_env("NEWSREC_GUARDIAN_API_KEY", "").strip(),
        live_content_connect_timeout_seconds=_env_positive_int(
            "NEWSREC_LIVE_CONTENT_CONNECT_TIMEOUT_SECONDS", "5"
        ),
        live_content_read_timeout_seconds=_env_positive_int(
            "NEWSREC_LIVE_CONTENT_READ_TIMEOUT_SECONDS", "15"
        ),
        live_content_max_response_bytes=_env_positive_int(
            "NEWSREC_LIVE_CONTENT_MAX_RESPONSE_BYTES", str(2 * 1024 * 1024)
        ),
        live_content_worker_batch_size=_env_positive_int(
            "NEWSREC_LIVE_CONTENT_WORKER_BATCH_SIZE", "20"
        ),
        live_content_worker_concurrency=_env_positive_int(
            "NEWSREC_LIVE_CONTENT_WORKER_CONCURRENCY", "4"
        ),
        postgres_connect_timeout_seconds=int(_env("NEWSREC_POSTGRES_CONNECT_TIMEOUT_SECONDS", "5")),
        postgres_pool_min_size=int(_env("NEWSREC_POSTGRES_POOL_MIN_SIZE", "1")),
        postgres_pool_max_connections=int(_env("NEWSREC_POSTGRES_POOL_MAX_CONNECTIONS", "10")),
        request_id_prefix=_env("NEWSREC_REQUEST_ID_PREFIX", "newsrec"),
        search_query_behavior_delta=float(_env("NEWSREC_SEARCH_QUERY_BEHAVIOR_DELTA", "1.0")),
        recommendation_click_behavior_delta=float(
            _env("NEWSREC_RECOMMENDATION_CLICK_BEHAVIOR_DELTA", "3.0")
        ),
        search_result_click_behavior_delta=float(
            _env("NEWSREC_SEARCH_RESULT_CLICK_BEHAVIOR_DELTA", "5.0")
        ),
        profile_topic_decay=float(_env("NEWSREC_PROFILE_TOPIC_DECAY", "0.92")),
        profile_v2_enabled=_env_bool("NEWSREC_PROFILE_V2_ENABLED", "1"),
        profile_v2_short_half_life_seconds=int(
            _env("NEWSREC_PROFILE_V2_SHORT_HALF_LIFE_SECONDS", "21600")
        ),
        profile_v2_long_half_life_seconds=int(
            _env("NEWSREC_PROFILE_V2_LONG_HALF_LIFE_SECONDS", "2592000")
        ),
        profile_v2_long_term_factor=float(_env("NEWSREC_PROFILE_V2_LONG_TERM_FACTOR", "0.25")),
        profile_v2_boost=float(_env("NEWSREC_PROFILE_V2_BOOST", "0.10")),
        recommendation_click_topic_delta=float(
            _env("NEWSREC_RECOMMENDATION_CLICK_TOPIC_DELTA", "0.08")
        ),
        search_result_click_topic_delta=float(
            _env("NEWSREC_SEARCH_RESULT_CLICK_TOPIC_DELTA", "0.12")
        ),
        search_result_overlap_topic_delta=float(
            _env("NEWSREC_SEARCH_RESULT_OVERLAP_TOPIC_DELTA", "0.2")
        ),
        cold_start_alpha_floor=float(_env("NEWSREC_COLD_START_ALPHA_FLOOR", "0.1")),
        cold_start_alpha_ceiling=float(_env("NEWSREC_COLD_START_ALPHA_CEILING", "0.95")),
        cold_start_behavior_score_scale=float(
            _env("NEWSREC_COLD_START_BEHAVIOR_SCORE_SCALE", "30.0")
        ),
        cold_start_default_seed_key=_env(
            "NEWSREC_COLD_START_DEFAULT_SEED_KEY", "cold_start_default"
        ),
        als_recall_top_k=int(_env("NEWSREC_ALS_RECALL_TOP_K", "200")),
        als_recall_enabled=_env_bool("NEWSREC_ALS_RECALL_ENABLED", "1"),
        search_retrieval_mode=parse_search_retrieval_mode(
            _env("NEWSREC_SEARCH_RETRIEVAL_MODE", "hybrid_v1")
        ),
        search_index_dir=_env("NEWSREC_SEARCH_INDEX_DIR", "build/mind_search/full"),
        search_source_fingerprint=_normalized_source_fingerprint(mind_normalized_dir),
        event_mode=parse_event_mode(_env("NEWSREC_EVENT_MODE", "sync_postgres")),
        kafka_bootstrap_servers=_env(
            "NEWSREC_KAFKA_BOOTSTRAP_SERVERS",
            "127.0.0.1:9092",
        ),
        kafka_client_id=_env("NEWSREC_KAFKA_CLIENT_ID", "newsrec-api"),
        kafka_profile_group_id=_env(
            "NEWSREC_KAFKA_PROFILE_GROUP_ID",
            "newsrec-profile-consumer",
        ),
        kafka_raw_events_topic=_env(
            "NEWSREC_KAFKA_RAW_EVENTS_TOPIC",
            "newsrec.events.raw",
        ),
        kafka_training_topic=_env(
            "NEWSREC_KAFKA_TRAINING_TOPIC",
            "newsrec.training.interactions",
        ),
        kafka_dlq_topic=_env("NEWSREC_KAFKA_DLQ_TOPIC", "newsrec.events.dlq"),
        kafka_source_partition_keys_enabled=_env_bool(
            "NEWSREC_KAFKA_SOURCE_PARTITION_KEYS_ENABLED", "0"
        ),
        kafka_producer_linger_ms=int(_env("NEWSREC_KAFKA_PRODUCER_LINGER_MS", "5")),
        kafka_producer_flush_timeout_seconds=float(
            _env("NEWSREC_KAFKA_PRODUCER_FLUSH_TIMEOUT_SECONDS", "10")
        ),
        kafka_consumer_max_retries=int(_env("NEWSREC_KAFKA_CONSUMER_MAX_RETRIES", "5")),
        kafka_consumer_retry_backoff_seconds=float(
            _env("NEWSREC_KAFKA_CONSUMER_RETRY_BACKOFF_SECONDS", "1")
        ),
        outbox_batch_size=int(_env("NEWSREC_OUTBOX_BATCH_SIZE", "100")),
        outbox_max_attempts=int(_env("NEWSREC_OUTBOX_MAX_ATTEMPTS", "10")),
        outbox_poll_interval_seconds=float(_env("NEWSREC_OUTBOX_POLL_INTERVAL_SECONDS", "1")),
        outbox_stale_after_seconds=int(_env("NEWSREC_OUTBOX_STALE_AFTER_SECONDS", "60")),
        sponsored_enabled=_env_bool("NEWSREC_SPONSORED_ENABLED", "1"),
        sponsored_slots=tuple(
            int(value.strip())
            for value in _env("NEWSREC_SPONSORED_SLOTS", "3,8").split(",")
            if value.strip()
        ),
        sponsored_pacing_headroom_seconds=int(
            _env("NEWSREC_SPONSORED_PACING_HEADROOM_SECONDS", "3600")
        ),
        readiness_timeout_seconds=float(_env("NEWSREC_READINESS_TIMEOUT_SECONDS", "2")),
        readiness_outbox_backlog_limit=int(_env("NEWSREC_READINESS_OUTBOX_BACKLOG_LIMIT", "10000")),
        readiness_worker_heartbeat_max_age_seconds=int(
            _env("NEWSREC_READINESS_WORKER_HEARTBEAT_MAX_AGE_SECONDS", "15")
        ),
        readiness_outbox_oldest_pending_max_age_seconds=int(
            _env("NEWSREC_READINESS_OUTBOX_OLDEST_PENDING_MAX_AGE_SECONDS", "30")
        ),
        readiness_consumer_lag_limit=int(_env("NEWSREC_READINESS_CONSUMER_LAG_LIMIT", "1000")),
        consumer_metrics_port=int(_env("NEWSREC_CONSUMER_METRICS_PORT", "9101")),
        outbox_metrics_port=int(_env("NEWSREC_OUTBOX_METRICS_PORT", "9102")),
        cors_origins=tuple(
            origin.strip()
            for origin in _env(
                "NEWSREC_CORS_ORIGINS",
                "http://127.0.0.1:5174,http://localhost:5174",
            ).split(",")
            if origin.strip()
        ),
    )
