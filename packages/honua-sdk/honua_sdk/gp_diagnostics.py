"""Read ``honua.job-diagnostics/v1`` for GP inspect and logs.

The document is the server projection from
``GET /api/v1/admin/jobs/{jobId}/diagnostics``. This module types and renders
that document. It does not assemble a second diagnostics model. A local run
receipt is projected into the same schema; fields the receipt does not hold
are listed under ``evidence`` and are not invented.

Remote calls use the bound client, so they send the caller's current
credentials and no separate devkit or server checkout. Command output redacts
secrets and never writes credentials to logs.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import sys
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any, cast

from ._client_protocol import SupportsAsyncRequest, SupportsSyncRequest
from ._http import _encode_path_segment
from .errors import HonuaAuthError, HonuaError, HonuaHttpError, HonuaTransportError

SCHEMA_ID = "honua.job-diagnostics/v1"
DEFAULT_EVENT_LIMIT = 50
MAX_EVENT_LIMIT = 500

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_UNAUTHORIZED = 3
EXIT_MISSING = 4
EXIT_EXPIRED = 5
EXIT_INTERRUPTED = 6

_ENV_BASE_URL = "HONUA_BASE_URL"
_ENV_API_KEY = "HONUA_API_KEY"
_REDACTED = "[REDACTED]"
_ASSIGNMENT = re.compile(
    r"(?i)\b((?:api[-_]?key|password|passwd|secret|token|authorization)\b\s*[=:]\s*)"
    r"(?!(?:bearer|basic)\b)(\S+)"
)
_BEARER = re.compile(r"(?i)\b((?:bearer|basic)\s+)(\S+)")
_USERINFO = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@]+:[^\s/@]+@[^\s]+")
JsonObject = dict[str, Any]
ClientFactory = Callable[[argparse.Namespace], Any]


class GpDiagnosticsContractError(HonuaError):
    """The payload is not a ``honua.job-diagnostics/v1`` document."""


class GpDiagnosticsUsageError(HonuaError):
    """The inspect or logs command was invoked incorrectly."""


class GpDiagnosticsStreamInterrupted(HonuaError):
    """A bounded event stream stopped before a truthful end."""


def redact_secrets(text: str, secrets: Sequence[str] = ()) -> str:
    """Replace credentials and secret assignments with ``[REDACTED]``."""
    redacted = _redact_userinfo(_redact_assignments(_redact_tokens(text)))
    for secret in secrets:
        if secret and secret != _REDACTED:
            redacted = redacted.replace(secret, _REDACTED)
    return redacted


def redact_document(document: Mapping[str, Any], secrets: Sequence[str] = ()) -> JsonObject:
    """Return a copy of a projection with secret string values redacted."""
    walked = _redact_value(document, secrets)
    if not isinstance(walked, dict):
        raise GpDiagnosticsContractError("job diagnostics document must be an object")
    return walked


def parse_job_diagnostics(document: Mapping[str, Any]) -> JobDiagnostics:
    """Validate and wrap one projection page without dropping its markers."""
    if not isinstance(document, Mapping):
        raise GpDiagnosticsContractError("job diagnostics document must be an object")
    schema = document.get("schema")
    if schema != SCHEMA_ID:
        raise GpDiagnosticsContractError(f"job diagnostics schema must be {SCHEMA_ID}")
    if not isinstance(document.get("jobId"), str) or not document.get("jobId"):
        raise GpDiagnosticsContractError("job diagnostics jobId is required")
    _require_mapping(document.get("lifecycle"), "lifecycle")
    _require_mapping(document.get("attempt"), "attempt")
    _require_mapping(document.get("events"), "events")
    _require_mapping(document.get("evidence"), "evidence")
    _require_mapping(document.get("artifacts"), "artifacts")
    events = document["events"]
    evidence = document["evidence"]
    _require_bool(events.get("truncated"), "events.truncated")
    _require_strings(evidence.get("missing"), "evidence.missing")
    _require_strings(evidence.get("truncated"), "evidence.truncated")
    _require_strings(evidence.get("notes"), "evidence.notes")
    failure = document.get("failure")
    if failure is not None:
        _require_mapping(failure, "failure")
    return JobDiagnostics(dict(document))


def format_job_diagnostics(diagnostics: JobDiagnostics) -> str:
    """Render one projection page, leading with phase, attempt, and next action."""
    lines = [
        _lead_line(diagnostics),
        f"next: {_next_action(diagnostics)}",
        "",
        f"job: {diagnostics.job_id}",
        f"status: {diagnostics.lifecycle.status}",
        f"lifecycle phase: {diagnostics.lifecycle.phase}",
        f"worker: {diagnostics.worker.liveness} ({diagnostics.worker.liveness_reason})",
        f"release: {diagnostics.release.state}",
        (
            "artifacts: "
            f"{diagnostics.artifacts.state} "
            f"(expired {diagnostics.artifacts.expired_count}, "
            f"available {diagnostics.artifacts.available_count}, "
            f"unavailable {diagnostics.artifacts.unavailable_count})"
        ),
        _events_line(diagnostics),
    ]
    failure = diagnostics.failure
    if failure is not None:
        lines.append(f"failure: {failure.classification}: {failure.message}")
    lines.extend(_marker_block("missing evidence", diagnostics.evidence.missing))
    lines.extend(_marker_block("truncated", diagnostics.evidence.truncated))
    lines.extend(_marker_block("notes", diagnostics.evidence.notes))
    return "\n".join(lines).rstrip() + "\n"


def format_event_line(entry: LogEntryView) -> str:
    """Render one bounded log event."""
    phase = f" {entry.phase}" if entry.phase else ""
    return f"{entry.timestamp} {entry.level}{phase} {entry.message}"


def log_disclosure_lines(pages: Sequence[JobDiagnostics]) -> tuple[str, ...]:
    """Disclosure lines for truncation, missing evidence, and paging cursors."""
    lines: list[str] = []
    missing: list[str] = []
    for page in pages:
        for item in page.evidence.missing:
            _append_unique(missing, item)
        for item in page.evidence.truncated:
            _append_unique(lines, f"truncated: {item}")
        bits: list[str] = []
        if page.events.first_cursor:
            bits.append(f"firstCursor={page.events.first_cursor}")
        if page.events.next_cursor:
            bits.append(f"nextCursor={page.events.next_cursor}")
        if page.events.truncated and bits:
            _append_unique(lines, "truncated: " + ", ".join(bits))
    lines.extend(_marker_block("missing evidence", missing))
    return tuple(lines)


def load_local_receipt(
    path: str | Path,
    *,
    events: int = DEFAULT_EVENT_LIMIT,
    event_cursor: str | None = None,
) -> JobDiagnostics:
    """Project a local receipt directory into one diagnostics page.

    Reads only the receipt directory. It does not open a socket or read
    credentials.
    """
    return parse_job_diagnostics(_local_document(Path(path), events=events, event_cursor=event_cursor))


def iter_local_event_pages(
    path: str | Path,
    *,
    events: int = DEFAULT_EVENT_LIMIT,
    event_cursor: str | None = "start",
) -> Iterator[JobDiagnostics]:
    """Yield bounded local event pages without dropping cursors or evidence."""
    directory = _receipt_directory(Path(path))
    cursor = event_cursor
    seen: set[str] = set()
    while True:
        cursor = _remember_cursor(cursor, seen)
        page = parse_job_diagnostics(_local_document(directory, events=events, event_cursor=cursor))
        yield page
        cursor = page.events.next_cursor
        if cursor is None:
            return


def local_receipt_directory(target: str) -> Path | None:
    """Return a receipt directory, or None when *target* is a remote job id."""
    path = Path(target).expanduser()
    looks_like_path = target.startswith(("/", ".", "~")) or "/" in target or "\\" in target
    if looks_like_path:
        if not path.exists():
            raise GpDiagnosticsUsageError(f"local receipt path does not exist: {target}")
        return _receipt_directory(path)
    if path.is_dir() or (path.is_file() and path.name == "receipt.json"):
        return _receipt_directory(path)
    return None


def diagnostics_failure(
    exc: BaseException,
    *,
    stream_started: bool,
    secrets: Sequence[str] = (),
) -> tuple[int, str]:
    """Map a failure to a distinct exit code and a redacted stderr line."""
    if isinstance(exc, GpDiagnosticsUsageError | ValueError):
        return EXIT_USAGE, _error_line(redact_secrets(str(exc), secrets))
    if isinstance(exc, HonuaAuthError):
        return EXIT_UNAUTHORIZED, _error_line(
            f"unauthorized (HTTP {exc.status_code}): {redact_secrets(exc.message, secrets)}"
        )
    if isinstance(exc, HonuaHttpError):
        return _http_failure(exc, secrets)
    if isinstance(exc, GpDiagnosticsStreamInterrupted) or (
        stream_started and isinstance(exc, HonuaTransportError | HonuaError)
    ):
        return EXIT_INTERRUPTED, _error_line(f"log stream interrupted: {redact_secrets(str(exc), secrets)}")
    if isinstance(exc, HonuaError):
        return EXIT_ERROR, _error_line(redact_secrets(str(exc), secrets))
    return EXIT_ERROR, _error_line("job diagnostics failed")


class LogEntryView:
    """One ``events.items`` record from the projection."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = raw

    @property
    def timestamp(self) -> str:
        value = self._raw.get("timestamp")
        return value if isinstance(value, str) else ""

    @property
    def level(self) -> str:
        value = self._raw.get("level")
        return value if isinstance(value, str) else ""

    @property
    def message(self) -> str:
        value = self._raw.get("message")
        return value if isinstance(value, str) else ""

    @property
    def phase(self) -> str | None:
        value = self._raw.get("phase")
        return value if isinstance(value, str) and value else None


