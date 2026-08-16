from __future__ import annotations

from pathlib import Path


def test_project_dotenv_is_loaded_automatically(monkeypatch, tmp_path: Path):
    from backend.app import config

    monkeypatch.setattr(
        config,
        "_DOTENV_VALUES",
        {
            "NEWSREC_DATABASE_URL": "postgresql://from-dotenv",
            "NEWSREC_SEARCH_RETRIEVAL_MODE": "lexical_v1",
        },
        raising=False,
    )
    monkeypatch.delenv("NEWSREC_DATABASE_URL", raising=False)
    monkeypatch.delenv("NEWSREC_SEARCH_RETRIEVAL_MODE", raising=False)
    config.get_settings.cache_clear()

    try:
        settings = config.get_settings()
    finally:
        config.get_settings.cache_clear()

    assert settings.database_url == "postgresql://from-dotenv"
    assert settings.search_retrieval_mode == "lexical_v1"


def test_newsrec_environment_reads_explicit_default_user(monkeypatch):
    from backend.app.config import get_settings

    monkeypatch.setenv("NEWSREC_DEFAULT_DEMO_USER_ID", "42")
    monkeypatch.setenv("NEWSREC_DATABASE_URL", "postgresql://new")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.app_name == "NewsIntentRec Backend"
    assert settings.database_url == "postgresql://new"
    assert settings.default_demo_user_id == 42
    assert settings.request_id_prefix == "newsrec"


def test_legacy_environment_is_not_read(monkeypatch):
    from backend.app import config

    monkeypatch.delenv("NEWSREC_DATABASE_URL", raising=False)
    monkeypatch.setenv("ZHIHUREC_DATABASE_URL", "mysql://legacy")
    monkeypatch.setattr(config, "_DOTENV_VALUES", {}, raising=False)
    config.get_settings.cache_clear()

    settings = config.get_settings()

    assert settings.database_url == ""


def test_normalized_manifest_sets_search_source_fingerprint(monkeypatch, tmp_path: Path):
    from backend.app.config import get_settings

    normalized_dir = tmp_path / "normalized"
    normalized_dir.mkdir()
    (normalized_dir / "normalization_manifest.json").write_text(
        '{"normalized_fingerprint":"fixture-fingerprint"}', encoding="utf-8"
    )
    monkeypatch.setenv("NEWSREC_MIND_NORMALIZED_DIR", str(normalized_dir))
    get_settings.cache_clear()

    assert get_settings().search_source_fingerprint == "fixture-fingerprint"


def test_auth_secret_can_be_loaded_from_file(monkeypatch, tmp_path: Path):
    from backend.app import config

    secret = "a" * 44
    secret_path = tmp_path / "auth-secret.txt"
    secret_path.write_text(secret + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "_DOTENV_VALUES", {}, raising=False)
    monkeypatch.delenv("NEWSREC_AUTH_SECRET_KEY", raising=False)
    monkeypatch.delenv("ZHIHUREC_AUTH_SECRET_KEY", raising=False)
    monkeypatch.setenv("NEWSREC_AUTH_SECRET_KEY_FILE", str(secret_path))
    config.get_settings.cache_clear()

    try:
        settings = config.get_settings()
    finally:
        config.get_settings.cache_clear()

    assert settings.auth_secret_key == secret


def test_profile_v2_settings_have_safe_mvp_defaults() -> None:
    from backend.app.config import Settings

    settings = Settings()

    assert settings.profile_v2_enabled is False
    assert settings.profile_v2_short_half_life_seconds == 21_600
    assert settings.profile_v2_long_half_life_seconds == 2_592_000
    assert settings.profile_v2_long_term_factor == 0.25
    assert settings.profile_v2_boost == 0.10


def test_profile_v2_settings_can_be_overridden_from_the_environment(monkeypatch) -> None:
    from backend.app.config import get_settings

    monkeypatch.setenv("NEWSREC_PROFILE_V2_ENABLED", "true")
    monkeypatch.setenv("NEWSREC_PROFILE_V2_SHORT_HALF_LIFE_SECONDS", "3600")
    monkeypatch.setenv("NEWSREC_PROFILE_V2_LONG_HALF_LIFE_SECONDS", "86400")
    monkeypatch.setenv("NEWSREC_PROFILE_V2_LONG_TERM_FACTOR", "0.4")
    monkeypatch.setenv("NEWSREC_PROFILE_V2_BOOST", "0.2")
    get_settings.cache_clear()

    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()

    assert settings.profile_v2_enabled is True
    assert settings.profile_v2_short_half_life_seconds == 3_600
    assert settings.profile_v2_long_half_life_seconds == 86_400
    assert settings.profile_v2_long_term_factor == 0.4
    assert settings.profile_v2_boost == 0.2
