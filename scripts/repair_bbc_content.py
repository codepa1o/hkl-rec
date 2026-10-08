"""Reacquire a BBC News article; default is preview, --apply backs up and writes derived content."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import get_settings, local_research_content_allowed  # noqa: E402
from backend.app.live_news.allowlist import load_allowlist  # noqa: E402
from backend.app.live_news.content_dao import complete_content_job, ensure_content_job  # noqa: E402
from backend.app.live_news.content_fetch import SafeFetcher  # noqa: E402
from backend.app.live_news.content_providers import HtmlContentProvider  # noqa: E402
from backend.app.live_news.content_types import (  # noqa: E402
    ContentAcquisitionError,
    ContentJob,
    ContentRequest,
)
from backend.app.repositories.connection import connect, parse_database_url  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--article-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    c = connect(parse_database_url(settings.database_url))
    try:
        with c.cursor() as cur:
            cur.execute("SELECT * FROM live_news WHERE article_id=%s", (args.article_id,))
            row = cur.fetchone()
        c.commit()
        if not row:
            raise ValueError("Article not found")
        policy = load_allowlist(Path(settings.live_news_source_config)).match(row["source_domain"])
        if policy is None or policy.content.mode != "html" or policy.content.adapter != "bbc":
            raise ValueError("Only enabled BBC HTML articles are supported")
        request = ContentRequest(
            args.article_id,
            row["canonical_url"],
            policy.domain,
            row["language"],
            policy.content,
            row["image_url"],
            row["title"],
        )
        acquired = HtmlContentProvider(
            SafeFetcher(
                connect_timeout_seconds=settings.live_content_connect_timeout_seconds,
                read_timeout_seconds=settings.live_content_read_timeout_seconds,
                max_response_bytes=settings.live_content_max_response_bytes,
            ),
            local_research_allowed=local_research_content_allowed(settings),
        ).acquire(request)
        doc = acquired.body_document
        report = {
            "article_id": args.article_id,
            "apply": args.apply,
            "version": doc.extraction_version,
            "source": acquired.source,
            "scope": acquired.access_scope,
            "characters": len(acquired.body_text),
            "block_types": [b.type for b in doc.blocks],
            "tags": [t.name for t in doc.publisher_tags],
            "byline": doc.byline,
        }
        if args.apply:
            with c.transaction(), c.cursor() as cur:
                cur.execute(
                    "SELECT * FROM live_news WHERE article_id=%s FOR UPDATE", (args.article_id,)
                )
                current = cur.fetchone()
                if current is None or any(
                    current[k] != row[k]
                    for k in ("body_document_hash", "canonical_url", "title", "status")
                ):
                    raise RuntimeError(
                        "Article changed while fetching; rerun instead of overwriting"
                    )
                cur.execute(
                    "SELECT * FROM live_news_content_job WHERE article_id=%s FOR UPDATE",
                    (args.article_id,),
                )
                job = cur.fetchone()
                if job and job["status"] == "fetching":
                    raise RuntimeError("Another worker is processing this article")
                cur.execute(
                    "SELECT * FROM live_news_content_asset WHERE article_id=%s", (args.article_id,)
                )
                assets = [dict(a) for a in cur.fetchall()]
                backup = (
                    ROOT / ".runtime" / "bbc-repair" / f"{args.article_id}-{uuid.uuid4().hex}.json"
                )
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_text(
                    json.dumps(
                        {
                            "article": dict(current),
                            "content_job": dict(job) if job else None,
                            "assets": assets,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                ensure_content_job(c, args.article_id, policy.content, now=datetime.now(UTC))
                complete_content_job(
                    c, ContentJob(args.article_id, request, policy.content.display, 1), acquired
                )
                report["backup"] = str(backup)
        print(json.dumps(report, ensure_ascii=True))
        return 0
    except ContentAcquisitionError as e:
        print(json.dumps({"error": e.code, "retryable": e.retryable}))
        return 1
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