class FailureView:
    """The projection's ``failure`` object, when the job recorded one."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = raw

    @property
    def message(self) -> str:
        value = self._raw.get("message")
        return value if isinstance(value, str) else ""

    @property
    def classification(self) -> str:
        value = self._raw.get("classification")
        return value if isinstance(value, str) else ""

    @property
    def phase(self) -> str | None:
        value = self._raw.get("phase")
        return value if isinstance(value, str) and value else None

    @property
    def step_ordinal(self) -> int | None:
        return _optional_int(self._raw.get("stepOrdinal"))

    @property
    def recovery(self) -> str:
        value = self._raw.get("recovery")
        return value if isinstance(value, str) else ""


class RetryView:
    """``attempt.retry`` from the projection."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = raw

    @property
    def allowed(self) -> bool:
        value = self._raw.get("allowed")
        return value if isinstance(value, bool) else False

    @property
    def disabled_reason(self) -> str | None:
        value = self._raw.get("disabledReason")
        return value if isinstance(value, str) and value else None

    @property
    def would_repeat(self) -> str:
        value = self._raw.get("wouldRepeat")
        return value if isinstance(value, str) else ""


class AttemptView:
    """``attempt`` from the projection."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = raw

    @property
    def number(self) -> int:
        value = _optional_int(self._raw.get("number"))
        return value if value is not None else 0

    @property
    def max_attempts(self) -> int | None:
        return _optional_int(self._raw.get("maxAttempts"))

    @property
    def retry(self) -> RetryView:
        raw = self._raw.get("retry")
        return RetryView(raw if isinstance(raw, Mapping) else {})


class EventsView:
    """``events`` from one bounded page, including cursors and truncation."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = raw

    @property
    def state(self) -> str:
        value = self._raw.get("state")
        return value if isinstance(value, str) else ""

    @property
    def items(self) -> tuple[LogEntryView, ...]:
        raw_items = self._raw.get("items")
        if not isinstance(raw_items, list):
            return ()
        return tuple(LogEntryView(item) for item in raw_items if isinstance(item, Mapping))

    @property
    def total_count(self) -> int:
        value = _optional_int(self._raw.get("totalCount"))
        return value if value is not None else len(self.items)

    @property
    def limit(self) -> int:
        value = _optional_int(self._raw.get("limit"))
        return value if value is not None else len(self.items)

    @property
    def truncated(self) -> bool:
        value = self._raw.get("truncated")
        return value if isinstance(value, bool) else False

    @property
    def first_cursor(self) -> str | None:
        return _optional_cursor(self._raw.get("firstCursor"))

    @property
    def next_cursor(self) -> str | None:
        return _optional_cursor(self._raw.get("nextCursor"))

    @property
    def mode(self) -> str:
        value = self._raw.get("mode")
        return value if isinstance(value, str) else ""


