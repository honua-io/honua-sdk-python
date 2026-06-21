"""Shared HTTP utilities used by all Honua SDK client modules."""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from .auth import SENSITIVE_AUTH_HEADER_NAMES, AuthProvider, normalize_auth_headers
from .errors import (
    HonuaAuthError,
    HonuaHttpError,
    HonuaRateLimitError,
    HonuaTimeoutError,
    HonuaTransportError,
)


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


def _warn_deprecated_bearer_token(
    bearer_token: str | None,
    *,
    stacklevel: int = 3,
) -> None:
    """Emit a :class:`DeprecationWarning` when ``bearer_token=`` is used.

    The ``bearer_token=`` constructor kwarg is deprecated in favor of the
    single ``auth_provider=`` parameter (mirroring the one-auth-parameter
    convention used by stripe-python / openai-python). Migrate callers to
    ``auth_provider=StaticAuthProvider({"Authorization": f"Bearer {token}"})``.
    Scheduled for removal in 0.2.x.

    ``stacklevel`` defaults to 3 so the warning points at the caller's
    constructor invocation (warn → ``_warn_deprecated_bearer_token`` →
    ``__init__`` → caller).
    """
    if bearer_token is None:
        return
    warnings.warn(
        "The `bearer_token=` constructor argument is deprecated and will be "
        "removed in 0.2.x. Pass authentication via `auth_provider=` instead, "
        'e.g. `auth_provider=StaticAuthProvider({"Authorization": f"Bearer '
        '{token}"})` (StaticAuthProvider is exported from honua_sdk.auth).',
        DeprecationWarning,
        stacklevel=stacklevel,
    )


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


def parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header value into seconds, if possible.

    Accepts either the delta-seconds form (``"120"``) or the RFC 7231
    HTTP-date form (``"Wed, 21 Oct 2026 07:28:00 GMT"``). For HTTP-date
    values the returned delay is ``max(0, target - now)`` so a date in
    the past becomes ``0.0``. Returns ``None`` for ``None`` input or any
    value that cannot be parsed as either form.

    Non-finite delta-seconds values (``"inf"``, ``"infinity"``, ``"nan"``,
    ``"1e400"``) are rejected as unparseable rather than producing an
    effectively infinite (or instant-retry) sleep. The caller is then free
    to fall back to bounded exponential backoff.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except (TypeError, ValueError):
        seconds = None
    # Reject inf/-inf/nan: a non-finite ``Retry-After`` would otherwise flow
    # un-capped into ``time.sleep`` and hang the client forever (or, for
    # ``nan``, silently coerce to retry-immediately). Treat it as "not a
    # delta-seconds value" so the HTTP-date branch (also a no-match here)
    # ultimately yields ``None``.
    if seconds is not None and not math.isfinite(seconds):
        seconds = None
    if seconds is not None:
        return max(0.0, seconds)
    try:
        target = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    if target.tzinfo is None:
        # RFC 7231 dates carry a zone; treat naive as UTC for safety.
        target = target.replace(tzinfo=UTC)
    return max(0.0, (target - datetime.now(UTC)).total_seconds())


# Back-compat alias for callers still pinned to the underscore spelling
# (re-exported from ``honua_sdk._shared`` and ``honua_sdk.http``).
_parse_retry_after = parse_retry_after


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

    status_code = response.status_code
    request_id = (
        response.headers.get("x-request-id")
        or response.headers.get("honua-request-id")
        or response.headers.get("x-correlation-id")
    )
    headers = dict(response.headers)
    if status_code in (401, 403):
        return HonuaAuthError(
            status_code,
            message,
            body=body,
            request_id=request_id,
            headers=headers,
        )
    if status_code == 429:
        retry_after = _parse_retry_after(response.headers.get("retry-after"))
        return HonuaRateLimitError(
            status_code,
            message,
            body=body,
            retry_after=retry_after,
            request_id=request_id,
            headers=headers,
        )
    return HonuaHttpError(
        status_code,
        message,
        body=body,
        request_id=request_id,
        headers=headers,
    )


def _to_transport_error(error: httpx.HTTPError) -> HonuaTransportError:
    """Map an httpx transport-level error to the Honua exception hierarchy.

    ``httpx.TimeoutException`` becomes :class:`HonuaTimeoutError`; every
    other transport-level :class:`httpx.RequestError` (and any other
    :class:`httpx.HTTPError` arriving without a response) becomes
    :class:`HonuaTransportError`.
    """
    message = str(error) or error.__class__.__name__
    request = getattr(error, "request", None)
    url = str(request.url) if request is not None else None
    detail = f"Transport error: {message}"

    if isinstance(error, httpx.TimeoutException):
        exc: HonuaTransportError = HonuaTimeoutError(detail)
    else:
        exc = HonuaTransportError(detail)

    exc.cause_type = error.__class__.__name__  # type: ignore[attr-defined]
    exc.url = url  # type: ignore[attr-defined]
    return exc
