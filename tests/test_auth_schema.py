from pathlib import Path


def test_auth_table_is_dropped_before_referenced_app_user() -> None:
    schema = Path("sql/schema.sql").read_text(encoding="utf-8")

    assert schema.index("DROP TABLE IF EXISTS user_account") < schema.index(
        "DROP TABLE IF EXISTS app_user"
    )


def test_auth_uses_sequence_without_altering_existing_user_primary_key() -> None:
    schema = Path("sql/schema.sql").read_text(encoding="utf-8")
    migration = Path("sql/migrations/001_auth.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE auth_user_id_sequence" in schema
    assert "CREATE TABLE IF NOT EXISTS auth_user_id_sequence" in migration
    assert "MAX(user_id)" in migration
    assert "ALTER TABLE app_user" not in migration