class EvidenceView:
    """``evidence.missing``, ``evidence.truncated``, and ``evidence.notes``."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = raw

    @property
    def missing(self) -> tuple[str, ...]:
        return _string_tuple(self._raw.get("missing"))

    @property
    def truncated(self) -> tuple[str, ...]:
        return _string_tuple(self._raw.get("truncated"))

    @property
    def notes(self) -> tuple[str, ...]:
        return _string_tuple(self._raw.get("notes"))


class ArtifactsView:
    """Artifact completeness counts from the projection."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = raw

    @property
    def state(self) -> str:
        value = self._raw.get("state")
        return value if isinstance(value, str) else ""

    @property
    def expired_count(self) -> int:
        return _required_count(self._raw.get("expiredCount"))

    @property
    def available_count(self) -> int:
        return _required_count(self._raw.get("availableCount"))

    @property
    def unavailable_count(self) -> int:
        return _required_count(self._raw.get("unavailableCount"))


class LifecycleView:
    """``lifecycle`` phase and status."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = raw

    @property
    def status(self) -> str:
        value = self._raw.get("status")
        return value if isinstance(value, str) else ""

    @property
    def phase(self) -> str:
        value = self._raw.get("phase")
        return value if isinstance(value, str) else ""


class ReleaseView:
    """``release.state`` and the fields the projection says are missing."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = raw

    @property
    def state(self) -> str:
        value = self._raw.get("state")
        return value if isinstance(value, str) else ""


