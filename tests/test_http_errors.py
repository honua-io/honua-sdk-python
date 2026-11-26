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
    assert error.receipt.correlation_id == "abc-123"


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
    assert error.receipt.retry_after_seconds == pytest.approx(30.0)
    assert error.request_id == "rl-9"
    assert error.headers.get("retry-after") == "30"


def test_honua_http_error_default_request_id_and_headers() -> None:
    # Direct construction (no response): request_id defaults to None
    # ("unknown" is a real signal), but headers defaults to an empty dict
    # so callers can use `.get(...)` without a null check.
    error = HonuaHttpError(500, "boom")
    assert error.request_id is None
    assert error.headers == {}


def test_direct_error_receipt_retains_explicit_request_id() -> None:
    error = HonuaHttpError(500, "boom", request_id="direct-request")

    assert error.receipt.correlation_id == "direct-request"


def test_direct_rate_limit_receipt_retains_explicit_retry_after() -> None:
    error = HonuaRateLimitError(429, "slow down", retry_after=2.5)

    assert error.retry_after == pytest.approx(2.5)
    assert error.receipt.retry_after_seconds == pytest.approx(2.5)


def test_http_error_strips_sensitive_response_headers() -> None:
    response = _make_response(
        500,
        headers={
            "X-Request-ID": "req-secret-test",
            "Set-Cookie": "session=super-secret-cookie; HttpOnly",
            "Authorization": "Bearer super-secret-token",
            "Cookie": "sid=super-secret-cookie",
            "X-API-Key": "super-secret-key",
            "Proxy-Authorization": "Basic super-secret-proxy",
            "Content-Type": "application/json",
        },
    )
    error = _to_http_error(response)

    assert error.headers.get("x-request-id") == "req-secret-test"
    for sensitive in ("set-cookie", "authorization", "cookie", "x-api-key", "proxy-authorization"):
        assert sensitive not in {key.lower() for key in error.headers}
    assert "super-secret" not in str(error.headers)


def test_geoservices_and_direct_http_error_strip_set_cookie_header() -> None:
    from honua_sdk._http import _build_geoservices_error

    geo_response = _make_response(
        200,
        headers={"Set-Cookie": "sid=geo-secret", "X-Request-ID": "geo-1"},
        json_body={"error": {"code": 403, "message": "denied"}},
    )
    geo_error = _build_geoservices_error(
        error_code=403,
        message="denied",
        body={"error": {"code": 403, "message": "denied"}},
        response=geo_response,
    )
    assert "set-cookie" not in {key.lower() for key in geo_error.headers}
    assert geo_error.headers.get("x-request-id") == "geo-1"

    direct_error = HonuaHttpError(
        500,
        "boom",
        headers={
            "Set-Cookie": "sid=direct-secret",
            "Proxy-Authorization": "Basic direct-proxy",
            "X-Request-ID": "direct-1",
        },
    )
    assert "set-cookie" not in {key.lower() for key in direct_error.headers}
    assert "proxy-authorization" not in {key.lower() for key in direct_error.headers}
    assert direct_error.headers.get("X-Request-ID") == "direct-1"


def test_honua_sdk_pyproject_declares_anyio_dependency() -> None:
    import tomllib
    from pathlib import Path

    pyproject_path = Path(__file__).resolve().parents[1] / "packages" / "honua-sdk" / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert any(dep.lower().startswith("anyio") for dep in deps)
