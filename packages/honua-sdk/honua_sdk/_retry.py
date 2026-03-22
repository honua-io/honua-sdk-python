"""Retry transport wrapper with exponential backoff for httpx."""

from __future__ import annotations

import time

import httpx

_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503})

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_INITIAL_BACKOFF = 0.5  # 500 ms
_DEFAULT_MAX_BACKOFF = 5.0  # 5 s


class RetryTransport(httpx.BaseTransport):
    """An httpx transport wrapper that retries on transient HTTP errors.

    Retries are triggered for responses with status codes 429, 502, or 503.
    Exponential backoff is applied between attempts, and the ``Retry-After``
    header is honoured on 429 and 503 responses.

    Parameters
    ----------
    wrapped:
        The real transport to delegate to.
    max_retries:
        Maximum number of retry attempts (excluding the initial request).
        Set to ``0`` to disable retrying.
    backoff_initial:
        Initial backoff duration in seconds (doubled on each subsequent retry).
    backoff_max:
        Upper bound for the backoff duration in seconds.
    """

    def __init__(
        self,
        wrapped: httpx.BaseTransport,
        *,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        backoff_initial: float = _DEFAULT_INITIAL_BACKOFF,
        backoff_max: float = _DEFAULT_MAX_BACKOFF,
    ) -> None:
        self._wrapped = wrapped
        self._max_retries = max_retries
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._wrapped.handle_request(request)

        retries_remaining = self._max_retries
        backoff = self._backoff_initial

        while retries_remaining > 0 and response.status_code in _RETRYABLE_STATUS_CODES:
            delay = self._compute_delay(response, backoff)
            time.sleep(delay)

            # Read and close the unsuccessful response before retrying so the
            # underlying connection is released.
            response.read()
            response.close()

            response = self._wrapped.handle_request(request)

            retries_remaining -= 1
            backoff = min(backoff * 2, self._backoff_max)

        return response

    @staticmethod
    def _compute_delay(response: httpx.Response, backoff: float) -> float:
        """Return the delay to use before the next retry attempt.

        If the response contains a ``Retry-After`` header with a valid
        integer value, that value (in seconds) is used instead of the
        calculated exponential backoff.
        """
        retry_after = response.headers.get("retry-after")
        if retry_after is not None:
            try:
                return max(0.0, float(retry_after))
            except (ValueError, OverflowError):
                pass
        return backoff

    def close(self) -> None:
        self._wrapped.close()
