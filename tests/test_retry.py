from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from honua_sdk._retry import RetryTransport


def _make_transport(responses: list[httpx.Response], **kwargs: Any) -> RetryTransport:
    """Build a RetryTransport wrapping a mock that cycles through *responses*.

    Defaults ``jitter=False`` so the legacy deterministic-backoff assertions
    in this module hold; tests that exercise the jitter path opt back in.
    """
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        return responses[idx]

    inner = httpx.MockTransport(handler)
    kwargs.setdefault("jitter", False)
    transport = RetryTransport(inner, **kwargs)
    transport._call_count = call_count  # type: ignore[attr-defined]
    return transport


def test_no_retry_on_success() -> None:
    transport = _make_transport([httpx.Response(200, json={"ok": True})])
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 1  # type: ignore[attr-defined]
    mock_sleep.assert_not_called()


def test_retry_on_502() -> None:
    transport = _make_transport(
        [
            httpx.Response(502, text="Bad Gateway"),
            httpx.Response(200, json={"ok": True}),
        ],
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]
    mock_sleep.assert_called_once_with(0.5)


def test_retry_on_503() -> None:
    transport = _make_transport(
        [
            httpx.Response(503, text="Service Unavailable"),
            httpx.Response(200, json={"ok": True}),
        ],
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep"):
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]


def test_retry_on_429() -> None:
    transport = _make_transport(
        [
            httpx.Response(429, text="Too Many Requests"),
            httpx.Response(200, json={"ok": True}),
        ],
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep"):
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]


def test_retry_on_504() -> None:
    transport = _make_transport(
        [
            httpx.Response(504, text="Gateway Timeout"),
            httpx.Response(200, json={"ok": True}),
        ],
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep"):
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]


