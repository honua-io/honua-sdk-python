"""Asynchronous retry transport wrapper for httpx.

This module owns only the **asynchronous I/O dispatch** for retries: it drives
``self._wrapped.handle_async_request`` and ``asyncio.sleep`` between attempts.
Every pure policy decision (transient-exception set, should-retry-on
status/method, exponential backoff math, ``Retry-After`` parsing) lives in the
shared, I/O-free :mod:`honua_sdk._retry_core`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from ._retry_core import (
    _DEFAULT_INITIAL_BACKOFF,
    _DEFAULT_MAX_BACKOFF,
    _DEFAULT_MAX_RETRIES,
    _DEFAULT_RETRY_METHODS,
    _DEFAULT_RETRY_STATUSES,
    _RETRIABLE_TRANSPORT_EXCEPTIONS,
    AsyncAuthRefreshHook,
    can_replay_request,
    compute_backoff,
    compute_delay,
    is_auth_challenge_response,
    needs_envelope_inspection,
    normalize_retry_methods,
    retry_trigger_label,
    should_retry_method,
    should_retry_response,
)

__all__ = [
    "AsyncNonClosingTransport",
    "AsyncRetryTransport",
]

_LOGGER = logging.getLogger("honua_sdk.transport")


@dataclass
class _RetryState:
    request: httpx.Request
    budget: int
    remaining: int
    attempt: int = 0
    auth_refreshed: bool = False


class AsyncNonClosingTransport(httpx.AsyncBaseTransport):
    """Asynchronous transport wrapper whose ``aclose`` does not close the wrapped transport.

    Used by ``with_options`` / ``copy`` when an independently-owned clone must
    reuse a caller-supplied transport: the clone owns its own
    :class:`httpx.AsyncClient`, so closing it would otherwise tear down the
    shared transport's connection pool and break the original client that still
    depends on it. Ownership of the wrapped transport stays with the original.
    """

    def __init__(self, wrapped: httpx.AsyncBaseTransport) -> None:
        self._wrapped = wrapped

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._wrapped.handle_async_request(request)

    async def aclose(self) -> None:
        # Intentionally a no-op: the original client owns the wrapped transport.
        return None


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
        self._auth_refresh: AsyncAuthRefreshHook | None = None

    @property
    def retry_methods(self) -> frozenset[str]:
        """The set of HTTP methods that this transport will retry."""
        return self._retry_methods

    def set_auth_refresh(self, hook: AsyncAuthRefreshHook | None) -> None:
        """Configure a reactive auth-refresh hook for 401/498/499 challenges."""
        self._auth_refresh = hook

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        budget = self._resolve_retry_budget(request)
        state = _RetryState(request=request, budget=budget, remaining=budget)

        while True:
            try:
                response = await self._wrapped.handle_async_request(request)
            except _RETRIABLE_TRANSPORT_EXCEPTIONS as exc:
                if state.remaining <= 0:
                    raise
                await self._wait_after_transport_error(exc, state)
                continue

            if needs_envelope_inspection(response):
                await response.aread()

            if not state.auth_refreshed and await self._try_auth_refresh(request, response):
                state.auth_refreshed = True
                continue

            if state.remaining <= 0 or not should_retry_response(response, self._retry_statuses):
                return response

            await self._wait_after_response(response, state)

    def _resolve_retry_budget(self, request: httpx.Request) -> int:
        if not should_retry_method(request.method, self._retry_methods):
            return 0
        override = request.extensions.get("honua_max_retries")
        return override if isinstance(override, int) else self._max_retries

    async def _try_auth_refresh(self, request: httpx.Request, response: httpx.Response) -> bool:
        if self._auth_refresh is None or not is_auth_challenge_response(response):
            return False
        if not can_replay_request(request):
            return False
        if not await self._auth_refresh(request):
            return False
        _LOGGER.debug("Retrying %s %s after reactive auth refresh", request.method, request.url.path)
        await response.aread()
        await response.aclose()
        return True

    async def _wait_after_transport_error(self, exc: Exception, state: _RetryState) -> None:
        delay = self._compute_backoff(state.attempt)
        _LOGGER.debug(
            "Retrying %s %s after transport error %s (attempt %s/%s, delay %.3fs)",
            state.request.method,
            state.request.url.path,
            exc.__class__.__name__,
            state.attempt + 1,
            state.budget,
            delay,
        )
        await asyncio.sleep(delay)
        state.remaining -= 1
        state.attempt += 1

    async def _wait_after_response(self, response: httpx.Response, state: _RetryState) -> None:
        delay = self._compute_delay(response, state.attempt)
        _LOGGER.debug(
            "Retrying %s %s after %s (attempt %s/%s, delay %.3fs)",
            state.request.method,
            state.request.url.path,
            retry_trigger_label(response),
            state.attempt + 1,
            state.budget,
            delay,
        )
        # Read and close the unsuccessful response BEFORE sleeping so the
        # underlying connection is returned to the pool during the backoff
        # window. Holding it across the sleep would tie up pooled capacity
        # under a 429/503 storm exactly when the server is already degraded.
        await response.aread()
        await response.aclose()
        await asyncio.sleep(delay)
        state.remaining -= 1
        state.attempt += 1

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
