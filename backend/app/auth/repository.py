from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from psycopg.errors import UniqueViolation

from backend.app.config import Settings
from backend.app.errors import RepositoryNotReadyError
from backend.app.repositories.connection import (
    PostgresConnectionPool,
    parse_database_url,
    transaction,
)


@dataclass(frozen=True)
class AccountRecord:
    user_id: int
    email: str
    display_name: str
    password_hash: str
    is_active: bool


class DuplicateEmailError(ValueError):
    """Raised when a normalized email address is already registered."""


class AuthRepository(Protocol):
    def create_account(
        self,
        email: str,
        display_name: str,
        password_hash: str,
    ) -> AccountRecord: ...

    def get_by_email(self, email: str) -> AccountRecord | None: ...

    def get_by_user_id(self, user_id: int) -> AccountRecord | None: ...

    def is_demo_user(self, user_id: int) -> bool: ...

    def close(self) -> None: ...


class PostgresAuthRepository:
    def __init__(self, settings: Settings) -> None:
        if not settings.database_configured:
            raise RepositoryNotReadyError("authentication")
        self._pool = PostgresConnectionPool(
            parse_database_url(settings.database_url),
            connect_timeout=settings.postgres_connect_timeout_seconds,
            min_size=settings.postgres_pool_min_size,
            max_connections=settings.postgres_pool_max_connections,
        )
        self._cold_start_seed_key = settings.cold_start_default_seed_key

    def close(self) -> None:
        self._pool.close()

    @staticmethod
    def _record(row: dict[str, Any] | None) -> AccountRecord | None:
        if row is None:
            return None
        return AccountRecord(
            user_id=int(row["user_id"]),
            email=str(row["email"]),
            display_name=str(row["display_name"]),
            password_hash=str(row["password_hash"]),
            is_active=bool(row["is_active"]),
        )

    def create_account(self, email: str, display_name: str, password_hash: str) -> AccountRecord:
        connection = self._pool.connect()
        try:
            with transaction(connection), connection.cursor() as cursor:
                cursor.execute(
                    "SELECT next_user_id FROM auth_user_id_sequence "
                    "WHERE sequence_key = %s FOR UPDATE",
                    ("registered_user",),
                )
                sequence = cursor.fetchone()
                if sequence is None:
                    raise RepositoryNotReadyError("authentication user id sequence")
                user_id = int(sequence["next_user_id"])
                cursor.execute(
                    "UPDATE auth_user_id_sequence SET next_user_id = %s WHERE sequence_key = %s",
                    (user_id + 1, "registered_user"),
                )
                cursor.execute(
                    "INSERT INTO app_user "
                    "(user_id, display_name, register_ts, is_demo_user, source) "
                    "VALUES (%s, %s, EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)::BIGINT, "
                    "false, 'registered')",
                    (user_id, display_name),
                )
                cursor.execute(
                    "INSERT INTO user_account "
                    "(user_id, email, password_hash, is_active) VALUES (%s, %s, %s, true)",
                    (user_id, email, password_hash),
                )
                cursor.execute(
                    "INSERT INTO user_profile "
                    "(user_id, cold_start_seed_key, topic_weights_json, "
                    "recent_clicked_answers_json, recent_queries_json, behavior_score, notes) "
                    "SELECT %s, seed_key, topic_weights_json, '[]'::jsonb, '[]'::jsonb, 0, "
                    "'registered cold-start profile' FROM system_profile_seed WHERE seed_key = %s",
                    (user_id, self._cold_start_seed_key),
                )
                if cursor.rowcount != 1:
                    raise RepositoryNotReadyError("authentication cold-start seed")
        except UniqueViolation as exc:
            if exc.diag.constraint_name == "uq_user_account_email":
                raise DuplicateEmailError(email) from exc
            raise
        finally:
            connection.close()
        return AccountRecord(user_id, email, display_name, password_hash, True)

    def get_by_email(self, email: str) -> AccountRecord | None:
        return self._fetch("ua.email = %s", email)

    def get_by_user_id(self, user_id: int) -> AccountRecord | None:
        return self._fetch("ua.user_id = %s", user_id)

    def is_demo_user(self, user_id: int) -> bool:
        connection = self._pool.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM app_user WHERE user_id = %s AND is_demo_user IS TRUE LIMIT 1",
                    (user_id,),
                )
                return cursor.fetchone() is not None
        finally:
            connection.close()

    def _fetch(self, predicate: str, value: str | int) -> AccountRecord | None:
        connection = self._pool.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT ua.user_id, ua.email, u.display_name, ua.password_hash, ua.is_active "
                    "FROM user_account ua JOIN app_user u ON u.user_id = ua.user_id "
                    f"WHERE {predicate} LIMIT 1",
                    (value,),
                )
                return self._record(cursor.fetchone())
        finally:
            connection.close()
