from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from backend.app.live_news.content_types import ContentAcquisitionError


class Transport(Protocol):
    def __call__(self, request: Any, timeout: float) -> Any: ...


@dataclass(frozen=True)
class FetchResponse:
    final_url: str
    status: int
    content_type: str
    body: bytes
    retry_after: str | None


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _default_transport(request: Request, timeout: float) -> Any:
    opener = build_opener(_NoRedirectHandler())
    try:
        return opener.open(request, timeout=timeout)
    except HTTPError as exc:
        return exc


def _default_resolver(host: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(sockaddr[0])
                for _family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(
                    host, 443, type=socket.SOCK_STREAM
                )
            }
        )
    )


def _host_matches(host: str, expected_domain: str) -> bool:
    normalized = host.rstrip(".").lower()
    domain = expected_domain.rstrip(".").lower()
    return normalized == domain or normalized.endswith(f".{domain}")


def _validate_addresses(addresses: tuple[str, ...]) -> None:
    if not addresses:
        raise ContentAcquisitionError(
            "dns_failure", "hostname resolved to no addresses", retryable=True
        )
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ContentAcquisitionError(
                "dns_failure", f"invalid resolved address: {address}", retryable=True
            ) from exc
        if not parsed.is_global:
            raise ContentAcquisitionError(
                "unsafe_address", f"resolved address is not global: {address}", retryable=False
            )


class SafeFetcher:
    def __init__(
        self,
        *,
        transport: Transport | None = None,
        resolver: Callable[[str], tuple[str, ...]] | None = None,
        connect_timeout_seconds: int = 5,
        read_timeout_seconds: int = 15,
        max_response_bytes: int = 2 * 1024 * 1024,
        max_redirects: int = 3,
    ) -> None:
        self._transport = transport or _default_transport
        self._resolver = resolver or _default_resolver
        self._timeout = float(connect_timeout_seconds + read_timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._max_redirects = max_redirects

    def get(
        self,
        url: str,
        *,
        expected_domain: str,
        accepted_content_types: frozenset[str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResponse:
        accepted = accepted_content_types or frozenset(
            {"text/html", "application/json", "application/rss+xml", "application/xml", "text/xml"}
        )
        current_url = url
        request_headers = {
            "Accept-Encoding": "identity",
            "User-Agent": "hkl-rec-live-content/1.0 (+local research project)",
            **dict(headers or {}),
        }
        for redirect_count in range(self._max_redirects + 1):
            parsed = urlsplit(current_url)
            host = (parsed.hostname or "").rstrip(".").lower()
            if (
                parsed.scheme != "https"
                or not host
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in {None, 443}
            ):
                raise ContentAcquisitionError(
                    "invalid_url",
                    "content URL must be a credential-free HTTPS URL",
                    retryable=False,
                )
            if not _host_matches(host, expected_domain):
                raise ContentAcquisitionError(
                    "invalid_redirect",
                    f"URL host {host!r} does not match {expected_domain!r}",
                    retryable=False,
                )
            try:
                _validate_addresses(tuple(self._resolver(host)))
                response = self._transport(
                    Request(current_url, headers=request_headers), self._timeout
                )
            except ContentAcquisitionError:
                raise
            except (OSError, TimeoutError, URLError) as exc:
                raise ContentAcquisitionError(
                    "network_error", f"{type(exc).__name__}: {exc}", retryable=True
                ) from exc
            try:
                status = int(getattr(response, "status", getattr(response, "code", 0)))
                retry_after = response.headers.get("Retry-After")
                if status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location or redirect_count >= self._max_redirects:
                        raise ContentAcquisitionError(
                            "invalid_redirect",
                            "redirect limit reached or location missing",
                            retryable=False,
                        )
                    current_url = urljoin(current_url, location)
                    continue
                if status >= 400:
                    retryable = status in {408, 425, 429} or status >= 500
                    if status in {401, 403}:
                        code = "authentication_required"
                    elif status in {404, 410}:
                        code = "article_not_found"
                    else:
                        code = f"http_{status}"
                    raise ContentAcquisitionError(
                        code,
                        f"publisher returned HTTP {status}",
                        retryable=retryable,
                        retry_after=retry_after,
                    )
                content_type = (
                    str(response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
                )
                if content_type not in accepted:
                    raise ContentAcquisitionError(
                        "unsupported_content_type",
                        f"unsupported content type: {content_type or 'missing'}",
                        retryable=False,
                    )
                body = response.read(self._max_response_bytes + 1)
                if len(body) > self._max_response_bytes:
                    raise ContentAcquisitionError(
                        "response_too_large",
                        f"response exceeds {self._max_response_bytes} bytes",
                        retryable=False,
                    )
                return FetchResponse(
                    final_url=current_url,
                    status=status,
                    content_type=content_type,
                    body=body,
                    retry_after=retry_after,
                )
            finally:
                response.close()
        raise ContentAcquisitionError("invalid_redirect", "redirect limit reached", retryable=False)