class WorkerView:
    """Worker liveness from the projection."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = raw

    @property
    def liveness(self) -> str:
        value = self._raw.get("liveness")
        return value if isinstance(value, str) else ""

    @property
    def liveness_reason(self) -> str:
        value = self._raw.get("livenessReason")
        return value if isinstance(value, str) else ""


class JobDiagnostics:
    """Typed view of one ``honua.job-diagnostics/v1`` page.

    ``document`` is the projection itself. Rendering and paging read cursors,
    truncation, and missing-evidence markers from that object; they are not
    copied into a second model that can drop them.
    """

    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document: JsonObject = dict(document)

    @property
    def schema(self) -> str:
        value = self.document.get("schema")
        return value if isinstance(value, str) else ""

    @property
    def job_id(self) -> str:
        value = self.document.get("jobId")
        return value if isinstance(value, str) else ""

    @property
    def failure(self) -> FailureView | None:
        raw = self.document.get("failure")
        if not isinstance(raw, Mapping):
            return None
        return FailureView(raw)

    @property
    def attempt(self) -> AttemptView:
        return AttemptView(_section(self.document, "attempt"))

    @property
    def events(self) -> EventsView:
        return EventsView(_section(self.document, "events"))

    @property
    def evidence(self) -> EvidenceView:
        return EvidenceView(_section(self.document, "evidence"))

    @property
    def artifacts(self) -> ArtifactsView:
        return ArtifactsView(_section(self.document, "artifacts"))

    @property
    def lifecycle(self) -> LifecycleView:
        return LifecycleView(_section(self.document, "lifecycle"))

    @property
    def release(self) -> ReleaseView:
        return ReleaseView(_section(self.document, "release"))

    @property
    def worker(self) -> WorkerView:
        return WorkerView(_section(self.document, "worker"))


class GpDiagnostics:
    """Synchronous reader for the canonical job diagnostics projection."""

    def __init__(self, client: SupportsSyncRequest) -> None:
        self._client = client

    def diagnostics(
        self,
        job_id: str,
        *,
        events: int = DEFAULT_EVENT_LIMIT,
        event_cursor: str | None = None,
    ) -> JobDiagnostics:
        """Return one bounded diagnostics page for ``job_id``.

        Omit ``event_cursor`` for the recent tail. Pass ``events.first_cursor``
        (``start``) or ``events.next_cursor`` to read another bounded page.
        The returned page keeps cursors, truncation, and evidence markers.
        """
        document = self._client._request_json(
            "GET",
            _diagnostics_path(job_id),
            params=_diagnostics_params(events, event_cursor),
        )
        return parse_job_diagnostics(document)

    def iter_event_pages(
        self,
        job_id: str,
        *,
        events: int = DEFAULT_EVENT_LIMIT,
        event_cursor: str | None = "start",
    ) -> Iterator[JobDiagnostics]:
        """Yield bounded event pages in append order until ``nextCursor`` ends."""
        cursor = event_cursor
        seen: set[str] = set()
        while True:
            cursor = _remember_cursor(cursor, seen)
            page = self.diagnostics(job_id, events=events, event_cursor=cursor)
            yield page
            cursor = page.events.next_cursor
            if cursor is None:
                return


class AsyncGpDiagnostics:
    """Asynchronous reader for the canonical job diagnostics projection."""

    def __init__(self, client: SupportsAsyncRequest) -> None:
        self._client = client

    async def diagnostics(
        self,
        job_id: str,
        *,
        events: int = DEFAULT_EVENT_LIMIT,
        event_cursor: str | None = None,
    ) -> JobDiagnostics:
        """Return one bounded diagnostics page for ``job_id``."""
        document = await self._client._request_json(
            "GET",
            _diagnostics_path(job_id),
            params=_diagnostics_params(events, event_cursor),
        )
        return parse_job_diagnostics(document)

    async def iter_event_pages(
        self,
        job_id: str,
        *,
        events: int = DEFAULT_EVENT_LIMIT,
        event_cursor: str | None = "start",
    ) -> AsyncIterator[JobDiagnostics]:
        """Yield bounded event pages in append order until ``nextCursor`` ends."""
        cursor = event_cursor
        seen: set[str] = set()
        while True:
            cursor = _remember_cursor(cursor, seen)
            page = await self.diagnostics(job_id, events=events, event_cursor=cursor)
            yield page
            cursor = page.events.next_cursor
            if cursor is None:
                return


def run_gp_diagnostics_command(
    argv: Sequence[str],
    *,
    client_factory: ClientFactory,
    stdout: Any | None = None,
    stderr: Any | None = None,
) -> int:
    """Run ``honua gp inspect`` or ``honua gp logs`` without the devkit."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    parsed = _parse_cli(argv, err)
    if isinstance(parsed, int):
        return parsed
    secrets = _cli_secrets(parsed)
    try:
        local = local_receipt_directory(parsed.job)
        if parsed.action == "inspect":
            page = _inspect_page(parsed, local, client_factory)
            _write_inspect(page, as_json=parsed.json, secrets=secrets, stdout=out)
            return EXIT_OK
        return _stream_logs(parsed, local, client_factory, (out, err), secrets)
    except Exception as exc:
        code, line = diagnostics_failure(exc, stream_started=False, secrets=secrets)
        err.write(line)
        return code


def _inspect_page(
    args: argparse.Namespace,
    local: Path | None,
    client_factory: ClientFactory,
) -> JobDiagnostics:
    if local is not None:
        return load_local_receipt(local, events=args.events, event_cursor=args.event_cursor)
    _require_base_url(args)
    with client_factory(args) as client:
        page = client.gp.diagnostics(args.job, events=args.events, event_cursor=args.event_cursor)
        return cast(JobDiagnostics, page)


def _stream_logs(
    args: argparse.Namespace,
    local: Path | None,
    client_factory: ClientFactory,
    streams: tuple[Any, Any],
    secrets: Sequence[str],
) -> int:
    stdout, stderr = streams
    pages: list[JobDiagnostics] = []
    try:
        for page in _log_pages(args, local, client_factory):
            pages.append(page)
            if args.json:
                _write_log_page(page, secrets, stdout)
            else:
                for entry in page.events.items:
                    stdout.write(redact_secrets(format_event_line(entry), secrets) + "\n")
    except Exception as exc:
        code, line = diagnostics_failure(exc, stream_started=bool(pages), secrets=secrets)
        stderr.write(line)
        return code
    if not args.json:
        for line in log_disclosure_lines(pages):
            stdout.write(redact_secrets(line, secrets) + "\n")
    return EXIT_OK


def _log_pages(
    args: argparse.Namespace,
    local: Path | None,
    client_factory: ClientFactory,
) -> Iterator[JobDiagnostics]:
    cursor = "start" if args.event_cursor is None else args.event_cursor
    if local is not None:
        yield from iter_local_event_pages(local, events=args.events, event_cursor=cursor)
        return
    _require_base_url(args)
    with client_factory(args) as client:
        yield from client.gp.iter_event_pages(args.job, events=args.events, event_cursor=cursor)


def _write_inspect(page: JobDiagnostics, *, as_json: bool, secrets: Sequence[str], stdout: Any) -> None:
    if as_json:
        _write_json(redact_document(page.document, secrets), stdout)
        return
    stdout.write(redact_secrets(format_job_diagnostics(page), secrets))


def _write_log_page(page: JobDiagnostics, secrets: Sequence[str], stdout: Any) -> None:
    payload = {
        "jobId": page.job_id,
        "events": page.document.get("events"),
        "evidence": page.document.get("evidence"),
    }
    stdout.write(json.dumps(redact_document(payload, secrets), separators=(",", ":")) + "\n")


def _write_json(document: Mapping[str, Any], stdout: Any) -> None:
    json.dump(document, stdout, indent=2)
    stdout.write("\n")


