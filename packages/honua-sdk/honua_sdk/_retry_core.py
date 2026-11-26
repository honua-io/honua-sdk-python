"""Pure helpers shared by the sync and async retry transports.

This module is the **single source of truth** for the retry policy
(constants, transient-exception set, backoff math, ``Retry-After``
parsing, and the should-retry decision). The sync transport in
:mod:`honua_sdk._retry` and the async transport in
:mod:`honua_sdk._async_retry` both delegate every non-I/O decision
to functions defined here.

The boundary between this module and the two transport modules is::

    _retry_core (this module)  -> pure functions, no I/O, no sleep
    _retry                     -> sync I/O dispatch + time.sleep
    _async_retry               -> async I/O dispatch + asyncio.sleep

After this split, the only meaningful difference between
``RetryTransport`` and ``AsyncRetryTransport`` is the choice of
``handle_request`` vs ``handle_async_request`` and the sleep primitive
they use between attempts.
"""

from __future__ import annotations

import math
import random
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeAlias

import httpx

from ._http import parse_retry_after

AuthRefreshHook: TypeAlias = Callable[[httpx.Request], bool]
AsyncAuthRefreshHook: TypeAlias = Callable[[httpx.Request], Awaitable[bool]]

_HTTP_OK = 200
_HTTP_UNAUTHORIZED = 401
_DEFAULT_RETRY_STATUSES: frozenset[int] = frozenset({429, 502, 503, 504})
_GEOSERVICES_RETRY_CODES: frozenset[int] = frozenset({429, 503})
_GEOSERVICES_AUTH_CHALLENGE_CODES: frozenset[int] = frozenset({401, 498, 499})
_DEFAULT_RETRY_METHODS: frozenset[str] = frozenset(
    {"GET", "HEAD", "PUT", "DELETE", "OPTIONS"}
)

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_INITIAL_BACKOFF = 0.5  # 500 ms
_DEFAULT_MAX_BACKOFF = 5.0  # 5 s

# Transport-level exceptions treated as transient. ``TimeoutException`` is
# included as a base class so its subclasses (``ConnectTimeout``,
# ``ReadTimeout``, ``WriteTimeout``, ``PoolTimeout``) all match.
_RETRIABLE_TRANSPORT_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
    httpx.ProxyError,
    httpx.TimeoutException,
)


def compute_backoff(
    attempt: int,
    *,
    backoff_initial: float,
    backoff_max: float,
    jitter: bool,
) -> float:
    """Return the (optionally jittered) exponential backoff for ``attempt``.

    For attempt ``n`` (0-indexed), the cap is
    ``min(backoff_initial * 2**n, backoff_max)``. When ``jitter`` is
    ``True`` the actual delay is drawn from ``random.uniform(0, cap)``
    (full-jitter); otherwise the deterministic cap is returned verbatim.
    """
    computed: float = backoff_initial * (2**attempt)
    capped: float = min(computed, backoff_max)
    if jitter:
        # random.uniform is typed as Any in some stubs; declare the float.
        jittered: float = random.uniform(0.0, capped)  # noqa: S311 -- jitter timing, not security
        return jittered
    return capped


def compute_delay(
    response: httpx.Response,
    attempt: int,
    *,
    backoff_initial: float,
    backoff_max: float,
    jitter: bool,
) -> float:
    """Return the delay before the next retry, honouring ``Retry-After``.

    When ``Retry-After`` is present and parseable (delta-seconds or RFC
    7231 HTTP-date), the parsed value is clamped to ``backoff_max`` and
    returned (un-jittered). Clamping keeps a server-sent header (e.g.
    ``Retry-After: 86400``) from blocking far longer than the configured
    ceiling, matching the JS SDK. Otherwise the exponential backoff (see
    :func:`compute_backoff`) is used.
    """
    retry_after = parse_retry_after(response.headers.get("retry-after"))
    if retry_after is None:
        retry_after = _envelope_retry_after(response)
    if retry_after is not None:
        return min(retry_after, backoff_max)
    return compute_backoff(
        attempt,
        backoff_initial=backoff_initial,
        backoff_max=backoff_max,
        jitter=jitter,
    )


def parse_retryable_header(response: httpx.Response) -> bool | None:
    """Parse ``Honua-Retryable`` (or ``Honua-Error-Retryable``) header."""
    raw = response.headers.get("honua-retryable") or response.headers.get("honua-error-retryable")
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _is_json_content_type(response: httpx.Response) -> bool:
    raw = response.headers.get("content-type", "")
    media_type = raw.split(";", 1)[0].strip().lower()
    return media_type in ("application/json", "text/json") or media_type.endswith("+json")


