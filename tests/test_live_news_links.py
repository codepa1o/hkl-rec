from __future__ import annotations

import urllib.error

from scripts.check_live_news_links import LinkProbeResult, next_link_state, probe_url


def test_success_resets_link_failures_and_keeps_article_active() -> None:
    assert next_link_state(2, LinkProbeResult(ok=True, detail="200")) == (0, "active")


def test_permanent_and_transport_failures_deactivate_on_third_failure() -> None:
    assert next_link_state(
        1,
        LinkProbeResult(ok=False, permanent=True, detail="404"),
    ) == (2, "active")
    assert next_link_state(
        2,
        LinkProbeResult(ok=False, permanent=False, detail="timeout"),
    ) == (3, "inactive")


def test_probe_result_does_not_expose_url_or_exception_as_metric_label() -> None:
    result = LinkProbeResult(ok=False, permanent=False, detail="TimeoutError")
    assert result.detail == "TimeoutError"


def test_probe_falls_back_from_head_to_get_without_network() -> None:
    methods: list[str] = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def opener(request, *, timeout):
        methods.append(request.get_method())
        if request.get_method() == "HEAD":
            raise urllib.error.HTTPError(request.full_url, 405, "", {}, None)
        return Response()

    result = probe_url("https://example.com/article", 5, opener=opener)

    assert result == LinkProbeResult(ok=True, detail="200")
    assert methods == ["HEAD", "GET"]


def test_probe_marks_404_as_permanent_without_get_retry() -> None:
    def opener(request, *, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "", {}, None)

    assert probe_url("https://example.com/missing", 5, opener=opener) == LinkProbeResult(
        ok=False,
        permanent=True,
        detail="404",
    )
