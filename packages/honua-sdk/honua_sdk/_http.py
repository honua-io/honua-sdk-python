"""Shared HTTP utilities used by all Honua SDK client modules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from .auth import AuthProvider, SENSITIVE_AUTH_HEADER_NAMES, normalize_auth_headers
from .errors import HonuaHttpError


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/"


def _encode_path_segment(value: str) -> str:
    return quote(value, safe="")


def _build_sensitive_auth_headers(
    *,
    api_key: str | None,
    bearer_token: str | None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return headers


def _validate_auth_configuration(
    *,
    bearer_token: str | None,
    auth_provider: AuthProvider | None,
) -> None:
    if bearer_token is not None and auth_provider is not None:
        raise ValueError("Provide either `bearer_token` or `auth_provider`, not both.")


def _validate_external_client_auth_configuration(
    *,
    client: object | None,
    api_key: str | None,
    bearer_token: str | None,
    auth_provider: AuthProvider | None,
) -> None:
    if client is None:
        return
    if api_key is None and bearer_token is None and auth_provider is None:
        return
    raise ValueError(
        "Configure authentication on the supplied `client`; "
        "`api_key`, `bearer_token`, and `auth_provider` are only applied "
        "when the SDK creates the HTTP client."
    )


def _extract_trusted_authority(url: httpx.URL) -> tuple[str, int | None]:
    """Return ``(host, port)`` from *url* for use as a trusted-origin key.

    Using both host **and** port prevents credentials configured for
    ``example.test:443`` from being sent to ``example.test:9999``
    after a redirect.
    """
    return (url.host, url.port)


def _apply_sensitive_auth_headers(
    request: httpx.Request,
    *,
    trusted_authority: tuple[str, int | None] | None,
    auth_headers: Mapping[str, str],
    auth_provider: AuthProvider | None = None,
) -> None:
    """Attach or strip sensitive headers depending on the request target.

    Headers are only attached when the request's ``(host, port)`` matches
    *trusted_authority* exactly; otherwise they are stripped to prevent
    credential leakage on redirects.
    """
    if trusted_authority is None:
        return

    request_authority = (request.url.host, request.url.port)
    if request_authority == trusted_authority:
        dynamic_headers = _auth_provider_headers(auth_provider)
        for name, value in auth_headers.items():
            request.headers.setdefault(name, value)
        for name, value in dynamic_headers.items():
            request.headers.setdefault(name, value)
        return

    for name in SENSITIVE_AUTH_HEADER_NAMES:
        request.headers.pop(name, None)


def _auth_provider_headers(auth_provider: AuthProvider | None) -> dict[str, str]:
    if auth_provider is None:
        return {}
    return normalize_auth_headers(auth_provider.auth_headers())


def _to_http_error(response: httpx.Response) -> HonuaHttpError:
    body: Any | None = None
    message = response.reason_phrase or "Request failed"

    if response.content:
        try:
            body = response.json()
        except ValueError:
            body = response.text
    if isinstance(body, Mapping):
        error = body.get("error")
        if isinstance(error, Mapping):
            candidate = error.get("message")
            if isinstance(candidate, str) and candidate:
                message = candidate
        else:
            candidate = body.get("detail") or body.get("message")
            if isinstance(candidate, str) and candidate:
                message = candidate

    return HonuaHttpError(response.status_code, message, body=body)


def _to_transport_error(error: httpx.HTTPError) -> HonuaHttpError:
    message = str(error) or error.__class__.__name__
    body: dict[str, Any] = {"type": error.__class__.__name__, "message": message}
    request = getattr(error, "request", None)
    if request is not None:
        body["url"] = str(request.url)
    return HonuaHttpError(0, f"Transport error: {message}", body=body)