def needs_envelope_inspection(response: httpx.Response) -> bool:
    """Return whether an HTTP 200 response should be buffered to inspect for an error envelope."""
    if response.status_code != _HTTP_OK:
        return False
    return _is_json_content_type(response) or parse_retryable_header(response) is True


def extract_geoservices_error(response: httpx.Response) -> Mapping[str, Any] | None:
    """Return the ``error`` mapping from an HTTP 200 GeoServices error envelope, if any."""
    if not needs_envelope_inspection(response) or not response.content:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, Mapping):
        return None
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    if not isinstance(code, int) or isinstance(code, bool):
        return None
    return error


def _envelope_retry_after(response: httpx.Response) -> float | None:
    error = extract_geoservices_error(response)
    if error is None:
        return None
    value = error.get("retryAfterSeconds")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def should_retry_method(method: str, retry_methods: frozenset[str]) -> bool:
    """Return whether ``method`` is eligible for retry given ``retry_methods``.

    The comparison is case-insensitive: the request method is uppercased
    before being checked against ``retry_methods`` (which the transports
    normalize at construction time).
    """
    return method.upper() in retry_methods


def should_retry_status(
    status_code: int,
    retry_statuses: frozenset[int],
) -> bool:
    """Return whether a response with ``status_code`` triggers a retry."""
    return status_code in retry_statuses


def should_retry_response(
    response: httpx.Response,
    retry_statuses: frozenset[int],
) -> bool:
    """Return whether ``response`` should be retried.

    Honours explicit ``Honua-Retryable: false`` on any status (so non-retryable
    503 responses such as ``CAPABILITY_UNAVAILABLE`` are never blindly retried),
    and retries HTTP 200 GeoServices error envelopes carrying ``429``/``503`` or
    explicit ``Honua-Retryable: true``.
    """
    header_retryable = parse_retryable_header(response)
    if header_retryable is False:
        return False
    if response.status_code != _HTTP_OK:
        return should_retry_status(response.status_code, retry_statuses)
    return _should_retry_geoservices_envelope(response, retry_statuses, header_retryable=header_retryable)


def _should_retry_geoservices_envelope(
    response: httpx.Response,
    retry_statuses: frozenset[int],
    *,
    header_retryable: bool | None,
) -> bool:
    error = extract_geoservices_error(response)
    if error is None:
        return False
    body_retryable = error.get("retryable")
    if body_retryable is False:
        return False
    if header_retryable is True or body_retryable is True:
        return True
    code = error.get("code")
    return isinstance(code, int) and code in _GEOSERVICES_RETRY_CODES and code in retry_statuses


def is_auth_challenge_response(response: httpx.Response) -> bool:
    """Return whether ``response`` is an HTTP 401 or GeoServices 401/498/499 auth challenge."""
    if response.status_code == _HTTP_UNAUTHORIZED:
        return True
    error = extract_geoservices_error(response)
    if error is None:
        return False
    return error.get("code") in _GEOSERVICES_AUTH_CHALLENGE_CODES


def can_replay_request(request: httpx.Request) -> bool:
    """Return whether ``request`` carries a replayable body stream."""
    return isinstance(request.stream, httpx.ByteStream)


def retry_trigger_label(response: httpx.Response) -> str:
    """Format a concise log label describing why ``response`` triggered a retry."""
    if response.status_code != _HTTP_OK:
        return f"HTTP {response.status_code}"
    error = extract_geoservices_error(response)
    code = error.get("code") if error is not None else response.status_code
    return f"GeoServices error {code} (HTTP 200)"


def normalize_retry_methods(methods: frozenset[str]) -> frozenset[str]:
    """Uppercase every entry in ``methods`` so lookups are case-insensitive."""
    return frozenset(m.upper() for m in methods)


__all__ = [
    "_DEFAULT_INITIAL_BACKOFF",
    "_DEFAULT_MAX_BACKOFF",
    "_DEFAULT_MAX_RETRIES",
    "_DEFAULT_RETRY_METHODS",
    "_DEFAULT_RETRY_STATUSES",
    "_RETRIABLE_TRANSPORT_EXCEPTIONS",
    "AsyncAuthRefreshHook",
    "AuthRefreshHook",
    "can_replay_request",
    "compute_backoff",
    "compute_delay",
    "extract_geoservices_error",
    "is_auth_challenge_response",
    "needs_envelope_inspection",
    "normalize_retry_methods",
    "parse_retryable_header",
    "retry_trigger_label",
    "should_retry_method",
    "should_retry_response",
    "should_retry_status",
]
