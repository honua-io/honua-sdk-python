"""Async retry transport wrapper for httpx.

This module owns only the **async I/O dispatch** for retries: it awaits
``self._wrapped.handle_async_request`` and ``asyncio.sleep`` between
attempts. Every pure policy decision (transient-exception set,
should-retry-on status/method, exponential backoff math,
``Retry-After`` parsing) lives in :mod:`honua_sdk._retry_core` and is
shared verbatim with the sync counterpart in :mod:`honua_sdk._retry`.

Boundary recap::

    _retry_core   -> pure functions, no I/O
    _retry        -> sync I/O dispatch + ``time.sleep``
    _async_retry  -> async I/O dispatch + ``asyncio.sleep``   (this module)
"""

from __future__ import annotations

import asyncio

import httpx

from ._retry_core import (
    _DEFAULT_INITIAL_BACKOFF,
    _DEFAULT_MAX_BACKOFF,
    _DEFAULT_MAX_RETRIES,
    _DEFAULT_RETRY_METHODS,
    _DEFAULT_RETRY_STATUSES,
    _RETRIABLE_TRANSPORT_EXCEPTIONS,
    compute_backoff,
    compute_delay,
    normalize_retry_methods,
    should_retry_method,
    should_retry_status,
)

__all__ = [
    "AsyncRetryTransport",
]


class AsyncRetryTransport(httpx.AsyncBaseTransport):
    """An async httpx transport wrapper that retries on transient HTTP errors.

    Retries are triggered for responses whose status codes are listed in
    ``retry_statuses`` (default: ``429``, ``502``, ``503``, ``504``).
    Exponential backoff is applied between attempts, and the
    ``Retry-After`` header is honoured on 429/503 responses (either
    delta-seconds or an RFC 7231 HTTP-date).

    **Idempotency gating.** Only requests whose method is in
    ``retry_methods`` (default: ``GET``, ``HEAD``, ``PUT``, ``DELETE``,
    ``OPTIONS``) are retried. ``POST`` and other non-idempotent methods
    are intentionally excluded so that mutations are never silently
    duplicated. Callers who know their POSTs are safe (e.g. carry an
    idempotency key) can opt-in by passing ``retry_methods`` explicitly.

    **Backoff math.** For retry attempt ``n`` (0-indexed), the cap is
    ``min(backoff_initial * 2**n, backoff_max)``. When ``jitter`` is
    ``True`` (default), the actual sleep is drawn from
    ``random.uniform(0, cap)`` (full-jitter). When ``False``, the
    deterministic ``cap`` value is used. The ``Retry-After`` header,
    when present and parseable, is honoured verbatim and is never
    jittered. The attempt counter resets per request.

    Parameters
    ----------
    wrapped:
        The real async transport to delegate to.
    max_retries:
        Maximum number of retry attempts (excluding the initial request).
        Set to ``0`` to disable retrying.
    backoff_initial:
        Initial backoff base in seconds. The exponential schedule is
        ``backoff_initial * 2**attempt`` (capped at ``backoff_max``).
    backoff_max:
        Upper bound for the backoff duration in seconds.
    jitter:
        When ``True`` (default) apply *full jitter* to the computed
        exponential backoff cap.
    retry_methods:
        HTTP methods (uppercase) eligible for retry. Defaults to the
        idempotent set ``{GET, HEAD, PUT, DELETE, OPTIONS}``.
    retry_statuses:
        Response status codes that trigger a retry. Defaults to
        ``{429, 502, 503, 504}``.
    """

    def __init__(
        self,
        wrapped: httpx.AsyncBaseTransport,
        *,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        backoff_initial: float = _DEFAULT_INITIAL_BACKOFF,
        backoff_max: float = _DEFAULT_MAX_BACKOFF,
        jitter: bool = True,
        retry_methods: frozenset[str] = _DEFAULT_RETRY_METHODS,
        retry_statuses: frozenset[int] = _DEFAULT_RETRY_STATUSES,
    ) -> None:
        self._wrapped = wrapped
        self._max_retries = max_retries
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._jitter = jitter
        self._retry_methods = normalize_retry_methods(retry_methods)
        self._retry_statuses = retry_statuses

    @property
    def retry_methods(self) -> frozenset[str]:
        """The set of HTTP methods that this transport will retry."""
        return self._retry_methods

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # Idempotency gate: non-retriable methods get a single attempt.
        if not should_retry_method(request.method, self._retry_methods):
            return await self._wrapped.handle_async_request(request)

        # Per-request override: ``AsyncHonuaClient.with_options(max_retries=…)``
        # signals an override by stashing the value in ``request.extensions``.
        override = request.extensions.get("honua_max_retries")
        retries_remaining = override if isinstance(override, int) else self._max_retries
        attempt = 0

        while True:
            try:
                response = await self._wrapped.handle_async_request(request)
            except _RETRIABLE_TRANSPORT_EXCEPTIONS:
                if retries_remaining <= 0:
                    raise
                delay = self._compute_backoff(attempt)
                await asyncio.sleep(delay)
                retries_remaining -= 1
                attempt += 1
                continue

            if retries_remaining <= 0 or not should_retry_status(
                response.status_code, self._retry_statuses
            ):
                return response

            delay = self._compute_delay(response, attempt)
            await asyncio.sleep(delay)

            # Read and close the unsuccessful response before retrying so the
            # underlying connection is released.
            await response.aread()
            await response.aclose()

            retries_remaining -= 1
            attempt += 1

    def _compute_delay(self, response: httpx.Response, attempt: int) -> float:
        return compute_delay(
            response,
            attempt,
            backoff_initial=self._backoff_initial,
            backoff_max=self._backoff_max,
            jitter=self._jitter,
        )

    def _compute_backoff(self, attempt: int) -> float:
        return compute_backoff(
            attempt,
            backoff_initial=self._backoff_initial,
            backoff_max=self._backoff_max,
            jitter=self._jitter,
        )

    async def aclose(self) -> None:
        await self._wrapped.aclose()