def _parse_cli(argv: Sequence[str], stderr: Any) -> argparse.Namespace | int:
    parser = argparse.ArgumentParser(prog="honua gp")
    parser.add_argument("action", choices=("inspect", "logs"))
    parser.add_argument("job", help="Remote job id, or a local receipt directory.")
    parser.add_argument("--json", action="store_true", help="Print the projection or event pages as JSON.")
    parser.add_argument("--events", type=int, default=DEFAULT_EVENT_LIMIT, help="Bounded events per page (1-500).")
    parser.add_argument("--event-cursor", default=None, help="Projection eventCursor. Logs default to start.")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        code = exc.code
        return EXIT_OK if code in (None, 0) else EXIT_USAGE
    try:
        _validate_events(args.events)
    except ValueError as exc:
        stderr.write(_error_line(str(exc)))
        return EXIT_USAGE
    return args


def _cli_secrets(args: argparse.Namespace) -> tuple[str, ...]:
    values = [args.api_key, os.environ.get(_ENV_API_KEY)]
    return tuple(value for value in values if isinstance(value, str) and value)


def _require_base_url(args: argparse.Namespace) -> None:
    if args.base_url or os.environ.get(_ENV_BASE_URL):
        return
    raise GpDiagnosticsUsageError(
        f"a base URL is required (pass --base-url or set {_ENV_BASE_URL})",
    )


def _diagnostics_path(job_id: str) -> str:
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id is required")
    return f"/api/v1/admin/jobs/{_encode_path_segment(job_id)}/diagnostics"


def _diagnostics_params(events: int, event_cursor: str | None) -> JsonObject:
    params: JsonObject = {"events": _validate_events(events)}
    if event_cursor is not None:
        if not isinstance(event_cursor, str) or not event_cursor:
            raise ValueError("event_cursor must be a non-empty string")
        params["eventCursor"] = event_cursor
    return params


def _validate_events(events: int) -> int:
    if isinstance(events, bool) or not isinstance(events, int) or events < 1 or events > MAX_EVENT_LIMIT:
        raise ValueError(f"events must be an integer between 1 and {MAX_EVENT_LIMIT}")
    return events


def _remember_cursor(cursor: str | None, seen: set[str]) -> str | None:
    if cursor is None:
        return None
    if cursor in seen:
        raise GpDiagnosticsStreamInterrupted("event stream repeated a cursor instead of ending")
    seen.add(cursor)
    return cursor


def _http_failure(exc: HonuaHttpError, secrets: Sequence[str]) -> tuple[int, str]:
    detail = redact_secrets(exc.message, secrets)
    status = exc.status_code
    if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        return EXIT_UNAUTHORIZED, _error_line(f"unauthorized (HTTP {status}): {detail}")
    if status == HTTPStatus.NOT_FOUND:
        return EXIT_MISSING, _error_line(f"job not found (HTTP {status}): {detail}")
    if status == HTTPStatus.GONE or "expired" in detail.lower():
        return EXIT_EXPIRED, _error_line(f"expired (HTTP {status}): {detail}")
    return EXIT_ERROR, _error_line(f"HTTP {status}: {detail}")


def _error_line(message: str) -> str:
    text = message if message.startswith("error:") else f"error: {message}"
    return text if text.endswith("\n") else text + "\n"


def _lead_line(diagnostics: JobDiagnostics) -> str:
    failure = diagnostics.failure
    phase = failure.phase if failure is not None and failure.phase else diagnostics.lifecycle.phase
    prefix = "failing phase" if failure is not None else "phase"
    maximum = diagnostics.attempt.max_attempts
    attempt = f"attempt {diagnostics.attempt.number}"
    if maximum is not None:
        attempt = f"{attempt} of {maximum}"
    return f"{prefix} {phase}, {attempt}"


def _next_action(diagnostics: JobDiagnostics) -> str:
    failure = diagnostics.failure
    retry = diagnostics.attempt.retry
    if failure is not None and failure.recovery:
        return failure.recovery
    if retry.allowed and retry.would_repeat:
        return retry.would_repeat
    if retry.disabled_reason:
        return retry.disabled_reason
    if retry.would_repeat:
        return retry.would_repeat
    return "read evidence.missing and evidence.truncated before deciding what to run next"


def _events_line(diagnostics: JobDiagnostics) -> str:
    events = diagnostics.events
    cursor = f"firstCursor={events.first_cursor}" if events.first_cursor else "firstCursor=absent"
    if events.next_cursor:
        cursor = f"{cursor}, nextCursor={events.next_cursor}"
    truncated = "true" if events.truncated else "false"
    return f"events: {events.mode} {len(events.items)} of {events.total_count}, truncated={truncated}, {cursor}"


def _marker_block(title: str, items: Sequence[str]) -> list[str]:
    if not items:
        return []
    return [f"{title}:", *[f"  {item}" for item in items]]


def _append_unique(lines: list[str], line: str) -> None:
    if line not in lines:
        lines.append(line)


