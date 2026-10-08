"""Reacquire one Guardian article; --apply backs up then atomically updates derived body data."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.live_news.allowlist import load_allowlist  # noqa: E402
from backend.app.live_news.content_dao import complete_content_job, ensure_content_job  # noqa: E402
from backend.app.live_news.content_fetch import SafeFetcher  # noqa: E402
from backend.app.live_news.content_types import (  # noqa: E402
    ContentAcquisitionError,
    ContentJob,
    ContentRequest,
)
from backend.app.repositories.connection import connect, parse_database_url  # noqa: E402
from scripts.run_live_news_content_worker import build_provider_registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--article-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    connection = connect(parse_database_url(settings.database_url))
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT * FROM live_news WHERE article_id=%s", (args.article_id,))
            row = cur.fetchone()
        connection.commit()
        if not row:
            raise ValueError("Article not found")
        policy = load_allowlist(Path(settings.live_news_source_config)).match(row["source_domain"])
        if policy is None or policy.content.mode != "guardian_api":
            raise ValueError("Only Guardian API articles are supported")
        request = ContentRequest(
            article_id=args.article_id,
            canonical_url=row["canonical_url"],
            expected_domain=policy.domain,
            language=row["language"],
            policy=policy.content,
            lead_image_url=row["image_url"],
            title=row["title"],
        )
        acquired = (
            build_provider_registry(settings, SafeFetcher())
            .for_mode("guardian_api")
            .acquire(request)
        )
        doc = acquired.body_document
        report = {
            "article_id": args.article_id,
            "apply": args.apply,
            "version": doc.extraction_version,
            "source": acquired.source,
            "access_scope": acquired.access_scope or request.policy.access_scope,
            "fallback_reason": doc.fallback_reason,
            "blocks": len(doc.blocks),
            "images": sum(b.type == "image" for b in doc.blocks),
            "publisher_tags": [t.name for t in doc.publisher_tags],
            "body_characters": len(acquired.body_text),
        }
        if args.apply:
            with connection.transaction(), connection.cursor() as cur:
                cur.execute(
                    "SELECT * FROM live_news WHERE article_id=%s FOR UPDATE", (args.article_id,)
                )
                current = cur.fetchone()
                if (
                    current["body_document_hash"] != row["body_document_hash"]
                    or current["canonical_url"] != row["canonical_url"]
                ):
                    raise RuntimeError(
                        "Article changed during acquisition; rerun instead of overwriting"
                    )
                cur.execute(
                    "SELECT * FROM live_news_content_job WHERE article_id=%s FOR UPDATE",
                    (args.article_id,),
                )
                job = cur.fetchone()
                if job and job["status"] == "fetching":
                    raise RuntimeError("Article is being fetched by another worker")
                backup = (
                    ROOT
                    / ".runtime"
                    / "guardian-repair"
                    / f"{args.article_id}-{uuid.uuid4().hex}.json"
                )
                backup.parent.mkdir(parents=True, exist_ok=True)
                cur.execute(
                    "SELECT * FROM live_news_content_asset WHERE article_id=%s", (args.article_id,)
                )
                assets = [dict(asset) for asset in cur.fetchall()]
                backup.write_text(
                    json.dumps(
                        {
                            "article": dict(current),
                            "assets": assets,
                            "content_job": dict(job) if job else None,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                ensure_content_job(
                    connection, args.article_id, policy.content, now=datetime.now(UTC)
                )
                complete_content_job(
                    connection,
                    ContentJob(args.article_id, request, policy.content.display, 1),
                    acquired,
                )
                report["backup"] = str(backup)
        print(json.dumps(report, ensure_ascii=True))
        return 0
    except ContentAcquisitionError as exc:
        print(json.dumps({"error": exc.code, "retryable": exc.retryable}))
        return 1  # Never print an authenticated provider URL or key.
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
