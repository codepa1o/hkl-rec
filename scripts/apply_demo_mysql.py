from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]


def environment_value(name: str, legacy_name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    if legacy_name in os.environ:
        print(f"deprecated environment variable {legacy_name}; use {name}", file=sys.stderr)
        return os.environ[legacy_name]
    return default


@dataclass(frozen=True)
class MysqlUrl:
    host: str
    port: int
    user: str
    password: str
    database: str


def parse_args() -> argparse.Namespace:
    seed_dir = environment_value(
        "NEWSREC_DEMO_SEED_DIR",
        "ZHIHUREC_DEMO_SEED_DIR",
        "build/mind_demo_world",
    )
    parser = argparse.ArgumentParser(
        description="Apply the NewsIntentRec schema and demo seed SQL to MySQL."
    )
    parser.add_argument("--schema-sql", default="sql/schema.sql", help="Schema SQL file.")
    parser.add_argument(
        "--seed-sql",
        default=f"{seed_dir}/import_demo_world.sql",
        help="Seed SQL file.",
    )
    parser.add_argument(
        "--fixture-dir",
        default="build/mind_demo_fixture",
        help="Generated compact fixture directory used when --seed-sql is missing.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Only verify inputs and print the target."
    )
    return parser.parse_args()


def repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def parse_database_url(database_url: str) -> MysqlUrl:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise ValueError("NEWSREC_DATABASE_URL must start with mysql:// or mysql+pymysql://")
    if not parsed.hostname:
        raise ValueError("NEWSREC_DATABASE_URL must include a host")
    if not parsed.username:
        raise ValueError("NEWSREC_DATABASE_URL must include a username")
    database = parsed.path.lstrip("/")
    if not database:
        raise ValueError("NEWSREC_DATABASE_URL must include a database name")
    return MysqlUrl(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=unquote(parsed.username),
        password=unquote(parsed.password or ""),
        database=unquote(database),
    )


def split_sql(sql_text: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    escaped = False

    for char in sql_text:
        if quote is not None:
            buffer.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in {"'", '"', "`"}:
            quote = char
            buffer.append(char)
        elif char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
        else:
            buffer.append(char)

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def connect(config: MysqlUrl):
    import pymysql

    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        autocommit=True,
    )


def apply_sql_file(connection, sql_path: Path) -> int:
    sql_text = sql_path.read_text(encoding="utf-8")
    statements = split_sql(sql_text)
    with connection.cursor() as cursor:
        for index, statement in enumerate(statements, start=1):
            try:
                cursor.execute(statement)
            except Exception as exc:  # pragma: no cover - 诊断路径
                preview = " ".join(statement.split())[:240]
                raise RuntimeError(f"failed at {sql_path} statement {index}: {preview}") from exc
    return len(statements)


def prepare_seed_sql(seed_sql: Path, fixture_dir: Path) -> Path:
    if seed_sql.exists():
        return seed_sql

    fixture_seed_sql = fixture_dir / "import_demo_world.sql"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_mind_demo_fixture.py"),
            "--output-dir",
            str(fixture_dir),
        ],
        check=True,
        cwd=ROOT,
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "import_demo_world.py"),
            "--input-dir",
            str(fixture_dir),
            "--output-sql",
            str(fixture_seed_sql),
            "--truncate-first",
        ],
        check=True,
        cwd=ROOT,
    )
    print(f"seed SQL not found at {seed_sql}; using compact fixture {fixture_seed_sql}")
    return fixture_seed_sql


def main() -> None:
    args = parse_args()
    schema_sql = repo_path(args.schema_sql)
    seed_sql = repo_path(args.seed_sql)
    fixture_dir = repo_path(args.fixture_dir)
    if not args.dry_run:
        seed_sql = prepare_seed_sql(seed_sql, fixture_dir)
    missing = [path for path in (schema_sql, seed_sql) if not path.exists()]
    if missing:
        for path in missing:
            print(f"missing: {path}")
        raise SystemExit(1)

    database_url = environment_value(
        "NEWSREC_DATABASE_URL",
        "ZHIHUREC_DATABASE_URL",
    ).strip()
    config = parse_database_url(database_url) if database_url else None

    if args.dry_run:
        print(f"schema_sql: {schema_sql}")
        print(f"seed_sql: {seed_sql}")
        if config is None:
            print("database_url: not configured; required for normal mode")
        else:
            print(f"target: {config.user}@{config.host}:{config.port}/{config.database}")
        print("dry_run: ok")
        return

    if config is None:
        raise SystemExit("NEWSREC_DATABASE_URL is required unless --dry-run is used")

    connection = connect(config)
    try:
        schema_count = apply_sql_file(connection, schema_sql)
        seed_count = apply_sql_file(connection, seed_sql)
    finally:
        connection.close()

    print(f"applied schema statements: {schema_count}")
    print(f"applied seed statements: {seed_count}")
    print(f"target: {config.user}@{config.host}:{config.port}/{config.database}")


if __name__ == "__main__":
    main()
