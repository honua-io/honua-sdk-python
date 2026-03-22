from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from honua_sdk._retry import RetryTransport


def _make_transport(responses: list[httpx.Response], **kwargs: Any) -> RetryTransport:
    """Build a RetryTransport wrapping a mock that cycles through *responses*."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        return responses[idx]

    inner = httpx.MockTransport(handler)
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
    )
    request = httpx.Request("GET", "http://example.test/")

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 200
    mock_sleep.assert_called_once_with(7.0)


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
