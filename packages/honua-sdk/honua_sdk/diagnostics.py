"""Sanitized support diagnostics for the :command:`honua doctor` workflow.

The wire artifact is intentionally narrower than runtime SDK context. It emits
only the canonical ``diagnostic-bundle.v1`` fields and never persists raw HTTP
traffic. Bodies are hashed in memory and replaced with bounded metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

import httpx

DIAGNOSTIC_SCHEMA_URL = "https://honua.io/schemas/diagnostic-bundle.v1.json"
DIAGNOSTIC_SCHEMA_SHA256 = "4dd7282d17bb417d56f1c3cfa243e03b612a401e5d22be766658849287e431a9"
DIAGNOSTIC_SCHEMA_BYTES = 6494

_MAX_BODY_BYTES = 25 * 1024 * 1024
_MAX_PROBE_BYTES = 256 * 1024
_MAX_ENVELOPES = 50
_MAX_HEADERS = 32
_MAX_PATH_LENGTH = 2048
_CLASSIFICATIONS = frozenset({"unknown", "public", "internal", "customer-data", "secret-suspected"})
_BUNDLE_KEYS = frozenset({"schemaVersion", "bundleId", "contentClassification", "consent", "envelopes"})
_CONSENT_KEYS = frozenset({"redactionAcknowledged", "shareWithSupport", "grantedBy"})
_ENVELOPE_KEYS = frozenset(
    {
        "method",
        "normalizedPath",
        "statusCode",
        "mediaType",
        "correlationId",
        "traceId",
        "capturedAt",
        "requestHeaders",
        "responseHeaders",
        "requestBody",
        "responseBody",
    }
)
_BODY_KEYS = frozenset({"preview", "contentSha256", "originalByteSize", "redactionApplied", "truncated"})
_SAFE_HEADER_NAMES = {
    "accept": "Accept",
    "content-length": "Content-Length",
    "content-type": "Content-Type",
    "retry-after": "Retry-After",
    "server": "Server",
    "traceparent": "Traceparent",
    "x-correlation-id": "X-Correlation-Id",
    "x-honua-version": "X-Honua-Version",
    "x-request-id": "X-Request-Id",
}
_SAFE_PATH_SEGMENTS = frozenset(
    {
        "api",
        "v1",
        "rest",
        "services",
        "FeatureServer",
        "MapServer",
        "query",
        "healthz",
        "ready",
        "ogc",
        "collections",
        "items",
        "conformance",
    }
)
_SAFE_QUERY_NAMES = frozenset({"f", "format", "limit", "offset", "page", "status"})
_SECRET_PATTERN = re.compile(
    r"(?i)(?:bearer\s+|basic\s+|password\s*[=:]|secret\s*[=:]|token\s*[=:]|api[-_]?key\s*[=:]"
    r"|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|[^\s/@]+@[^\s/@]+\.[^\s/@]+)"
)


class DiagnosticError(ValueError):
    """Base class for safe diagnostic validation and sanitization failures."""


class DiagnosticSafetyError(DiagnosticError):
    """Raised before output or network effects when diagnostic input is unsafe."""


class DiagnosticValidationError(DiagnosticError):
    """Raised when a bundle does not conform to the pinned v1 contract."""

    def __init__(self, errors: Sequence[str]) -> None:
        super().__init__("Diagnostic bundle failed pinned-schema validation.")
        self.errors = tuple(errors)


def validate_diagnostic_bundle(value: object) -> tuple[str, ...]:
    """Validate *value* against the pinned canonical v1 wire constraints."""
    errors: list[str] = []
    if not isinstance(value, dict):
        return ("$: expected type 'object'",)
    _unexpected(value, _BUNDLE_KEYS, "$", errors)
    _required(value, ("schemaVersion", "contentClassification", "consent", "envelopes"), "$", errors)
    _string(value, "schemaVersion", "$", errors, maximum=3, constant="1.0")
    _string(value, "bundleId", "$", errors, maximum=64)
    classification = _string(value, "contentClassification", "$", errors, maximum=32)
    if classification is not None and classification not in _CLASSIFICATIONS:
        errors.append("$.contentClassification: value is not in the canonical enum")
    _validate_consent(value.get("consent"), errors)
    envelopes = value.get("envelopes")
    if not isinstance(envelopes, list):
        if "envelopes" in value:
            errors.append("$.envelopes: expected type 'array'")
    else:
        if not envelopes:
            errors.append("$.envelopes: contains fewer than minimum 1 item")
        if len(envelopes) > _MAX_ENVELOPES:
            errors.append("$.envelopes: contains more than maximum 50 items")
        for index, envelope in enumerate(envelopes):
            _validate_envelope(envelope, index, errors)
    return tuple(errors)


def assert_diagnostic_bundle(value: object) -> None:
    """Raise :class:`DiagnosticValidationError` unless *value* is canonical v1."""
    errors = validate_diagnostic_bundle(value)
    if errors:
        raise DiagnosticValidationError(errors)


def create_diagnostic_bundle(
    *,
    content_classification: str,
    redaction_acknowledged: bool,
    share_with_support: bool,
    exchanges: Sequence[Mapping[str, Any]],
    bundle_id: str | None = None,
    granted_by: str | None = None,
) -> dict[str, Any]:
    """Create and validate a canonical bundle from raw in-memory exchanges."""
    if content_classification not in _CLASSIFICATIONS:
        raise DiagnosticSafetyError("Content classification is not supported by diagnostic-bundle.v1.")
    if not isinstance(redaction_acknowledged, bool) or not isinstance(share_with_support, bool):
        raise DiagnosticSafetyError("Both diagnostic consent values must be explicit booleans.")
    if not exchanges:
        raise DiagnosticSafetyError("At least one diagnostic exchange is required.")
    if len(exchanges) > _MAX_ENVELOPES:
        raise DiagnosticSafetyError("Diagnostic bundles cannot contain more than 50 exchanges.")

    consent: dict[str, Any] = {
        "redactionAcknowledged": redaction_acknowledged,
        "shareWithSupport": share_with_support,
    }
    if granted_by is not None:
        consent["grantedBy"] = _safe_metadata(granted_by, "grantedBy", 256)
    bundle: dict[str, Any] = {
        "schemaVersion": "1.0",
        "contentClassification": content_classification,
        "consent": consent,
        "envelopes": [sanitize_exchange(exchange) for exchange in exchanges],
    }
    if bundle_id is not None:
        bundle["bundleId"] = _safe_metadata(bundle_id, "bundleId", 64)
    assert_diagnostic_bundle(bundle)
    return bundle


def sanitize_exchange(exchange: Mapping[str, Any]) -> dict[str, Any]:
    """Convert one raw in-memory exchange to a canonical sanitized envelope."""
    method = exchange.get("method")
    url = exchange.get("url")
    if not isinstance(method, str) or not method.strip():
        raise DiagnosticSafetyError("Diagnostic exchange requires a request method string.")
    if not isinstance(url, str) or not url.strip():
        raise DiagnosticSafetyError("Diagnostic exchange requires a request URL string.")

    envelope: dict[str, Any] = {
        "method": method.strip().upper()[:16],
        "normalizedPath": normalize_diagnostic_path(url),
    }
    _copy_optional_integer(exchange, envelope, "statusCode", minimum=100, maximum=599)
    _copy_optional_safe_string(exchange, envelope, "mediaType", maximum=256)
    _copy_optional_safe_string(exchange, envelope, "correlationId", maximum=200)
    _copy_optional_safe_string(exchange, envelope, "traceId", maximum=200)
    _copy_optional_safe_string(exchange, envelope, "capturedAt", maximum=40)
    for source_name, output_name in (
        ("requestHeaders", "requestHeaders"),
        ("responseHeaders", "responseHeaders"),
    ):
        if source_name in exchange:
            headers = sanitize_headers(exchange[source_name])
            if headers:
                envelope[output_name] = headers
    for source_name, output_name in (("requestBody", "requestBody"), ("responseBody", "responseBody")):
        if source_name in exchange:
            envelope[output_name] = sanitize_body(exchange[source_name])

    assert_diagnostic_bundle(
        {
            "schemaVersion": "1.0",
            "contentClassification": "unknown",
            "consent": {"redactionAcknowledged": True, "shareWithSupport": False},
            "envelopes": [envelope],
        }
    )
    return envelope


def sanitize_headers(value: object) -> list[dict[str, str]]:
    """Return only allowlisted, non-secret headers from a raw mapping."""
    if value is None:
        return []
    if not isinstance(value, Mapping):
        raise DiagnosticSafetyError("Diagnostic headers must be a JSON object.")
    sanitized: list[dict[str, str]] = []
    for raw_name, raw_value in value.items():
        if not isinstance(raw_name, str):
            continue
        canonical_name = _SAFE_HEADER_NAMES.get(raw_name.strip().lower())
        if canonical_name is None:
            continue
        header_value = _header_value(raw_value)
        if header_value is None or _SECRET_PATTERN.search(header_value):
            continue
        if "\r" in header_value or "\n" in header_value:
            continue
        sanitized.append({"name": canonical_name, "value": header_value[:2048]})
    return sorted(sanitized, key=lambda header: header["name"].lower())


def sanitize_body(value: object) -> dict[str, Any]:
    """Hash raw body bytes in memory and persist metadata only, never a preview."""
    raw = _body_bytes(value)
    size = len(raw)
    if size > _MAX_BODY_BYTES:
        raise DiagnosticSafetyError("Diagnostic body exceeds the canonical 25 MiB limit.")
    suppressed = size > 0
    return {
        "contentSha256": hashlib.sha256(raw).hexdigest(),
        "originalByteSize": size,
        "redactionApplied": suppressed,
        "truncated": suppressed,
    }


def normalize_diagnostic_path(raw_url: str) -> str:
    """Remove origin/userinfo and placeholder path parameters and query values."""
    candidate = raw_url.strip()
    parsed = urlsplit(candidate if "://" in candidate else f"https://diagnostic.invalid/{candidate.lstrip('/')}")
    decoded_path = unquote(parsed.path)
    segments: list[str] = []
    for raw_segment in decoded_path.split("/"):
        if not raw_segment:
            continue
        segment = unquote(raw_segment)
        if segment in {".", ".."} or "\x00" in segment or "\\" in segment:
            raise DiagnosticSafetyError("Diagnostic URL contains an unsafe path segment.")
        segments.append(segment if segment in _SAFE_PATH_SEGMENTS else "{value}")
    normalized = "/" + "/".join(segments)
    query_names = sorted(
        {
            name
            for name, _ in parse_qsl(parsed.query, keep_blank_values=True)
            if name in _SAFE_QUERY_NAMES and not _SECRET_PATTERN.search(name)
        }
    )
    if query_names:
        normalized += "?" + "&".join(f"{name}={{value}}" for name in query_names)
    if len(normalized) > _MAX_PATH_LENGTH:
        raise DiagnosticSafetyError("Normalized diagnostic path exceeds the canonical limit.")
    return normalized


def safe_probe_base_url(raw_url: str) -> str:
    """Validate an anonymous probe/replay origin and return it without credentials."""
    parsed = urlsplit(raw_url.strip())
    local_http = parsed.scheme == "http" and (parsed.hostname or "").lower() in {
        "127.0.0.1",
        "::1",
        "localhost",
    }
    if (parsed.scheme != "https" and not local_http) or parsed.username or parsed.password:
        raise DiagnosticSafetyError("Doctor base URL must be credential-free HTTPS or localhost HTTP.")
    if parsed.query or parsed.fragment or not parsed.hostname:
        raise DiagnosticSafetyError("Doctor base URL must not contain query, fragment, or missing host.")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def probe_capabilities(
    base_url: str,
    *,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Perform one bounded anonymous capability read and return raw in-memory input."""
    safe_base = safe_probe_base_url(base_url)
    target = f"{safe_base}/api/v1/services?limit=1"
    captured_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        with (
            httpx.Client(
                timeout=max(0.001, min(timeout, 30.0)),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client,
            client.stream(
                "GET",
                target,
                headers={"Accept": "application/json, application/problem+json"},
            ) as response,
        ):
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > _MAX_PROBE_BYTES:
                    raise DiagnosticSafetyError("Capability probe response exceeds 256 KiB.")
                chunks.append(chunk)
            raw_body = b"".join(chunks)
            return {
                "method": "GET",
                "url": target,
                "statusCode": response.status_code,
                "mediaType": response.headers.get("content-type"),
                "correlationId": response.headers.get("x-correlation-id") or response.headers.get("x-request-id"),
                "traceId": response.headers.get("traceparent"),
                "capturedAt": captured_at,
                "responseHeaders": dict(response.headers),
                "responseBody": raw_body,
            }
    except DiagnosticSafetyError:
        raise
    except (httpx.HTTPError, OSError):
        return {"method": "GET", "url": target, "capturedAt": captured_at}


def replay_diagnostic_bundle(
    bundle: object,
    base_url: str,
    *,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Replay one sanitized read envelope anonymously and return a new bundle."""
    assert_diagnostic_bundle(bundle)
    validated = cast(dict[str, Any], bundle)
    _assert_replay_artifact_safe(validated)
    envelopes = cast(list[dict[str, Any]], validated["envelopes"])
    envelope = envelopes[-1]
    method = cast(str, envelope["method"])
    normalized_path = cast(str, envelope["normalizedPath"])
    if method.upper() not in {"GET", "HEAD"}:
        raise DiagnosticSafetyError("Replay permits only one GET or HEAD request.")
    replay_path = _safe_replay_path(normalized_path)
    target = _join_replay_target(safe_probe_base_url(base_url), replay_path)
    captured_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        with (
            httpx.Client(
                timeout=max(0.001, min(timeout, 30.0)),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client,
            client.stream(
                method.upper(),
                target,
                headers={"Accept": "application/json, application/problem+json"},
            ) as response,
        ):
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > _MAX_PROBE_BYTES:
                    raise DiagnosticSafetyError("Replay response exceeds 256 KiB.")
                chunks.append(chunk)
            exchange = {
                "method": method.upper(),
                "url": target,
                "statusCode": response.status_code,
                "mediaType": response.headers.get("content-type"),
                "correlationId": response.headers.get("x-correlation-id") or response.headers.get("x-request-id"),
                "traceId": response.headers.get("traceparent"),
                "capturedAt": captured_at,
                "responseHeaders": dict(response.headers),
                "responseBody": b"".join(chunks),
            }
    except DiagnosticSafetyError:
        raise
    except (httpx.HTTPError, OSError) as exc:
        raise DiagnosticSafetyError("Replay request failed without producing an artifact.") from exc

    consent = cast(dict[str, Any], validated["consent"])
    return create_diagnostic_bundle(
        content_classification=cast(str, validated["contentClassification"]),
        redaction_acknowledged=bool(consent["redactionAcknowledged"]),
        share_with_support=bool(consent["shareWithSupport"]),
        exchanges=[exchange],
        granted_by=consent.get("grantedBy") if isinstance(consent.get("grantedBy"), str) else None,
    )


def _assert_replay_artifact_safe(bundle: Mapping[str, Any]) -> None:
    bundle_id = bundle.get("bundleId")
    if isinstance(bundle_id, str):
        _safe_metadata(bundle_id, "bundleId", 64)
    consent = bundle.get("consent")
    if isinstance(consent, dict) and isinstance(consent.get("grantedBy"), str):
        _safe_metadata(consent["grantedBy"], "grantedBy", 256)
    envelopes = cast(list[dict[str, Any]], bundle["envelopes"])
    for envelope in envelopes:
        if "requestBody" in envelope:
            raise DiagnosticSafetyError("Replay refuses artifacts containing request bodies.")
        for header_group in ("requestHeaders", "responseHeaders"):
            headers = envelope.get(header_group)
            if headers is None:
                continue
            for header in cast(list[dict[str, Any]], headers):
                name = header.get("name")
                value = header.get("value")
                if (
                    not isinstance(name, str)
                    or name.lower() not in _SAFE_HEADER_NAMES
                    or not isinstance(value, str)
                    or _SECRET_PATTERN.search(value)
                ):
                    raise DiagnosticSafetyError("Replay artifact contains unsafe headers.")
        for body_name in ("responseBody",):
            body = envelope.get(body_name)
            if isinstance(body, dict):
                _verify_body_metadata(body)


def _verify_body_metadata(body: Mapping[str, Any]) -> None:
    preview = body.get("preview")
    content_hash = body.get("contentSha256")
    redacted = body.get("redactionApplied")
    truncated = body.get("truncated")
    if isinstance(preview, str) and _SECRET_PATTERN.search(preview):
        raise DiagnosticSafetyError("Replay artifact contains credential-shaped body content.")
    if (
        isinstance(preview, str)
        and isinstance(content_hash, str)
        and redacted is False
        and truncated is False
        and hashlib.sha256(preview.encode()).hexdigest() != content_hash
    ):
        raise DiagnosticSafetyError("Replay artifact body hash does not match its unredacted preview.")


def _safe_replay_path(normalized_path: str) -> str:
    raw_path = normalized_path.split("?", 1)[0]
    decoded = unquote(unquote(raw_path))
    segments = [segment for segment in decoded.split("/") if segment]
    lowered_segments = {segment.lower() for segment in segments}
    if (
        not decoded.startswith("/")
        or "{" in decoded
        or "}" in decoded
        or "%" in normalized_path
        or "//" in decoded
        or "\\" in decoded
        or "\x00" in decoded
        or any(segment in {".", ".."} for segment in decoded.split("/"))
        or any(segment not in _SAFE_PATH_SEGMENTS for segment in segments)
        or lowered_segments.intersection({"subscribe", "subscriptions", "stream", "watch", "events"})
    ):
        raise DiagnosticSafetyError("Replay path is unsafe, parameterized, or subscription-shaped.")
    return decoded


def _join_replay_target(base_url: str, replay_path: str) -> str:
    parsed = urlsplit(base_url)
    prefix = parsed.path.rstrip("/")
    path = replay_path if prefix and replay_path.startswith(f"{prefix}/") else f"{prefix}{replay_path}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _validate_consent(value: object, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("$.consent: expected type 'object'")
        return
    _unexpected(value, _CONSENT_KEYS, "$.consent", errors)
    _required(value, ("redactionAcknowledged", "shareWithSupport"), "$.consent", errors)
    _boolean(value, "redactionAcknowledged", "$.consent", errors)
    _boolean(value, "shareWithSupport", "$.consent", errors)
    _string(value, "grantedBy", "$.consent", errors, maximum=256)


def _validate_envelope(value: object, index: int, errors: list[str]) -> None:
    path = f"$.envelopes[{index}]"
    if not isinstance(value, dict):
        errors.append(f"{path}: expected type 'object'")
        return
    _unexpected(value, _ENVELOPE_KEYS, path, errors)
    _required(value, ("method", "normalizedPath"), path, errors)
    _string(value, "method", path, errors, maximum=16)
    _string(value, "normalizedPath", path, errors, maximum=2048)
    _integer(value, "statusCode", path, errors, minimum=100, maximum=599)
    for name, maximum in (
        ("mediaType", 256),
        ("correlationId", 200),
        ("traceId", 200),
        ("capturedAt", 40),
    ):
        _string(value, name, path, errors, maximum=maximum)
    for name in ("requestHeaders", "responseHeaders"):
        _validate_headers(value, name, path, errors)
    for name in ("requestBody", "responseBody"):
        _validate_body(value, name, path, errors)


def _validate_headers(value: Mapping[str, object], name: str, parent: str, errors: list[str]) -> None:
    if name not in value:
        return
    headers = value[name]
    path = f"{parent}.{name}"
    if not isinstance(headers, list):
        errors.append(f"{path}: expected type 'array'")
        return
    if len(headers) > _MAX_HEADERS:
        errors.append(f"{path}: contains more than maximum 32 items")
    for index, header in enumerate(headers):
        header_path = f"{path}[{index}]"
        if not isinstance(header, dict):
            errors.append(f"{header_path}: expected type 'object'")
            continue
        _unexpected(header, frozenset({"name", "value"}), header_path, errors)
        _required(header, ("name", "value"), header_path, errors)
        _string(header, "name", header_path, errors, maximum=128)
        _string(header, "value", header_path, errors, maximum=2048)


def _validate_body(value: Mapping[str, object], name: str, parent: str, errors: list[str]) -> None:
    if name not in value:
        return
    body = value[name]
    path = f"{parent}.{name}"
    if not isinstance(body, dict):
        errors.append(f"{path}: expected type 'object'")
        return
    _unexpected(body, _BODY_KEYS, path, errors)
    _required(body, ("originalByteSize", "redactionApplied", "truncated"), path, errors)
    _string(body, "preview", path, errors, maximum=8192)
    _string(body, "contentSha256", path, errors, maximum=64)
    _integer(body, "originalByteSize", path, errors, minimum=0, maximum=_MAX_BODY_BYTES)
    _boolean(body, "redactionApplied", path, errors)
    _boolean(body, "truncated", path, errors)


def _required(value: Mapping[str, object], names: Sequence[str], path: str, errors: list[str]) -> None:
    for name in names:
        if name not in value:
            errors.append(f"{path}: missing required property '{name}'")


def _unexpected(value: Mapping[str, object], allowed: frozenset[str], path: str, errors: list[str]) -> None:
    for name in value:
        if name not in allowed:
            errors.append(f"{path}: unexpected property '{name}'")


def _string(
    value: Mapping[str, object],
    name: str,
    parent: str,
    errors: list[str],
    *,
    maximum: int,
    constant: str | None = None,
) -> str | None:
    if name not in value:
        return None
    item = value[name]
    path = f"{parent}.{name}"
    if not isinstance(item, str):
        errors.append(f"{path}: expected type 'string'")
        return None
    if len(item) > maximum:
        errors.append(f"{path}: exceeds maximum length {maximum}")
    if constant is not None and item != constant:
        errors.append(f"{path}: value must equal the constant '{constant}'")
    return item


def _integer(
    value: Mapping[str, object],
    name: str,
    parent: str,
    errors: list[str],
    *,
    minimum: int,
    maximum: int,
) -> None:
    if name not in value:
        return
    item = value[name]
    path = f"{parent}.{name}"
    if not isinstance(item, int) or isinstance(item, bool):
        errors.append(f"{path}: expected type 'integer'")
        return
    if item < minimum:
        errors.append(f"{path}: is below minimum {minimum}")
    if item > maximum:
        errors.append(f"{path}: exceeds maximum {maximum}")


def _boolean(value: Mapping[str, object], name: str, parent: str, errors: list[str]) -> None:
    if name in value and not isinstance(value[name], bool):
        errors.append(f"{parent}.{name}: expected type 'boolean'")


def _copy_optional_integer(
    source: Mapping[str, Any],
    target: dict[str, Any],
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> None:
    if name not in source or source[name] is None:
        return
    value = source[name]
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum or value > maximum:
        raise DiagnosticSafetyError(f"Diagnostic {name} is outside the canonical range.")
    target[name] = value


def _copy_optional_safe_string(source: Mapping[str, Any], target: dict[str, Any], name: str, *, maximum: int) -> None:
    if name not in source or source[name] is None:
        return
    value = source[name]
    if not isinstance(value, str):
        raise DiagnosticSafetyError(f"Diagnostic {name} must be a string when present.")
    if value and not _SECRET_PATTERN.search(value) and "\r" not in value and "\n" not in value:
        target[name] = value[:maximum]


def _safe_metadata(value: str, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or _SECRET_PATTERN.search(normalized):
        raise DiagnosticSafetyError(f"Diagnostic {field} is empty, over-budget, or credential-shaped.")
    return normalized


def _header_value(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        strings = [item for item in value if isinstance(item, str)]
        if len(strings) == len(value):
            return ", ".join(strings)
    return None


def _body_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode()
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    except (TypeError, ValueError) as exc:
        raise DiagnosticSafetyError("Diagnostic body is not JSON-serializable.") from exc


__all__ = [
    "DIAGNOSTIC_SCHEMA_BYTES",
    "DIAGNOSTIC_SCHEMA_SHA256",
    "DIAGNOSTIC_SCHEMA_URL",
    "DiagnosticError",
    "DiagnosticSafetyError",
    "DiagnosticValidationError",
    "assert_diagnostic_bundle",
    "create_diagnostic_bundle",
    "normalize_diagnostic_path",
    "probe_capabilities",
    "replay_diagnostic_bundle",
    "safe_probe_base_url",
    "sanitize_body",
    "sanitize_exchange",
    "sanitize_headers",
    "validate_diagnostic_bundle",
]
