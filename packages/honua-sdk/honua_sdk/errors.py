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

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeAlias

__all__ = [
    "FailureKind",
    "FieldFailure",
    "HonuaAuthError",
    "HonuaCapabilityNotSupportedError",
    "HonuaError",
    "HonuaGrpcError",
    "HonuaHttpError",
    "HonuaRateLimitError",
    "HonuaTimeoutError",
    "HonuaTransportError",
    "ProtocolMetadata",
    "TerminalFailureReceipt",
]


class FailureKind(StrEnum):
    """Stable failure classes shared across Honua transports."""

    UNKNOWN = "unknown"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not-found"
    VALIDATION = "validation"
    CONFLICT = "conflict"
    THROTTLED = "throttled"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class FieldFailure:
    """One field- or item-addressable failure."""

    code: str | None = None
    severity: str | None = None
    path: str | None = None
    field_id: str | None = None
    item_index: int | None = None
    message: str | None = None


ProtocolValues: TypeAlias = Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class ProtocolMetadata:
    """Safe protocol metadata, separated into initial headers and trailers."""

    initial: ProtocolValues
    trailing: ProtocolValues


@dataclass(frozen=True, slots=True)
class TerminalFailureReceipt:
    """Machine-actionable terminal failure data retained without flattening."""

    transport_status: int | None
    protocol_code: str | None
    kind: FailureKind
    code: str
    retryable: bool
    retry_after_seconds: float | None
    correlation_id: str | None
    field_errors: tuple[FieldFailure, ...]
    protocol_metadata: ProtocolMetadata


_SENSITIVE_METADATA = frozenset({"authorization", "cookie", "set-cookie", "x-api-key"})
_HTTP_KINDS = {
    400: FailureKind.VALIDATION,
    401: FailureKind.AUTHENTICATION,
    403: FailureKind.AUTHORIZATION,
    404: FailureKind.NOT_FOUND,
    409: FailureKind.CONFLICT,
    412: FailureKind.CONFLICT,
    422: FailureKind.VALIDATION,
    428: FailureKind.CONFLICT,
    429: FailureKind.THROTTLED,
    498: FailureKind.AUTHORIZATION,
    499: FailureKind.AUTHORIZATION,
}
_RETRYABLE_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})
_SERVER_ERROR_MIN = 500


def _metadata(values: Mapping[str, Any] | None) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for key, value in (values or {}).items():
        normalized = str(key).lower()
        if normalized in _SENSITIVE_METADATA:
            continue
        sequence = value if isinstance(value, (list, tuple)) else (value,)
        result[normalized] = tuple(
            item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
            for item in sequence
        )
    return result


def _first(metadata: ProtocolValues, *keys: str) -> str | None:
    for key in keys:
        values = metadata.get(key)
        if values:
            return values[0]
    return None


def _kind(value: object, fallback: FailureKind) -> FailureKind:
    if isinstance(value, str):
        try:
            return FailureKind(value)
        except ValueError:
            pass
    return fallback


def _http_kind(code: int, transport_status: int) -> FailureKind:
    kind = _HTTP_KINDS.get(code)
    if kind is not None:
        return kind
    if code in _RETRYABLE_HTTP_CODES or transport_status >= _SERVER_ERROR_MIN:
        return FailureKind.UNAVAILABLE
    return FailureKind.UNKNOWN


def _grpc_kind(code: int) -> FailureKind:
    return {
        16: FailureKind.AUTHENTICATION,
        7: FailureKind.AUTHORIZATION,
        5: FailureKind.NOT_FOUND,
        3: FailureKind.VALIDATION,
        6: FailureKind.CONFLICT,
        10: FailureKind.CONFLICT,
        8: FailureKind.THROTTLED,
        4: FailureKind.UNAVAILABLE,
        14: FailureKind.UNAVAILABLE,
    }.get(code, FailureKind.UNKNOWN)


def _default_code(kind: FailureKind) -> str:
    return {
        FailureKind.AUTHENTICATION: "authentication_required",
        FailureKind.AUTHORIZATION: "permission_denied",
        FailureKind.NOT_FOUND: "resource_not_found",
        FailureKind.VALIDATION: "validation_failed",
        FailureKind.CONFLICT: "resource_conflict",
        FailureKind.THROTTLED: "rate_limited",
        FailureKind.UNAVAILABLE: "service_unavailable",
    }.get(kind, "unknown_failure")


def _field_errors(value: object) -> tuple[FieldFailure, ...]:
    failures: list[FieldFailure] = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            failures.append(
                FieldFailure(
                    code=item.get("code") if isinstance(item.get("code"), str) else None,
                    severity=item.get("severity") if isinstance(item.get("severity"), str) else None,
                    path=item.get("path") if isinstance(item.get("path"), str) else None,
                    field_id=item.get("fieldId") if isinstance(item.get("fieldId"), str) else None,
                    item_index=item.get("itemIndex") if isinstance(item.get("itemIndex"), int) else None,
                    message=item.get("message") if isinstance(item.get("message"), str) else None,
                )
            )
    elif isinstance(value, Mapping):
        for field_id, messages in value.items():
            if isinstance(messages, list):
                failures.extend(
                    FieldFailure(path=str(field_id), field_id=str(field_id), message=message)
                    for message in messages
                    if isinstance(message, str)
                )
    return tuple(failures)


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return None


