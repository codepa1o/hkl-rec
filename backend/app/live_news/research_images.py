"""Read-only, policy-gated delivery of publisher images for local research."""

from __future__ import annotations

import socket
import warnings
from http.client import HTTPConnection, HTTPSConnection
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

from backend.app.config import Settings, local_research_content_allowed
from backend.app.live_news.allowlist import SourceAllowlist, load_allowlist
from backend.app.live_news.content_document import ImageBlock, StructuredBodyDocument
from backend.app.live_news.content_fetch import FetchPolicy, SafeFetcher, _validate_addresses
from backend.app.live_news.content_policy import ContentPolicy
from backend.app.live_news.content_types import ContentAcquisitionError
from backend.app.repositories.connection import connect, parse_database_url

_IMAGE_SLOTS = BoundedSemaphore(4)
_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}


class _ImageResponse:
    def __init__(self, response: Any, connection: HTTPConnection, sock: Any, deadline: float) -> None:
        self.status = response.status
        self.headers = response.headers
        self._response = response
        self._connection = connection
        self._socket = sock
        self._deadline = deadline

    def read(self, size: int) -> bytes:
        result = bytearray()
        while len(result) < size:
            remaining = self._deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("image deadline exceeded")
            self._socket.settimeout(min(5, remaining))
            chunk = self._response.read1(min(65536, size - len(result)))
            if not chunk:
                break
            result.extend(chunk)
        return bytes(result)

    def close(self) -> None:
        self._response.close()
        self._connection.close()


class ImageTransport:
    """Pin the validated IP, keep the original Host/SNI, and bound all redirect reads."""

    def __init__(self) -> None:
        self._deadline = monotonic() + 20

    def __call__(self, request: Any, timeout: float) -> _ImageResponse:
        parsed = urlsplit(request.full_url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = tuple(
            str(item[4][0]) for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        )
        _validate_addresses(addresses)
        remaining = min(timeout, self._deadline - monotonic())
        if remaining <= 0:
            raise TimeoutError("image deadline exceeded")
        connection = (HTTPSConnection if parsed.scheme == "https" else HTTPConnection)(
            host, port, timeout=remaining
        )

        # urllib's DNS preflight alone does not pin the subsequent connection.
        def connect_ip(_address: Any, timeout: float, source_address: Any = None) -> socket.socket:
            return socket.create_connection(
                (addresses[0], port), timeout=timeout, source_address=source_address
            )

        connection._create_connection = connect_ip  # type: ignore[attr-defined]
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request("GET", path, headers=dict(request.header_items()))
            sock = connection.sock
            response = connection.getresponse()
            return _ImageResponse(response, connection, sock, self._deadline)
        except Exception:
            connection.close()
            raise


def image_media_type(body: bytes) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(body)) as image:
                media_type = _FORMATS.get(image.format or "")
                if not media_type or image.width * image.height > 25_000_000:
                    raise ValueError("unsupported image format or dimensions")
                image.verify()
                return media_type
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("invalid image bytes") from exc


def validate_asset(row: dict[str, Any], allowlist: SourceAllowlist) -> ContentPolicy:
    source = allowlist.match(str(row.get("source_domain", "")))
    if (
        source is None
        or source.content.mode != "html"
        or source.content.access_scope != "local_research"
        or source.content.display != "full_text"
        or source.content.images.display == "omit"
        or row.get("body_access_scope") != "local_research"
        or row.get("content_rights") != "full_text"
        or row.get("status") != "active"
        or row.get("body_structure_status") == "blocked"
    ):
        raise LookupError("research image not available")
    policy = source.content
    try:
        document = StructuredBodyDocument.model_validate(row.get("body_document"))
        matching = [
            block
            for block in document.blocks
            if isinstance(block, ImageBlock)
            and block.asset_id == row["asset_id"]
            and block.id == row["block_id"]
            and block.source_url == row["source_url"]
            and block.cache_status != "omitted"
        ]
        parsed = urlsplit(row["source_url"])
        host = (parsed.hostname or "").rstrip(".").lower()
        allowed = any(
            host == domain or host.endswith("." + domain)
            for domain in policy.images.allowed_domains
        )
        if (
            not matching
            or document.extraction_version != row.get("body_document_version")
            or not allowed
            or parsed.username is not None
            or parsed.password is not None
            or parsed.scheme not in ({"http", "https"} if policy.allow_insecure_http else {"https"})
        ):
            raise ValueError("asset is not part of the allowed current document")
    except (ValueError, KeyError, TypeError) as exc:
        raise LookupError("research image not available") from exc
    return policy


def load_research_image(settings: Settings, article_id: str, asset_id: str) -> tuple[bytes, str]:
    if not local_research_content_allowed(settings):
        raise LookupError("research image not available")
    if not _IMAGE_SLOTS.acquire(blocking=False):
        raise ContentAcquisitionError(
            "image_busy", "image concurrency limit reached", retryable=True
        )
    try:
        connection = connect(
            parse_database_url(settings.database_url),
            connect_timeout=settings.postgres_connect_timeout_seconds,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT n.article_id, n.source_domain, n.status,
                    n.body_access_scope, n.content_rights, n.body_document,
                    n.body_document_version, n.body_structure_status,
                    a.asset_id, a.block_id, a.source_url
                    FROM live_news n JOIN live_news_content_asset a USING (article_id)
                    WHERE n.article_id = %s AND a.asset_id = %s""",
                    (article_id, asset_id),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            raise LookupError("research image not found")
        policy = validate_asset(dict(row), load_allowlist(Path(settings.live_news_source_config)))
        fetcher = SafeFetcher(
            transport=ImageTransport(),
            max_response_bytes=min(policy.images.max_bytes_per_image, 8 * 1024 * 1024),
            connect_timeout_seconds=3,
            read_timeout_seconds=7,
            max_redirects=2,
        )
        response = fetcher.get(
            str(row["source_url"]),
            expected_domain=str(urlsplit(row["source_url"]).hostname),
            accepted_content_types=frozenset(_FORMATS.values()),
            fetch_policy=FetchPolicy.local_research_http() if policy.allow_insecure_http else None,
        )
        try:
            media_type = image_media_type(response.body)
        except ValueError as exc:
            raise ContentAcquisitionError(
                "invalid_image", "publisher returned invalid image bytes", retryable=False
            ) from exc
        return response.body, media_type
    finally:
        _IMAGE_SLOTS.release()
