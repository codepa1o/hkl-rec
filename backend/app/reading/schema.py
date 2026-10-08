from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB


def define_reading_tables(metadata: MetaData) -> None:
    def owner() -> Any:
        return Column(
            "user_id",
            BigInteger,
            ForeignKey("app_user.user_id", ondelete="CASCADE"),
            nullable=False,
        )

    def space() -> Any:
        return Column("source_space", String(16), nullable=False)

    def check() -> CheckConstraint:
        return CheckConstraint("source_space IN ('mind','live')", name="source_space")

    Table(
        "reading_state",
        metadata,
        owner(),
        space(),
        Column("article_id", String(64), nullable=False),
        Column("saved", Boolean, nullable=False, server_default=text("false")),
        Column("read", Boolean, nullable=False, server_default=text("false")),
        Column(
            "updated_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
        UniqueConstraint("user_id", "source_space", "article_id"),
        check(),
    )
    Table(
        "reading_rule",
        metadata,
        Column("id", BigInteger, Identity(), primary_key=True),
        owner(),
        space(),
        Column("target_type", String(16), nullable=False),
        Column("value", String(200), nullable=False),
        Column("effect", String(16), nullable=False),
        Column("enabled", Boolean, nullable=False, server_default=text("true")),
        UniqueConstraint("user_id", "source_space", "target_type", "value"),
        check(),
        CheckConstraint("target_type IN ('source','topic','keyword')", name="target_type"),
        CheckConstraint("effect IN ('prefer','reduce','block')", name="effect"),
    )
    Table(
        "reading_search",
        metadata,
        Column("id", BigInteger, Identity(), primary_key=True),
        owner(),
        space(),
        Column("query", String(300), nullable=False),
        Column("language", String(8), nullable=False),
        Column("category", String(64), nullable=False, server_default=text("''")),
        UniqueConstraint("user_id", "source_space", "query", "language", "category"),
        check(),
        CheckConstraint("language IN ('all','zh','en')", name="language"),
    )
    Table(
        "reading_feed",
        metadata,
        Column("id", String(64), primary_key=True),
        owner(),
        space(),
        Column("context", JSONB, nullable=False),
        Column("revision", String(64), nullable=False),
        Column("items", JSONB, nullable=False),
        Column("request_id", String(128), nullable=False),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
        UniqueConstraint("user_id", "source_space", "request_id"),
        check(),
    )
