"""JSONL audit logger for shim invocations.

Every call to a supported shim function produces one JSON line. The shape is::

    {
      "timestamp": "2026-05-22T17:42:11Z",
      "function": "analysis.Buffer",
      "args": ["...", "...", ...],           # redacted positional args
      "kwargs": {"distance": "..."},          # redacted kwargs
      "result_shape": {...},                  # shape-only summary, no values
      "latency_ms": 12.4,
      "status": "ok" | "error",
      "error_kind": "..."                     # only when status == "error"
    }

The file path is ``${HONUA_GP_AUDIT_DIR:-./.honua-gp/audit}/audit-YYYYMMDD.jsonl``
in UTC, written append-only with one writer at a time per process. Redaction
delegates to :mod:`honua_admin._arcpy_scanner` so we don't reinvent path /
secret heuristics.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:  # honua_admin owns the canonical redaction heuristics.
    from honua_admin._arcpy_scanner import (
        _PATH_EXTENSIONS,
        _is_sensitive_context,
        _looks_like_bare_secret,
        _looks_like_path,
        _looks_like_url,
        _redact_path,
        _redact_url,
    )
except Exception:  # pragma: no cover -- honua-admin is a hard dependency at runtime
    _PATH_EXTENSIONS = ()  # type: ignore[assignment]

    def _is_sensitive_context(context: str | None) -> bool:  # type: ignore[misc]
        return bool(context and any(token in context.lower() for token in ("password", "secret", "token", "key")))

    def _looks_like_bare_secret(value: str) -> bool:  # type: ignore[misc]
        lowered = value.lower()
        return any(token in lowered for token in ("password", "secret", "token"))

    def _looks_like_path(value: str) -> bool:  # type: ignore[misc]
        return value.startswith("/") or value.startswith("\\") or ":\\" in value or ":/" in value

    def _looks_like_url(value: str) -> bool:  # type: ignore[misc]
        return any(value.lower().startswith(scheme) for scheme in ("http://", "https://", "s3://", "gs://"))

    def _redact_path(value: str) -> str:  # type: ignore[misc]
        return "<local-path>/" + Path(value.replace("\\", "/")).name

    def _redact_url(value: str) -> str:  # type: ignore[misc]
        return value


_AUDIT_LOCK = threading.Lock()
_AUDIT_DIR_ENV = "HONUA_GP_AUDIT_DIR"
_AUDIT_DEFAULT_DIR = Path(".honua-gp") / "audit"


def _audit_dir() -> Path:
    override = os.environ.get(_AUDIT_DIR_ENV)
    if override:
        return Path(override)
    return _AUDIT_DEFAULT_DIR


def _audit_path(now: datetime | None = None) -> Path:
    moment = now or datetime.now(timezone.utc)
    return _audit_dir() / f"audit-{moment.strftime('%Y%m%d')}.jsonl"


def _utc_timestamp(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _redact_value(value: Any, *, context: str | None = None) -> Any:
    if isinstance(value, str):
        if _is_sensitive_context(context):
            return "<redacted>"
        if _looks_like_url(value):
            return _redact_url(value)
        if _looks_like_bare_secret(value):
            return "<redacted>"
        if _looks_like_path(value):
            return _redact_path(value)
        return value
    if isinstance(value, Mapping):
        return {str(key): _redact_value(item, context=str(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, context=context) for item in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    # Fall back to a shape-only representation: type tag rather than __repr__.
    return {"type": type(value).__name__}


def _shape_of(value: Any) -> Any:
    """Return a shape-only summary suitable for the result_shape field."""

    if value is None:
        return None
    if isinstance(value, Mapping):
        return {"type": "object", "keys": sorted(str(key) for key in value)}
    if isinstance(value, (list, tuple)):
        return {"type": "array", "length": len(value)}
    if isinstance(value, str):
        return {"type": "string", "length": len(value)}
    if isinstance(value, (int, float, bool)):
        return {"type": type(value).__name__}
    return {"type": type(value).__name__}


class AuditWriter:
    """Append-only JSONL writer with one open handle per UTC day."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir_override = base_dir
        self._current_path: Path | None = None
        self._current_handle: Any = None
        self._lock = threading.Lock()

    def _resolve_path(self, now: datetime | None = None) -> Path:
        if self._base_dir_override is not None:
            moment = now or datetime.now(timezone.utc)
            return self._base_dir_override / f"audit-{moment.strftime('%Y%m%d')}.jsonl"
        return _audit_path(now)

    def write(self, record: Mapping[str, Any], *, now: datetime | None = None) -> None:
        path = self._resolve_path(now)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self._lock:
            if self._current_path != path or self._current_handle is None:
                self.close()
                path.parent.mkdir(parents=True, exist_ok=True)
                self._current_handle = path.open("a", encoding="utf-8")
                self._current_path = path
            self._current_handle.write(line + "\n")
            self._current_handle.flush()

    def close(self) -> None:
        if self._current_handle is not None:
            try:
                self._current_handle.close()
            finally:
                self._current_handle = None
                self._current_path = None


_DEFAULT_WRITER = AuditWriter()


def set_audit_writer(writer: AuditWriter) -> AuditWriter:
    """Replace the module-default writer. Returns the previous instance."""

    global _DEFAULT_WRITER
    previous = _DEFAULT_WRITER
    _DEFAULT_WRITER = writer
    return previous


def default_writer() -> AuditWriter:
    return _DEFAULT_WRITER


@contextmanager
def record_call(
    function: str,
    *,
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    writer: AuditWriter | None = None,
) -> Iterator[dict[str, Any]]:
    """Audit a shim invocation.

    Yields a mutable dictionary so the dispatcher can attach ``result_shape``
    once the underlying call returns. The line is always written on exit --
    failures land with ``status="error"`` plus ``error_kind``.
    """

    target = writer or _DEFAULT_WRITER
    redacted_args = [_redact_value(value, context=f"arg{index}") for index, value in enumerate(args)]
    redacted_kwargs = {
        str(key): _redact_value(value, context=str(key))
        for key, value in (kwargs or {}).items()
    }
    record: dict[str, Any] = {
        "function": function,
        "args": redacted_args,
        "kwargs": redacted_kwargs,
        "status": "ok",
    }
    start = time.perf_counter()
    try:
        yield record
    except BaseException as exc:
        record["status"] = "error"
        kind = getattr(exc, "error_kind", None) or exc.__class__.__name__
        record["error_kind"] = str(kind)
        raise
    finally:
        record["latency_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
        record["timestamp"] = _utc_timestamp()
        record.setdefault("result_shape", None)
        try:
            target.write(record)
        except Exception:
            # Audit is observability; never let a logging failure mask the
            # real call's outcome or success.
            pass


__all__ = [
    "AuditWriter",
    "default_writer",
    "record_call",
    "set_audit_writer",
    "_redact_value",
    "_shape_of",
]