def _local_document(path: Path, *, events: int, event_cursor: str | None) -> JsonObject:
    directory = _receipt_directory(path)
    receipt = _read_json_object(directory / "receipt.json")
    limit = _validate_events(events)
    records, skipped = _read_journal(directory, receipt)
    selected, total, next_cursor, mode = _select_records(records, limit=limit, event_cursor=event_cursor)
    missing: list[str] = []
    truncated: list[str] = []
    notes = ["local receipt; no server authorization view was consulted and no credentials were read"]
    if skipped:
        notes.append(f"{skipped} journal lines were not honua.gp.events/v1 records and were not read as events")
    document: JsonObject = {
        "schema": SCHEMA_ID,
        "jobId": _required_text(receipt, "runId", "runId"),
        "generatedAt": _generated_at(records),
        "view": "owner",
        "identity": _local_identity(receipt, missing),
        "release": _local_release(receipt, missing),
        "lifecycle": _local_lifecycle(receipt, records),
        "attempt": _local_attempt(records, notes),
        "worker": _local_worker(receipt, missing),
        "steps": _local_steps(records, receipt),
        "events": _local_events(selected, (total, limit, next_cursor, mode), truncated),
        "artifacts": _local_artifacts(directory, receipt, missing),
        "evidence": {"missing": missing, "truncated": truncated, "notes": notes},
        "links": _local_links(receipt, missing),
    }
    failure = _local_failure(receipt, records)
    if failure is not None:
        document["failure"] = failure
    _note_journal_truncation(receipt, truncated)
    return document


def _local_identity(receipt: Mapping[str, Any], missing: list[str]) -> JsonObject:
    entrypoint = _optional_text(receipt.get("entrypoint"))
    run_id = _optional_text(receipt.get("runId")) or "local"
    missing.append("identity.priority: not recorded on the local receipt")
    missing.append("identity.contractVersion: not recorded on the local receipt")
    backend = _optional_text(receipt.get("executionMode")) or "local"
    return {
        "kind": "local",
        "backend": backend,
        "targetKind": "local",
        "workloadName": entrypoint or run_id,
        "resourceRefs": [],
    }


def _local_release(receipt: Mapping[str, Any], missing: list[str]) -> JsonObject:
    entrypoint = _optional_text(receipt.get("entrypoint"))
    absent = ["runtime", "sourceRepository", "sourceRef", "dependencyManifest", "serverVersion"]
    release_missing = [f"release.{name}" for name in absent]
    for name in release_missing:
        missing.append(f"{name}: not recorded on the local receipt")
    state = "partial" if entrypoint else "unavailable"
    release: JsonObject = {"state": state, "processDefinitions": [], "missing": release_missing}
    if entrypoint:
        release["entrypoint"] = entrypoint
    return release


