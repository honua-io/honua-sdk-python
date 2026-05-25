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

import random

import httpx

from ._http import parse_retry_after

_DEFAULT_RETRY_STATUSES: frozenset[int] = frozenset({429, 502, 503, 504})
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
    7231 HTTP-date), the parsed value is returned verbatim and is not
    jittered. Otherwise the exponential backoff (see
    :func:`compute_backoff`) is used.
    """
    retry_after = parse_retry_after(response.headers.get("retry-after"))
    if retry_after is not None:
        return retry_after
    return compute_backoff(
        attempt,
        backoff_initial=backoff_initial,
        backoff_max=backoff_max,
        jitter=jitter,
    )


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
    "compute_backoff",
    "compute_delay",
    "normalize_retry_methods",
    "should_retry_method",
    "should_retry_status",
]
