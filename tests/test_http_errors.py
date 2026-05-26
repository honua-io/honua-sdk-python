"""Tests for HTTP error enrichment (request_id and headers)."""

from __future__ import annotations

import httpx
import pytest

from honua_sdk._http import _to_http_error
from honua_sdk.errors import (
    HonuaAuthError,
    HonuaHttpError,
    HonuaRateLimitError,
)


def _make_response(
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict | None = None,
) -> httpx.Response:
    request = httpx.Request("GET", "https://example.test/api/thing")
    return httpx.Response(
        status_code,
        headers=headers or {},
        json=json_body if json_body is not None else {"error": {"message": "boom"}},
        request=request,
    )


def test_request_id_extracted_from_x_request_id_header() -> None:
    response = _make_response(500, headers={"X-Request-ID": "abc-123"})
    error = _to_http_error(response)
    assert isinstance(error, HonuaHttpError)
    assert error.request_id == "abc-123"


def test_headers_exposed_on_error() -> None:
    response = _make_response(
        500,
        headers={"X-Request-ID": "abc-123", "X-Other": "value"},
    )
    error = _to_http_error(response)
    # httpx normalises header keys to lowercase
    assert error.headers.get("x-request-id") == "abc-123"
    assert error.headers.get("x-other") == "value"


def test_request_id_lookup_is_case_insensitive() -> None:
    # Mixed-case input header should still be extracted because httpx
    # normalises header keys to lowercase and our extractor uses
    # lowercase lookups.
    response = _make_response(500, headers={"X-Request-Id": "case-test"})
    error = _to_http_error(response)
    assert error.request_id == "case-test"


def test_request_id_falls_back_to_honua_request_id() -> None:
    response = _make_response(500, headers={"Honua-Request-Id": "honua-42"})
    error = _to_http_error(response)
    assert error.request_id == "honua-42"


def test_request_id_falls_back_to_x_correlation_id() -> None:
    response = _make_response(500, headers={"X-Correlation-ID": "corr-7"})
    error = _to_http_error(response)
    assert error.request_id == "corr-7"


def test_request_id_prefers_x_request_id_over_alternatives() -> None:
    response = _make_response(
        500,
        headers={
            "X-Request-ID": "primary",
            "Honua-Request-Id": "secondary",
            "X-Correlation-ID": "tertiary",
        },
    )
    error = _to_http_error(response)
    assert error.request_id == "primary"


def test_request_id_is_none_when_no_header_present() -> None:
    response = _make_response(500, headers={})
    error = _to_http_error(response)
    assert error.request_id is None
    # Headers attribute is always populated (empty dict when absent)
    assert error.headers is not None


def test_auth_error_carries_request_id_and_headers() -> None:
    response = _make_response(401, headers={"X-Request-ID": "auth-1"})
    error = _to_http_error(response)
    assert isinstance(error, HonuaAuthError)
    assert error.request_id == "auth-1"
    assert error.headers.get("x-request-id") == "auth-1"


def test_rate_limit_error_has_retry_after_and_request_id() -> None:
    response = _make_response(
        429,
        headers={"Retry-After": "30", "X-Request-ID": "rl-9"},
    )
    error = _to_http_error(response)
    assert isinstance(error, HonuaRateLimitError)
    assert error.retry_after == pytest.approx(30.0)
    assert error.request_id == "rl-9"
    assert error.headers.get("retry-after") == "30"


def test_honua_http_error_default_request_id_and_headers() -> None:
    # Direct construction (no response): request_id defaults to None
    # ("unknown" is a real signal), but headers defaults to an empty dict
    # so callers can use `.get(...)` without a null check.
    error = HonuaHttpError(500, "boom")
    assert error.request_id is None
    assert error.headers == {}