def test_exponential_backoff() -> None:
    transport = _make_transport(
        [
            httpx.Response(503, text="retry"),
            httpx.Response(503, text="retry"),
            httpx.Response(503, text="retry"),
            httpx.Response(200, json={"ok": True}),
        ],
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 4  # type: ignore[attr-defined]
    calls = [c.args[0] for c in mock_sleep.call_args_list]
    assert calls == [0.5, 1.0, 2.0]


def test_backoff_capped_at_max() -> None:
    transport = _make_transport(
        [
            httpx.Response(503, text="retry"),
            httpx.Response(503, text="retry"),
            httpx.Response(503, text="retry"),
            httpx.Response(503, text="retry"),  # exhausts retries
        ],
        max_retries=3,
        backoff_initial=2.0,
        backoff_max=5.0,
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    # All retries exhausted, returns last 503
    assert response.status_code == 503
    calls = [c.args[0] for c in mock_sleep.call_args_list]
    assert calls == [2.0, 4.0, 5.0]


def test_honours_retry_after_header() -> None:
    transport = _make_transport(
        [
            httpx.Response(429, text="throttled", headers={"Retry-After": "7"}),
            httpx.Response(200, json={"ok": True}),
        ],
        backoff_max=10.0,
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 200
    mock_sleep.assert_called_once_with(7.0)


def test_retry_after_header_is_capped_by_backoff_max() -> None:
    transport = _make_transport(
        [
            httpx.Response(429, text="throttled", headers={"Retry-After": "86400"}),
            httpx.Response(200, json={"ok": True}),
        ],
        backoff_max=5.0,
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 200
    mock_sleep.assert_called_once_with(5.0)


@pytest.mark.parametrize("header_value", ["inf", "infinity", "1e400", "nan"])
def test_retry_after_non_finite_values_fall_back_to_backoff(header_value: str) -> None:
    transport = _make_transport(
        [
            httpx.Response(503, text="retry", headers={"Retry-After": header_value}),
            httpx.Response(200, json={"ok": True}),
        ],
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 200
    mock_sleep.assert_called_once_with(0.5)


def test_retry_after_invalid_falls_back_to_backoff() -> None:
    transport = _make_transport(
        [
            httpx.Response(503, text="retry", headers={"Retry-After": "not-a-number"}),
            httpx.Response(200, json={"ok": True}),
        ],
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 200
    mock_sleep.assert_called_once_with(0.5)


def test_max_retries_zero_disables_retry() -> None:
    transport = _make_transport(
        [httpx.Response(503, text="retry")],
        max_retries=0,
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 503
    assert transport._call_count["n"] == 1  # type: ignore[attr-defined]
    mock_sleep.assert_not_called()


def test_exhausted_retries_returns_last_response() -> None:
    transport = _make_transport(
        [
            httpx.Response(502, text="retry"),
            httpx.Response(502, text="retry"),
            httpx.Response(502, text="retry"),
            httpx.Response(502, text="still bad"),
        ],
        max_retries=3,
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep"):
        response = transport.handle_request(request)

    assert response.status_code == 502
    assert transport._call_count["n"] == 4  # type: ignore[attr-defined]


def test_no_retry_on_400() -> None:
    transport = _make_transport([httpx.Response(400, text="Bad Request")])
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 400
    assert transport._call_count["n"] == 1  # type: ignore[attr-defined]
    mock_sleep.assert_not_called()


def test_no_retry_on_404() -> None:
    transport = _make_transport([httpx.Response(404, text="Not Found")])
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 404
    mock_sleep.assert_not_called()


def test_post_not_retried_on_429_by_default() -> None:
    """POST requests are non-idempotent and must not be retried by default."""
    transport = _make_transport(
        [
            httpx.Response(429, text="Too Many Requests"),
            httpx.Response(200, json={"ok": True}),
        ],
    )
    request = httpx.Request("POST", "http://example.test/", json={"x": 1})

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 429
    assert transport._call_count["n"] == 1  # type: ignore[attr-defined]
    mock_sleep.assert_not_called()


def test_post_not_retried_on_503_by_default() -> None:
    transport = _make_transport(
        [
            httpx.Response(503, text="Service Unavailable"),
            httpx.Response(200, json={"ok": True}),
        ],
    )
    request = httpx.Request("POST", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 503
    assert transport._call_count["n"] == 1  # type: ignore[attr-defined]
    mock_sleep.assert_not_called()


def test_post_retried_when_opted_in_via_retry_methods() -> None:
    """When the caller explicitly opts POST into ``retry_methods`` it retries."""
    transport = _make_transport(
        [
            httpx.Response(429, text="Too Many Requests"),
            httpx.Response(200, json={"ok": True}),
        ],
        retry_methods=frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "POST"}),
    )
    request = httpx.Request("POST", "http://example.test/", json={"x": 1})

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]
    mock_sleep.assert_called_once_with(0.5)


def test_put_retried_by_default() -> None:
    """PUT is idempotent and should be retried by default."""
    transport = _make_transport(
        [
            httpx.Response(503, text="retry"),
            httpx.Response(200, json={"ok": True}),
        ],
    )
    request = httpx.Request("PUT", "http://example.test/resource/1", json={"x": 1})

    with patch("honua_sdk._retry.time.sleep"):
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]


def test_delete_retried_by_default() -> None:
    transport = _make_transport(
        [
            httpx.Response(502, text="bad gateway"),
            httpx.Response(204),
        ],
    )
    request = httpx.Request("DELETE", "http://example.test/resource/1")

    with patch("honua_sdk._retry.time.sleep"):
        response = transport.handle_request(request)

    assert response.status_code == 204
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]


def test_jitter_delay_sequence_matches_exponential_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With deterministic ``random.uniform`` the jittered schedule
    follows ``backoff_initial * 2**attempt`` (capped)."""
    observed_caps: list[float] = []

    def fake_uniform(lo: float, hi: float) -> float:
        assert lo == 0.0
        observed_caps.append(hi)
        return hi  # take the upper end of the jitter range

    monkeypatch.setattr("honua_sdk._retry_core.random.uniform", fake_uniform)

    transport = _make_transport(
        [
            httpx.Response(503, text="retry"),
            httpx.Response(503, text="retry"),
            httpx.Response(503, text="retry"),
            httpx.Response(503, text="retry"),
        ],
        max_retries=3,
        backoff_initial=0.5,
        backoff_max=5.0,
        jitter=True,
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 503
    # Expected caps: 0.5 * 2**0, 0.5 * 2**1, 0.5 * 2**2 = 0.5, 1.0, 2.0
    assert observed_caps == [0.5, 1.0, 2.0]
    calls = [c.args[0] for c in mock_sleep.call_args_list]
    assert calls == [0.5, 1.0, 2.0]


def test_jitter_delay_respects_backoff_max(monkeypatch: pytest.MonkeyPatch) -> None:
    """The jitter cap is bounded by ``backoff_max`` for late attempts."""
    observed_caps: list[float] = []

    def fake_uniform(lo: float, hi: float) -> float:
        observed_caps.append(hi)
        return hi

    monkeypatch.setattr("honua_sdk._retry_core.random.uniform", fake_uniform)

    transport = _make_transport(
        [
            httpx.Response(503, text="retry"),
            httpx.Response(503, text="retry"),
            httpx.Response(503, text="retry"),
            httpx.Response(503, text="retry"),
        ],
        max_retries=3,
        backoff_initial=2.0,
        backoff_max=5.0,
        jitter=True,
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep"):
        transport.handle_request(request)

    # Computed caps would be 2.0, 4.0, 8.0 → capped at 2.0, 4.0, 5.0.
    assert observed_caps == [2.0, 4.0, 5.0]


def test_custom_retry_statuses_overrides_default() -> None:
    """Callers can tune ``retry_statuses`` (e.g. add 524)."""
    transport = _make_transport(
        [
            httpx.Response(524, text="Cloudflare timeout"),
            httpx.Response(200, json={"ok": True}),
        ],
        retry_statuses=frozenset({429, 502, 503, 504, 524}),
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep"):
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]


def test_custom_retry_statuses_excludes_default() -> None:
    """If ``retry_statuses`` omits 429, it is not retried."""
    transport = _make_transport(
        [
            httpx.Response(429, text="throttled"),
            httpx.Response(200, json={"ok": True}),
        ],
        retry_statuses=frozenset({502, 503, 504}),
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 429
    assert transport._call_count["n"] == 1  # type: ignore[attr-defined]
    mock_sleep.assert_not_called()


def test_method_matching_is_case_insensitive() -> None:
    """Lowercase methods in ``retry_methods`` are normalised to uppercase."""
    transport = _make_transport(
        [
            httpx.Response(503, text="retry"),
            httpx.Response(200, json={"ok": True}),
        ],
        retry_methods=frozenset({"get", "post"}),
    )
    request = httpx.Request("POST", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep"):
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]


def test_client_integration_with_retry() -> None:
    """Verify RetryTransport integrates with HonuaClient end-to-end."""
    from honua_sdk import HonuaClient

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, json={"status": "ready"})

    transport = httpx.MockTransport(handler)

    with patch("honua_sdk._retry.time.sleep"):
        with HonuaClient("http://example.test", transport=transport, max_retries=3) as client:
            result = client.readiness()

    assert result == {"status": "ready"}
    assert call_count["n"] == 2