def _local_lifecycle(receipt: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> JsonObject:
    status = _optional_text(receipt.get("status")) or ""
    canonical = {
        "succeeded": ("Succeeded", "completed"),
        "failed": ("Failed", "failed"),
        "setupFailed": ("Failed", "failed"),
        "cancelled": ("Cancelled", "cancelled"),
    }.get(status, (status or "unknown", "unknown"))
    started = _record_time(records[0]) if records else _generated_at(records)
    updated = _record_time(records[-1]) if records else started
    terminal = next((record for record in reversed(records) if record.get("kind") == "terminal"), None)
    first_elapsed = _elapsed(records[0] if records else None)
    lifecycle: JsonObject = {
        "status": canonical[0],
        "phase": canonical[1],
        "createdAt": started,
        "updatedAt": updated,
        "timingSource": "measured" if first_elapsed is not None and terminal else "inferred",
    }
    current = _optional_text(receipt.get("failedPhase"))
    if current:
        lifecycle["currentPhase"] = current
    if terminal is not None:
        lifecycle["completedAt"] = _record_time(terminal)
        elapsed = _elapsed(terminal)
        if elapsed is not None:
            lifecycle["durationMs"] = elapsed
    return lifecycle


def _local_attempt(records: Sequence[Mapping[str, Any]], notes: list[str]) -> JsonObject:
    token = next(
        (str(record.get("attempt")) for record in records if record.get("attempt") is not None),
        "local",
    )
    number = int(token) if token.isdigit() else 1
    if not token.isdigit():
        notes.append(f"journal attempt identity: {token}")
    return {
        "number": number,
        "retry": {
            "allowed": False,
            "disabledReason": "local receipt; the server retry route was not called",
            "requiresApproval": False,
            "wouldRepeat": (
                "re-running the same local command repeats this attempt on this machine; no server retry is recorded"
            ),
        },
    }


def _local_worker(receipt: Mapping[str, Any], missing: list[str]) -> JsonObject:
    status = _optional_text(receipt.get("status")) or ""
    terminal = status in {"succeeded", "failed", "setupFailed", "cancelled"}
    missing.append("worker.heartbeatIntervalSeconds: not recorded on the local receipt")
    missing.append("worker.heartbeatTimeoutSeconds: not recorded on the local receipt")
    if terminal:
        return {
            "liveness": "finished",
            "livenessReason": "local receipt has no heartbeat; the run already reached a terminal status",
        }
    return {
        "liveness": "unknown",
        "livenessReason": "local receipt has no heartbeat and no terminal status",
    }


def _local_failure(
    receipt: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> JsonObject | None:
    status = _optional_text(receipt.get("status")) or ""
    if status not in {"failed", "setupFailed", "cancelled"}:
        return None
    error = receipt.get("error")
    message = ""
    if isinstance(error, Mapping) and isinstance(error.get("message"), str):
        message = error["message"]
    if not message and status == "cancelled":
        message = "local run cancelled"
    message = redact_secrets(message or "local run failed")
    classification = "cancelled" if status == "cancelled" else "execution_failed"
    if "timeout" in message.lower():
        classification = "timeout"
    failure_record = next((record for record in reversed(records) if record.get("kind") == "failure"), None)
    failure: JsonObject = {
        "message": message,
        "classification": classification,
        "recovery": _local_recovery(status),
    }
    phase = _optional_text(receipt.get("failedPhase"))
    if phase:
        failure["phase"] = phase
    if failure_record is not None and isinstance(failure_record.get("seq"), int):
        failure["stepOrdinal"] = failure_record["seq"]
    exit_code = receipt.get("exitCode")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        failure["nativeExitCode"] = exit_code
    if message:
        failure["stderrExcerpt"] = message
    return failure


def _local_recovery(status: str) -> str:
    if status == "cancelled":
        return "the local run was cancelled; re-run the local command to repeat it"
    return "fix the reported error and re-run the local command; this receipt cannot be retried on a server"


def _local_steps(records: Sequence[Mapping[str, Any]], receipt: Mapping[str, Any]) -> list[JsonObject]:
    phases = [record for record in records if record.get("kind") == "phase" and isinstance(record.get("phase"), str)]
    failed = _optional_text(receipt.get("failedPhase"))
    steps: list[JsonObject] = []
    for index, record in enumerate(phases):
        nxt = phases[index + 1] if index + 1 < len(phases) else None
        elapsed = _elapsed(record)
        next_elapsed = _elapsed(nxt)
        measured = elapsed is not None and next_elapsed is not None
        step: JsonObject = {
            "ordinal": record.get("seq") if isinstance(record.get("seq"), int) else index,
            "phase": record["phase"],
            "status": "failed" if record.get("phase") == failed else "completed",
            "startedAt": _record_time(record),
            "message": str(record.get("phase")),
            "timingSource": "measured" if measured else "inferred",
        }
        if measured and elapsed is not None and next_elapsed is not None:
            step["durationMs"] = next_elapsed - elapsed
        steps.append(step)
    return steps


def _local_events(
    selected: Sequence[Mapping[str, Any]],
    bounds: tuple[int, int, str | None, str],
    truncated_notes: list[str],
) -> JsonObject:
    total, limit, next_cursor, mode = bounds
    page_truncated = total > len(selected)
    if page_truncated:
        truncated_notes.append(
            f"events: {len(selected)} of {total} returned; use firstCursor to start paging and nextCursor to continue"
        )
    events: JsonObject = {
        "state": "available" if total or selected else "unavailable",
        "items": [_event_from_record(record) for record in selected],
        "totalCount": total,
        "limit": limit,
        "mode": mode,
        "truncated": page_truncated,
    }
    if total:
        events["firstCursor"] = "start"
    if next_cursor is not None:
        events["nextCursor"] = next_cursor
    return events


def _local_artifacts(directory: Path, receipt: Mapping[str, Any], missing: list[str]) -> JsonObject:
    raw_items = receipt.get("artifacts")
    items: list[JsonObject] = []
    if isinstance(raw_items, list):
        for artifact in raw_items:
            if isinstance(artifact, Mapping):
                items.append(_one_artifact(directory, artifact))
    available = sum(1 for item in items if item.get("availability") == "Available")
    unavailable = len(items) - available
    if not items:
        state = "none"
    elif unavailable == 0:
        state = "complete"
    elif available:
        state = "partial"
    else:
        state = "unavailable"
    if unavailable:
        missing.append(f"artifacts: {unavailable} artifact reference(s) could not be resolved")
    return {
        "state": state,
        "items": items,
        "availableCount": available,
        "expiredCount": 0,
        "unavailableCount": unavailable,
    }


def _one_artifact(directory: Path, artifact: Mapping[str, Any]) -> JsonObject:
    raw_name = artifact.get("name")
    name = raw_name if isinstance(raw_name, str) else "artifact"
    raw_path = artifact.get("path")
    relative = raw_path if isinstance(raw_path, str) else name
    item: JsonObject = {
        "artifactId": artifact.get("sha256") if isinstance(artifact.get("sha256"), str) else name,
        "availability": "Available" if _artifact_file(directory, relative) else "Unavailable",
        "label": name,
    }
    size = artifact.get("sizeBytes")
    if isinstance(size, int) and not isinstance(size, bool):
        item["sizeBytes"] = size
    return item


def _local_links(receipt: Mapping[str, Any], missing: list[str]) -> JsonObject:
    missing.append("links: local receipt has no admin job routes")
    journal = _optional_text(receipt.get("events")) or "events.jsonl"
    return {"self": "receipt.json", "logs": journal, "artifacts": "artifacts", "steps": journal}


def _note_journal_truncation(receipt: Mapping[str, Any], truncated: list[str]) -> None:
    if receipt.get("eventsTruncated") is True:
        dropped = receipt.get("eventsDropped")
        count = dropped if isinstance(dropped, int) and not isinstance(dropped, bool) else 0
        truncated.append(f"events: receipt eventsTruncated is true; {count} records were dropped by the journal cap")


def _event_from_record(record: Mapping[str, Any]) -> JsonObject:
    kind = str(record.get("kind") or "log")
    message = redact_secrets(_record_message(record))
    level = "Info"
    if kind == "failure" or (kind == "terminal" and record.get("status") != "succeeded"):
        level = "Error"
    elif kind == "truncated" or (kind == "log" and record.get("level") == "warning"):
        level = "Warning"
    entry: JsonObject = {"timestamp": _record_time(record), "level": level, "message": message}
    phase = record.get("phase")
    if isinstance(phase, str) and phase:
        entry["phase"] = phase
    metadata: JsonObject = {}
    for key in ("kind", "seq", "attempt", "elapsedMs"):
        if record.get(key) is not None:
            metadata[f"honua.event.{key}"] = str(record[key])
    if metadata:
        entry["metadata"] = metadata
    return entry


def _record_message(record: Mapping[str, Any]) -> str:
    kind = record.get("kind")
    message = record.get("message")
    if kind == "log" and isinstance(message, str):
        return message
    if kind == "failure":
        return _failure_record_message(record)
    rendered = _simple_kind_message(kind, record)
    if rendered is not None:
        return rendered
    if isinstance(record.get("phase"), str):
        return str(record["phase"])
    return str(kind)


def _failure_record_message(record: Mapping[str, Any]) -> str:
    error = record.get("error")
    if isinstance(error, Mapping):
        message = error.get("message")
        if isinstance(message, str):
            return message
    return "failure"


def _simple_kind_message(kind: Any, record: Mapping[str, Any]) -> str | None:
    if kind == "terminal":
        return f"terminal {record.get('status')}"
    if kind == "truncated":
        return f"truncated dropped={record.get('dropped')}"
    if kind == "artifact":
        artifact = record.get("artifact")
        name = artifact.get("name") if isinstance(artifact, Mapping) else "artifact"
        return f"artifact {name}"
    if kind == "progress":
        return f"progress {record.get('percent')}"
    return None


def _select_records(
    records: Sequence[Mapping[str, Any]],
    *,
    limit: int,
    event_cursor: str | None,
) -> tuple[list[Mapping[str, Any]], int, str | None, str]:
    total = len(records)
    if event_cursor is None:
        start = max(0, total - limit)
        return list(records[start:]), total, None, "tail"
    start = 0 if event_cursor == "start" else _decode_cursor(event_cursor)
    if start > total:
        raise GpDiagnosticsUsageError("Invalid diagnostic event cursor.")
    selected = list(records[start : start + limit])
    next_offset = start + len(selected)
    next_cursor = _encode_cursor(next_offset) if next_offset < total else None
    return selected, total, next_cursor, "page"


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"v1:{offset}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> int:
    padded = cursor + ("=" * (-len(cursor) % 4))
    try:
        text = base64.urlsafe_b64decode(padded.encode()).decode()
        prefix, raw_offset = text.split(":", 1)
        offset = int(raw_offset)
    except (ValueError, binascii.Error, UnicodeError):
        raise GpDiagnosticsUsageError("Invalid diagnostic event cursor.") from None
    if prefix != "v1" or offset < 0:
        raise GpDiagnosticsUsageError("Invalid diagnostic event cursor.")
    return offset


def _read_journal(directory: Path, receipt: Mapping[str, Any]) -> tuple[list[JsonObject], int]:
    name = _optional_text(receipt.get("events")) or "events.jsonl"
    path = _artifact_file(directory, name)
    if path is None:
        return [], 0
    records: list[JsonObject] = []
    skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(value, dict) and value.get("v") == 1 and isinstance(value.get("kind"), str):
            records.append(value)
        else:
            skipped += 1
    return records, skipped


def _receipt_directory(path: Path) -> Path:
    if path.is_file() and path.name == "receipt.json":
        return path.parent
    if path.is_dir() and (path / "receipt.json").is_file():
        return path
    raise GpDiagnosticsUsageError(f"{path} is not a local receipt directory")


def _read_json_object(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GpDiagnosticsUsageError(f"could not read {path.name}") from exc
    if not isinstance(value, dict):
        raise GpDiagnosticsUsageError(f"{path.name} must be a JSON object")
    return value


def _artifact_file(directory: Path, relative: str) -> Path | None:
    parts = Path(relative).parts
    if not relative or relative.startswith(("/", "\\")) or ".." in parts:
        return None
    candidate = (directory / relative).resolve()
    try:
        candidate.relative_to(directory.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _generated_at(records: Sequence[Mapping[str, Any]]) -> str:
    if records:
        return _record_time(records[-1])
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _record_time(record: Mapping[str, Any] | None) -> str:
    if record is not None:
        stamp = record.get("at")
        if isinstance(stamp, str):
            return stamp
    return _generated_at(())


def _elapsed(record: Mapping[str, Any] | None) -> int | None:
    if record is None:
        return None
    value = record.get("elapsedMs")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _required_text(raw: Mapping[str, Any], key: str, label: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise GpDiagnosticsUsageError(f"local receipt is missing {label}")
    return value


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _section(document: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = document.get(key)
    return value if isinstance(value, Mapping) else {}


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GpDiagnosticsContractError(f"{label} must be an object")
    return value


def _require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise GpDiagnosticsContractError(f"{label} must be a boolean")
    return value


def _require_strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise GpDiagnosticsContractError(f"{label} must be an array of strings")
    return tuple(value)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _required_count(value: Any) -> int:
    parsed = _optional_int(value)
    return parsed if parsed is not None else 0


def _optional_cursor(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _redact_value(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        return redact_secrets(value, secrets)
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _redact_value(item, secrets) for key, item in value.items()}
    return value


def _redact_assignments(text: str) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in _ASSIGNMENT.finditer(text):
        pieces.append(text[cursor : match.start()])
        pieces.append(match.group(1) + _REDACTED)
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


def _redact_tokens(text: str) -> str:
    return _BEARER.sub(lambda match: match.group(1) + _REDACTED, text)


def _redact_userinfo(text: str) -> str:
    return _USERINFO.sub(_REDACTED, text)
