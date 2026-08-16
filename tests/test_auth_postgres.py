from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from backend.app.auth.repository import PostgresAuthRepository
from backend.app.auth.security import hash_password
from backend.app.config import Settings
from backend.app.repositories.connection import connect, parse_database_url

pytestmark = pytest.mark.postgres


def _database_url() -> str:
    value = os.environ.get("NEWSREC_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("NEWSREC_DATABASE_URL not set")
    return value


def test_alembic_upgrade_is_idempotent_and_auth_tables_are_at_head() -> None:
    config = Config("alembic.ini")
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    assert expected_head is not None

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    connection = connect(parse_database_url(_database_url()))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone()["version_num"] == expected_head
            cursor.execute(
                "SELECT next_user_id FROM auth_user_id_sequence "
                "WHERE sequence_key = 'registered_user'"
            )
            assert int(cursor.fetchone()["next_user_id"]) >= 1_000_000_000
    finally:
        connection.close()


def test_concurrent_registration_allocates_unique_users_and_profiles_atomically() -> None:
    database_url = _database_url()
    settings = Settings(database_url=database_url, postgres_pool_max_connections=8)
    suffix = uuid.uuid4().hex

    def register(index: int) -> int:
        repository = PostgresAuthRepository(settings)
        try:
            account = repository.create_account(
                f"auth-integration-{suffix}-{index}@example.com",
                f"Auth Integration {index}",
                hash_password("integration-password"),
            )
            return account.user_id
        finally:
            repository.close()

    user_ids: list[int] = []
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            user_ids = list(executor.map(register, range(4)))

        assert len(set(user_ids)) == 4
        assert max(user_ids) - min(user_ids) == 3

        connection = connect(parse_database_url(database_url))
        try:
            with connection.cursor() as cursor:
                placeholders = ",".join(["%s"] * len(user_ids))
                cursor.execute(
                    f"SELECT u.user_id, ua.user_id AS account_id, up.user_id AS profile_id "
                    f"FROM app_user u JOIN user_account ua ON ua.user_id = u.user_id "
                    f"JOIN user_profile up ON up.user_id = u.user_id "
                    f"WHERE u.user_id IN ({placeholders})",
                    tuple(user_ids),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        assert {int(row["user_id"]) for row in rows} == set(user_ids)
        assert all(row["user_id"] == row["account_id"] == row["profile_id"] for row in rows)
    finally:
        if user_ids:
            connection = connect(parse_database_url(database_url))
            try:
                with connection.transaction(), connection.cursor() as cursor:
                    placeholders = ",".join(["%s"] * len(user_ids))
                    cursor.execute(
                        f"DELETE FROM user_profile WHERE user_id IN ({placeholders})",
                        tuple(user_ids),
                    )
                    cursor.execute(
                        f"DELETE FROM user_account WHERE user_id IN ({placeholders})",
                        tuple(user_ids),
                    )
                    cursor.execute(
                        f"DELETE FROM app_user WHERE user_id IN ({placeholders})",
                        tuple(user_ids),
                    )
            finally:
                connection.close()
