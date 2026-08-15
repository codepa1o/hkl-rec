from __future__ import annotations

import json
import logging
from pathlib import Path


def test_project_dotenv_is_loaded_automatically(monkeypatch, tmp_path: Path):
    from backend.app import config

    monkeypatch.setattr(
        config,
        "_DOTENV_VALUES",
        {
            "NEWSREC_DATABASE_URL": "mysql://from-dotenv",
            "NEWSREC_SEARCH_RETRIEVAL_MODE": "lexical_v1",
        },
        raising=False,
    )
    monkeypatch.delenv("NEWSREC_DATABASE_URL", raising=False)
    monkeypatch.delenv("ZHIHUREC_DATABASE_URL", raising=False)
    monkeypatch.delenv("NEWSREC_SEARCH_RETRIEVAL_MODE", raising=False)
    monkeypatch.delenv("ZHIHUREC_SEARCH_RETRIEVAL_MODE", raising=False)
    config.get_settings.cache_clear()

    try:
        settings = config.get_settings()
    finally:
        config.get_settings.cache_clear()

    assert settings.database_url == "mysql://from-dotenv"
    assert settings.search_retrieval_mode == "lexical_v1"


def test_newsrec_environment_takes_precedence_and_reads_demo_user(
    monkeypatch,
    tmp_path: Path,
):
    from backend.app.config import get_settings

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    (seed_dir / "demo_user_profile_seed.json").write_text(
        json.dumps({"user_id": 42}),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWSREC_DEMO_SEED_DIR", str(seed_dir))
    monkeypatch.setenv("NEWSREC_DATABASE_URL", "mysql://new")
    monkeypatch.setenv("ZHIHUREC_DATABASE_URL", "mysql://legacy")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.app_name == "NewsIntentRec Backend"
    assert settings.database_url == "mysql://new"
    assert settings.default_demo_user_id == 42
    assert settings.request_id_prefix == "newsrec"


def test_legacy_environment_logs_deprecation(monkeypatch, caplog):
    from backend.app import config

    monkeypatch.delenv("NEWSREC_DATABASE_URL", raising=False)
    monkeypatch.setenv("ZHIHUREC_DATABASE_URL", "mysql://legacy")
    config._DEPRECATED_ENV_WARNINGS.clear()
    config.get_settings.cache_clear()

    with caplog.at_level(logging.WARNING):
        settings = config.get_settings()

    assert settings.database_url == "mysql://legacy"
    assert any(
        record.deprecated_env == "ZHIHUREC_DATABASE_URL"
        and record.replacement_env == "NEWSREC_DATABASE_URL"
        for record in caplog.records
    )


def test_explicit_demo_user_does_not_read_invalid_seed(monkeypatch, tmp_path: Path):
    from backend.app.config import get_settings

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    (seed_dir / "demo_user_profile_seed.json").write_text("{invalid", encoding="utf-8")
    monkeypatch.setenv("NEWSREC_DEMO_SEED_DIR", str(seed_dir))
    monkeypatch.setenv("NEWSREC_DEFAULT_DEMO_USER_ID", "99")
    get_settings.cache_clear()

    assert get_settings().default_demo_user_id == 99


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
