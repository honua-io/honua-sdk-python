"""Error types for the Honua Python SDK.

Hierarchy:

* :class:`HonuaError` — root for every SDK failure.

  * :class:`HonuaCapabilityNotSupportedError` — a source/protocol cannot
    satisfy the requested capability.
  * :class:`HonuaHttpError` — server returned a non-success HTTP response.

    * :class:`HonuaAuthError` — 401 / 403 (auth or authorization failure).
    * :class:`HonuaRateLimitError` — 429 (with optional ``retry_after``).
  * :class:`HonuaTransportError` — request failed before any HTTP response
    (DNS, connect, TLS, read-on-broken-socket, etc.).

    * :class:`HonuaTimeoutError` — the request exceeded its timeout.
  * :class:`HonuaGrpcError` — gRPC call failed.

The subclasses of :class:`HonuaHttpError` are drop-in: existing
``except HonuaHttpError`` handlers continue to catch them. Likewise
:class:`HonuaTimeoutError` is a :class:`HonuaTransportError`, so a single
``except HonuaTransportError`` catches both.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "HonuaAuthError",
    "HonuaCapabilityNotSupportedError",
    "HonuaError",
    "HonuaGrpcError",
    "HonuaHttpError",
    "HonuaRateLimitError",
    "HonuaTimeoutError",
    "HonuaTransportError",
]


class HonuaError(Exception):
    """Base exception for SDK failures.

    Root of the SDK error hierarchy. Catch this (rather than the
    builtin :class:`Exception`) to scope ``try``/``except`` blocks to
    failures originating in honua-sdk transport, protocol, or
    capability resolution. Subclasses surface protocol-specific
    diagnostics (status code, request id, retry-after, gRPC status,
    etc.).
    """


class HonuaCapabilityNotSupportedError(HonuaError):
    """Raised when a source protocol does not support a requested capability."""

    def __init__(
        self,
        capability: str,
        protocol: str,
        *,
        source_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        message = f"Capability {capability!r} is not supported for protocol {protocol!r}"
        if source_id is not None:
            message = f"{message} on source {source_id!r}"
        if reason:
            message = f"{message}: {reason}"
        super().__init__(message)
        self.capability = capability
        self.protocol = protocol
        self.source_id = source_id
        self.reason = reason


class HonuaHttpError(HonuaError):
    """Raised when an API request returns a non-success response.

    Holds the HTTP ``status_code``, a server-supplied ``message``, and the
    raw response ``body`` (parsed JSON when available, raw text otherwise).
    The ``request_id`` attribute carries the server's correlation identifier
    (extracted from ``x-request-id``, ``Honua-Request-Id``, or
    ``X-Correlation-ID`` response headers, case-insensitive) when available,
    and ``headers`` exposes the full response headers as a plain ``dict`` for
    debugging.

    Status-specific subclasses (:class:`HonuaAuthError`,
    :class:`HonuaRateLimitError`) are raised for well-known codes so callers
    can ``except`` them individually while still catching
    :class:`HonuaHttpError` for the general case.

    Attributes:
        status_code: HTTP response status code.
        message: Server-supplied error message (defaults to the
            response reason phrase when none was provided in the body).
        body: Parsed JSON body when available, otherwise the raw
            response text or ``None``.
        request_id: Server correlation id parsed from the response
            headers (``x-request-id`` / ``Honua-Request-Id`` /
            ``X-Correlation-ID``), or ``None`` when not present.
        headers: Full response headers as a plain ``dict[str, str]``.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        body: Any | None = None,
        request_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.body = body
        self.request_id = request_id
        self.headers: Mapping[str, str] = dict(headers) if headers is not None else {}


class HonuaAuthError(HonuaHttpError):
    """HTTP 401/403 — authentication or authorization failure.

    Subclass of :class:`HonuaHttpError`; existing ``except HonuaHttpError``
    handlers catch these unchanged.

    Attributes:
        status_code: ``401`` (auth failure) or ``403`` (authorization
            failure).
        message: Server-supplied error message.
        body: Parsed JSON body when available, otherwise the raw text.
        request_id: Server correlation id, when present in the response
            headers.
        headers: Full response headers as a plain ``dict[str, str]``.
    """


class HonuaRateLimitError(HonuaHttpError):
    """HTTP 429 — the server rejected the request as rate-limited.

    Subclass of :class:`HonuaHttpError`. The optional ``retry_after``
    attribute carries the parsed ``Retry-After`` response header (seconds)
    when present and well-formed, otherwise ``None``.

    Attributes:
        status_code: HTTP ``429``.
        message: Server-supplied error message.
        body: Parsed JSON body when available, otherwise the raw text.
        retry_after: Parsed ``Retry-After`` value in seconds (float),
            or ``None`` when the header was absent / unparseable.
        request_id: Server correlation id, when present in the response
            headers.
        headers: Full response headers as a plain ``dict[str, str]``.
    """

    def __init__(  # noqa: PLR0913 — kwarg-only fields surface server diagnostics
        self,
        status_code: int,
        message: str,
        *,
        body: Any | None = None,
        retry_after: float | None = None,
        request_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code,
            message,
            body=body,
            request_id=request_id,
            headers=headers,
        )
        self.retry_after = retry_after


class HonuaTransportError(HonuaError):
    """Network-level failure with no HTTP response.

    Covers DNS errors, connection refusals, TLS handshake failures, and
    other transport-level conditions where no HTTP status was received.
    Catch this (or its parent :class:`HonuaError`) for retry-style logic
    that does not depend on a response body. Wraps the underlying
    :class:`httpx.HTTPError` via the standard ``__cause__`` chain when
    raised by the SDK transport layer.
    """


class HonuaTimeoutError(HonuaTransportError):
    """Request exceeded the configured timeout.

    Subclass of :class:`HonuaTransportError`; catch the parent class to
    treat timeouts and other transport failures uniformly. Raised when
    the underlying :class:`httpx.Timeout` (connect / read / write / pool)
    fires before the server returns a response.
    """


class HonuaGrpcError(HonuaError):
    """Raised when a gRPC call fails."""

    def __init__(self, code: Any, message: str, details: Any = None) -> None:
        code_display = getattr(code, "name", code)
        super().__init__(f"gRPC {code_display}: {message}")
        self.code = code
        self.message = message
        self.details = details