def _http_failure_receipt(
    *,
    transport_status: int,
    body: Any | None,
    headers: Mapping[str, Any] | None,
    protocol_code: int | None = None,
    retry_after_seconds: float | None = None,
) -> TerminalFailureReceipt:
    root = body if isinstance(body, Mapping) else {}
    error = root.get("error")
    source = error if isinstance(error, Mapping) else root
    classification_code = protocol_code if protocol_code is not None else transport_status
    kind = _kind(source.get("kind"), _http_kind(classification_code, transport_status))
    declared_code = source.get("machineCode") or source.get("code")
    code = declared_code if isinstance(declared_code, str) else _default_code(kind)
    declared_retryable = source.get("retryable")
    retryable = (
        declared_retryable
        if isinstance(declared_retryable, bool)
        else classification_code in _RETRYABLE_HTTP_CODES
    )
    safe_headers = _metadata(headers)
    correlation_id = source.get("correlationId") or root.get("correlationId") or _first(
        safe_headers, "x-correlation-id", "honua-request-id", "x-request-id"
    )
    declared_retry_after = _number(source.get("retryAfterSeconds"))
    return TerminalFailureReceipt(
        transport_status=transport_status,
        protocol_code=str(protocol_code) if protocol_code is not None else None,
        kind=kind,
        code=code,
        retryable=retryable,
        retry_after_seconds=(
            declared_retry_after
            if declared_retry_after is not None
            else retry_after_seconds
        ),
        correlation_id=correlation_id if isinstance(correlation_id, str) else None,
        field_errors=_field_errors(source.get("errors") or root.get("errors")),
        protocol_metadata=ProtocolMetadata(initial=safe_headers, trailing={}),
    )


def _grpc_code_number(code: Any) -> int:
    value = getattr(code, "value", code)
    if isinstance(value, tuple):
        value = value[0]
    return value if isinstance(value, int) else 2


def _grpc_failure_receipt(
    code: Any,
    initial_metadata: Mapping[str, Any] | None,
    trailing_metadata: Mapping[str, Any] | None,
) -> TerminalFailureReceipt:
    number = _grpc_code_number(code)
    initial = _metadata(initial_metadata)
    trailing = _metadata(trailing_metadata)
    declared_kind = _first(trailing, "honua-error-kind") or _first(initial, "honua-error-kind")
    kind = _kind(declared_kind, _grpc_kind(number))
    machine_code = _first(trailing, "honua-error-code") or _first(initial, "honua-error-code")
    declared_retryable = _first(trailing, "honua-error-retryable") or _first(initial, "honua-error-retryable")
    retryable = declared_retryable == "true" if declared_retryable in ("true", "false") else number in (4, 8, 10, 14)
    retry_after = _number_from_string(_first(trailing, "retry-after") or _first(initial, "retry-after"))
    details = _first(trailing, "honua-error-details") or _first(initial, "honua-error-details")
    try:
        errors: object = json.loads(details) if details else None
    except json.JSONDecodeError:
        errors = None
    return TerminalFailureReceipt(
        transport_status=None,
        protocol_code=str(number),
        kind=kind,
        code=machine_code or _default_code(kind),
        retryable=retryable,
        retry_after_seconds=retry_after,
        correlation_id=_first(trailing, "x-correlation-id", "honua-request-id", "x-request-id")
        or _first(initial, "x-correlation-id", "honua-request-id", "x-request-id"),
        field_errors=_field_errors(errors),
        protocol_metadata=ProtocolMetadata(initial=initial, trailing=trailing),
    )


def _number_from_string(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return _number(float(value))
    except ValueError:
        return None


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
        error_code: The application-level error code reported by an Esri
            GeoServices error envelope (e.g. ``498``/``499`` token errors), when
            the failure originated from such an envelope. ``None`` for ordinary
            transport-level HTTP failures. Distinct from ``status_code`` because
            GeoServices codes are an application code space, not HTTP statuses.
    """

    def __init__(  # noqa: PLR0913 — kwarg-only fields surface server diagnostics
        self,
        status_code: int,
        message: str,
        *,
        body: Any | None = None,
        request_id: str | None = None,
        headers: Mapping[str, str] | None = None,
        error_code: int | None = None,
        receipt: TerminalFailureReceipt | None = None,
    ) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.body = body
        self.request_id = request_id
        self.headers: Mapping[str, str] = dict(headers) if headers is not None else {}
        self.error_code = error_code
        self.receipt = receipt or _http_failure_receipt(
            transport_status=status_code,
            body=body,
            headers=headers,
            protocol_code=error_code,
        )
        self.failure_kind = self.receipt.kind
        self.machine_code = self.receipt.code
        self.retryable = self.receipt.retryable
        self.retry_after = self.receipt.retry_after_seconds
        self.correlation_id = self.receipt.correlation_id
        self.field_errors = self.receipt.field_errors
        self.protocol_metadata = self.receipt.protocol_metadata


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
        error_code: int | None = None,
        receipt: TerminalFailureReceipt | None = None,
    ) -> None:
        super().__init__(
            status_code,
            message,
            body=body,
            request_id=request_id,
            headers=headers,
            error_code=error_code,
            receipt=receipt,
        )
        self.retry_after = self.receipt.retry_after_seconds if retry_after is None else retry_after


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

    def __init__(
        self,
        code: Any,
        message: str,
        details: Any = None,
        *,
        initial_metadata: Mapping[str, Any] | None = None,
        trailing_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        code_display = getattr(code, "name", code)
        super().__init__(f"gRPC {code_display}: {message}")
        self.code = code
        self.message = message
        self.details = details
        self.receipt = _grpc_failure_receipt(code, initial_metadata, trailing_metadata)
        self.failure_kind = self.receipt.kind
        self.machine_code = self.receipt.code
        self.retryable = self.receipt.retryable
        self.retry_after = self.receipt.retry_after_seconds
        self.correlation_id = self.receipt.correlation_id
        self.field_errors = self.receipt.field_errors
        self.protocol_metadata = self.receipt.protocol_metadata
