"""GP inspect/logs over the canonical honua.job-diagnostics/v1 projection.

These tests drive the shipped formatter, pagination, CLI dispatch, offline
receipt reading, and auth/redaction behavior. They do not claim a live
installed-package journey.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from honua_sdk import AsyncHonuaClient, HonuaClient
from honua_sdk import cli
from honua_sdk.errors import HonuaAuthError
from honua_sdk.gp_diagnostics import (
    EXIT_EXPIRED,
    EXIT_INTERRUPTED,
    EXIT_MISSING,
    EXIT_UNAUTHORIZED,
    SCHEMA_ID,
    format_job_diagnostics,
    iter_local_event_pages,
    load_local_receipt,
    parse_job_diagnostics,
    redact_secrets,
)

_SECRET = "super-secret-value"


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = _merge(current, value)
        else:
            merged[key] = value
    return merged


def _projection(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "jobId": "job-1",
        "generatedAt": "2026-10-23T00:00:00.000Z",
        "view": "operator",
        "identity": {
            "kind": "Geoprocessing",
            "backend": "managed",
            "targetKind": "Process",
            "workloadName": "geometry.buffer",
            "priority": "Normal",
            "contractVersion": 1,
            "resourceRefs": [],
        },
        "release": {
            "state": "partial",
            "serverVersion": "2026.1.0",
            "processDefinitions": ["geometry.buffer"],
            "missing": ["release.planId"],
        },
        "lifecycle": {
            "status": "Failed",
            "phase": "failed",
            "currentPhase": "Reproject",
            "createdAt": "2026-10-23T00:00:00.000Z",
            "updatedAt": "2026-10-23T00:05:00.000Z",
            "timingSource": "inferred",
        },
        "attempt": {
            "number": 1,
            "maxAttempts": 3,
            "retry": {
                "allowed": False,
                "disabledReason": "retry budget is exhausted",
                "requiresApproval": False,
                "wouldRepeat": (
                    "re-dispatches the whole job as attempt 2 of 3 on backend 'managed' "
                    "with the same spec; no committed effects are recorded from earlier attempts"
                ),
            },
        },
        "worker": {
            "liveness": "finished",
            "livenessReason": "job is Failed; no worker is expected to be alive",
            "heartbeatIntervalSeconds": 30,
            "heartbeatTimeoutSeconds": 90,
        },
        "failure": {
            "message": "gdalwarp failed",
            "classification": "execution_failed",
            "phase": "Reproject",
            "stepOrdinal": 1,
            "errorCode": "GDAL_WARP_FAILED",
            "nativeExitCode": 2,
            "stderrExcerpt": "ERROR 1: PROJ: [REDACTED] could not open <path>",
            "recovery": "fix the reported error and resubmit; this job cannot be retried in place",
        },
        "steps": [
            {
                "ordinal": 1,
                "phase": "Reproject",
                "status": "failed",
                "startedAt": "2026-10-23T00:04:00.000Z",
                "message": "gdalwarp failed",
                "timingSource": "inferred",
            }
        ],
        "events": {
            "state": "available",
            "items": [
                {
                    "timestamp": "2026-10-23T00:04:00.000Z",
                    "level": "Error",
                    "message": "gdalwarp failed",
                    "phase": "Reproject",
                }
            ],
            "totalCount": 5,
            "limit": 1,
            "firstCursor": "start",
            "nextCursor": "cursor-2",
            "mode": "page",
            "truncated": True,
        },
        "artifacts": {
            "state": "partial",
            "items": [
                {"artifactId": "expired", "availability": "Expired", "label": "expired"},
                {"artifactId": "available", "availability": "Available", "label": "available"},
            ],
            "availableCount": 1,
            "expiredCount": 1,
            "unavailableCount": 0,
        },
        "evidence": {
            "missing": [
                "lifecycle.claimedAt: the job record carries no claim timestamp, so queue delay and execution time are not measured",
                "artifacts: 1 artifact(s) expired and can no longer be fetched",
                "release.planId: not recorded on the job",
            ],
            "truncated": ["events: 1 of 5 returned; use firstCursor to start paging and nextCursor to continue"],
            "notes": [
                "step timingSource identifies measured harness durations or durations inferred from consecutive log timestamps"
            ],
        },
        "links": {
            "self": "/api/v1/admin/jobs/job-1",
            "logs": "/api/v1/admin/jobs/job-1/logs",
            "artifacts": "/api/v1/admin/jobs/job-1/artifacts",
            "actions": "/api/v1/admin/jobs/job-1/actions",
            "steps": "/api/v1/admin/jobs/job-1/steps",
            "diagnostics": "/api/v1/admin/jobs/job-1/diagnostics",
        },
    }
    return _merge(document, overrides)


def _event(message: str) -> dict[str, str]:
    return {
        "timestamp": "2026-10-23T00:00:00.000Z",
        "level": "Info",
        "message": message,
        "phase": "Run",
    }


def _events_page(
    messages: list[str],
    *,
    mode: str,
    total: int,
    next_cursor: str | None,
    truncated: bool,
    truncated_notes: list[str],
) -> dict[str, Any]:
    events: dict[str, Any] = {
        "state": "available",
        "items": [_event(message) for message in messages],
        "totalCount": total,
        "limit": len(messages) or 1,
        "firstCursor": "start",
        "mode": mode,
        "truncated": truncated,
    }
    if next_cursor is not None:
        events["nextCursor"] = next_cursor
    page = _projection(
        events=events,
        evidence={
            "missing": ["lifecycle.claimedAt: the job record carries no claim timestamp"],
            "truncated": truncated_notes,
            "notes": ["kept-note"],
        },
    )
    # _projection deep-merges events, so an omitted cursor would keep the base nextCursor.
    if next_cursor is None:
        page["events"].pop("nextCursor", None)
    return page


def _pages() -> dict[str | None, dict[str, Any]]:
    return {
        None: _events_page(
            ["event 601", "event 602"],
            mode="tail",
            total=603,
            next_cursor=None,
            truncated=True,
            truncated_notes=["events: 2 of 603 returned; use firstCursor to start paging and nextCursor to continue"],
        ),
        "start": _events_page(
            ["event 0", "event 1"],
            mode="page",
            total=603,
            next_cursor="c1",
            truncated=True,
            truncated_notes=["events: 2 of 603 returned; use firstCursor to start paging and nextCursor to continue"],
        ),
        "c1": _events_page(
            ["event 2", "event 3"],
            mode="page",
            total=603,
            next_cursor=None,
            truncated=False,
            truncated_notes=["events: 2 earliest records were discarded by the durable storage limit"],
        ),
    }


def _client(handler: Any, *, api_key: str = "test-key") -> HonuaClient:
    return HonuaClient(
        "http://example.test",
        api_key=api_key,
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )


def test_formatter_keeps_failure_lead_cursors_and_evidence_markers() -> None:
    parsed = parse_job_diagnostics(_projection())
    text = format_job_diagnostics(parsed)
    lines = text.splitlines()

    assert parsed.schema == SCHEMA_ID
    assert parsed.failure is not None
    assert parsed.failure.phase == "Reproject"
    assert parsed.failure.step_ordinal == 1
    assert parsed.attempt.number == 1
    assert parsed.attempt.max_attempts == 3
    assert parsed.attempt.retry.allowed is False
    assert parsed.events.next_cursor == "cursor-2"
    assert parsed.events.first_cursor == "start"
    assert parsed.events.truncated is True
    assert parsed.artifacts.expired_count == 1
    assert any(item.startswith("artifacts: 1 artifact(s) expired") for item in parsed.evidence.missing)
    assert any(item.startswith("events:") for item in parsed.evidence.truncated)
    assert parsed.evidence.notes

    assert lines[0] == "failing phase Reproject, attempt 1 of 3"
    assert lines[1] == "next: fix the reported error and resubmit; this job cannot be retried in place"
    assert "re-dispatches the whole job" not in lines[1]
    assert "cursor-2" in text
    assert "firstCursor=start" in text
    assert "lifecycle.claimedAt:" in text
    assert "events: 1 of 5 returned" in text
    assert "expired" in text


def test_allowed_retry_next_action_uses_recovery() -> None:
    document = _projection(
        attempt={
            "number": 1,
            "maxAttempts": 3,
            "retry": {
                "allowed": True,
                "requiresApproval": False,
                "wouldRepeat": "re-dispatches the whole job as attempt 2 of 3 on backend 'managed'",
            },
        },
        failure={
            "message": "gdalwarp failed",
            "classification": "execution_failed",
            "phase": "Reproject",
            "recovery": "a step failed with native output; fix the input or tool before retrying, since a retry repeats the same spec",
        },
    )
    text = format_job_diagnostics(parse_job_diagnostics(document))
    assert text.splitlines()[1].startswith("next: a step failed with native output")


def test_pages_keep_cursors_truncation_and_missing_evidence() -> None:
    pages = _pages()
    calls: list[tuple[str | None, str | None, str | None, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("eventCursor")
        calls.append((cursor, request.url.params.get("events"), request.headers.get("X-API-Key"), request.url.path))
        return httpx.Response(200, json=pages[cursor])

    with _client(handler) as client:
        tail = client.gp.diagnostics("job-1", events=2)
        assert [item.message for item in tail.events.items] == ["event 601", "event 602"]
        assert tail.events.mode == "tail"
        assert tail.events.next_cursor is None
        assert tail.events.first_cursor == "start"
        assert tail.events.truncated is True
        assert tail.evidence.truncated
        assert tail.evidence.missing
        assert "nextCursor" not in tail.document["events"]

        seen: list[tuple[Any, ...]] = []
        messages: list[str] = []
        for page in client.gp.iter_event_pages("job-1", events=2):
            seen.append(
                (
                    page.events.mode,
                    page.events.next_cursor,
                    page.events.first_cursor,
                    page.events.truncated,
                    tuple(page.evidence.truncated),
                    tuple(page.evidence.missing),
                    tuple(page.evidence.notes),
                )
            )
            messages.extend(item.message for item in page.events.items)

    assert messages == ["event 0", "event 1", "event 2", "event 3"]
    assert seen[0][1] == "c1"
    assert seen[0][2] == "start"
    assert seen[0][3] is True
    assert seen[0][4][0].startswith("events:")
    assert seen[0][5][0].startswith("lifecycle.claimedAt")
    assert seen[0][6] == ("kept-note",)
    assert seen[1][1] is None
    assert seen[1][3] is False
    assert seen[1][4][0].startswith("events: 2 earliest records")
    assert calls[0][0] is None and calls[0][1] == "2"
    assert calls[1][0] == "start"
    assert calls[2][0] == "c1"
    assert {call[2] for call in calls} == {"test-key"}
    assert {call[3] for call in calls} == {"/api/v1/admin/jobs/job-1/diagnostics"}


def test_diagnostics_rejects_unbounded_event_page_before_calling_the_server() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("events outside 1..500 must not be sent")

    with _client(handler) as client:
        with pytest.raises(ValueError, match="events"):
            client.gp.diagnostics("job-1", events=0)
        with pytest.raises(ValueError, match="events"):
            client.gp.diagnostics("job-1", events=501)


def _write_receipt(directory: Path, *, secret: str = _SECRET) -> Path:
    run = directory / "run1"
    run.mkdir()
    (run / "artifacts").mkdir()
    (run / "artifacts" / "out.txt").write_text("ok\n", encoding="utf-8")
    events = [
        {
            "v": 1,
            "seq": 0,
            "at": "2026-10-23T00:00:00.000Z",
            "elapsedMs": 0,
            "attempt": "local",
            "kind": "phase",
            "phase": "execute",
        },
        {
            "v": 1,
            "seq": 1,
            "at": "2026-10-23T00:00:01.000Z",
            "elapsedMs": 1000,
            "attempt": "local",
            "kind": "log",
            "level": "info",
            "phase": "execute",
            "message": "working",
        },
        {
            "v": 1,
            "seq": 2,
            "at": "2026-10-23T00:00:02.000Z",
            "elapsedMs": 2000,
            "attempt": "local",
            "kind": "failure",
            "phase": "execute",
            "error": {"type": "RuntimeError", "message": f"tool failed token={secret}"},
        },
        {
            "v": 1,
            "seq": 3,
            "at": "2026-10-23T00:00:02.000Z",
            "elapsedMs": 2000,
            "attempt": "local",
            "kind": "terminal",
            "status": "failed",
            "exitCode": 1,
            "phase": "execute",
        },
    ]
    (run / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    receipt = {
        "schemaVersion": "1.0",
        "runId": "run1",
        "entrypoint": "tools.buffer:execute",
        "executionMode": "local",
        "artifacts": [
            {"name": "out.txt", "path": "artifacts/out.txt", "sizeBytes": 3, "sha256": "abc"},
            {"name": "missing.bin", "path": "artifacts/missing.bin", "sizeBytes": 1, "sha256": "def"},
        ],
        "events": "events.jsonl",
        "eventsSchema": "honua.gp.events/v1",
        "status": "failed",
        "failedPhase": "execute",
        "error": {"type": "RuntimeError", "message": f"tool failed token={secret} password={secret}"},
        "eventsTruncated": True,
        "eventsDropped": 3,
        "exitCode": 1,
    }
    (run / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return run


def test_local_receipt_uses_the_same_formatter_and_discloses_gaps(tmp_path: Path) -> None:
    run = _write_receipt(tmp_path)
    loaded = load_local_receipt(run, events=2)
    rendered = format_job_diagnostics(loaded)
    lines = rendered.splitlines()

    assert loaded.schema == SCHEMA_ID
    assert loaded.document["schema"] == SCHEMA_ID
    assert lines[0].startswith("failing phase execute, attempt ")
    assert lines[1].startswith("next: ")
    assert "retry the job on a server" not in lines[1]
    assert loaded.attempt.retry.allowed is False
    assert loaded.events.truncated is True
    assert loaded.events.first_cursor == "start"
    assert any(item.startswith("release.") for item in loaded.evidence.missing)
    assert any("eventsTruncated" in item or item.startswith("events:") for item in loaded.evidence.truncated)
    assert _SECRET not in rendered
    assert _SECRET not in json.dumps(loaded.document)
    assert "[REDACTED]" in rendered

    pages = list(iter_local_event_pages(run, events=2))
    messages = [item.message for page in pages for item in page.events.items]
    assert "working" in " ".join(messages)
    assert pages[0].events.next_cursor
    assert pages[-1].events.next_cursor is None
    assert any(page.events.truncated or page.evidence.truncated for page in pages)
    assert all(_SECRET not in item.message for page in pages for item in page.events.items)


def test_redact_secrets_covers_assignments_userinfo_and_caller_credentials() -> None:
    assert redact_secrets(f"token={_SECRET}") == "token=[REDACTED]"
    assert redact_secrets(f"https://user:{_SECRET}@git.example.com/org/tools.git") == "[REDACTED]"
    assert redact_secrets(f"header {_SECRET}", secrets=[_SECRET]) == "header [REDACTED]"
    assert "Bearer [REDACTED]" in redact_secrets(f"Authorization: Bearer {_SECRET}")


def test_inspect_and_logs_do_not_call_the_devkit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _write_receipt(tmp_path)
    calls: list[list[str]] = []

    def delegate(args: list[str]) -> int:
        calls.append(list(args))
        return 99

    monkeypatch.setattr(cli, "_delegate_gp", delegate)
    monkeypatch.delenv("HONUA_BASE_URL", raising=False)
    monkeypatch.delenv("HONUA_API_KEY", raising=False)
    monkeypatch.setenv("HONUA_GP_CLI", "/tools/honua-gp-devkit")

    assert cli.main(["gp", "inspect", str(run)]) == 0
    assert cli.main(["gp", "logs", str(run), "--events", "2"]) == 0
    assert cli.main(["gp", "doctor", "--json"]) == 99

    assert calls == [["doctor", "--json"]]
    captured = capsys.readouterr()
    assert _SECRET not in captured.out
    assert _SECRET not in captured.err


def test_local_inspect_makes_no_network_or_auth_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _write_receipt(tmp_path)

    def explode(*_args: Any, **_kwargs: Any) -> HonuaClient:
        raise AssertionError("local inspect must not construct a client")

    monkeypatch.setattr(cli, "_make_client", explode)
    monkeypatch.setattr(cli, "_delegate_gp", lambda _args: (_ for _ in ()).throw(AssertionError("devkit")))
    monkeypatch.delenv("HONUA_BASE_URL", raising=False)
    monkeypatch.delenv("HONUA_API_KEY", raising=False)

    assert cli.main(["gp", "inspect", str(run)]) == 0
    human = capsys.readouterr().out
    assert human == format_job_diagnostics(load_local_receipt(run))

    assert cli.main(["gp", "inspect", str(run), "--json"]) == 0
    raw = capsys.readouterr().out
    payload = json.loads(raw)
    assert payload["schema"] == SCHEMA_ID
    assert "next:" not in raw
    assert "Reading" not in raw
    assert _SECRET not in raw
    assert payload["evidence"]["missing"]
    assert payload["evidence"]["truncated"]


def test_remote_inspect_json_is_the_projection_and_uses_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    document = _projection()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=document)

    monkeypatch.setattr(cli, "_make_client", lambda _args: _client(handler, api_key="test-key"))
    monkeypatch.setattr(cli, "_delegate_gp", lambda _args: (_ for _ in ()).throw(AssertionError("devkit")))

    assert (
        cli.main(["gp", "inspect", "job-1", "--json", "--base-url", "http://example.test", "--api-key", "test-key"])
        == 0
    )
    captured = capsys.readouterr()
    assert json.loads(captured.out) == document
    assert "next:" not in captured.out
    assert captured.err == ""
    assert seen[0].url.path == "/api/v1/admin/jobs/job-1/diagnostics"
    assert seen[0].headers["X-API-Key"] == "test-key"
    assert len(seen) == 1


def test_remote_human_inspect_leads_with_phase_attempt_and_next_action(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    document = _projection()
    monkeypatch.setattr(
        cli,
        "_make_client",
        lambda _args: _client(lambda _request: httpx.Response(200, json=document)),
    )
    assert cli.main(["gp", "inspect", "job-1", "--base-url", "http://example.test"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "failing phase Reproject, attempt 1 of 3"
    assert lines[1].startswith("next: ")
    assert "cannot be retried" in lines[1]


def test_logs_stream_pages_and_disclose_truncation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pages = _pages()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[request.url.params.get("eventCursor")])

    monkeypatch.setattr(cli, "_make_client", lambda _args: _client(handler))
    assert cli.main(["gp", "logs", "job-1", "--events", "2", "--base-url", "http://example.test"]) == 0
    output = capsys.readouterr().out
    assert "event 0" in output
    assert "event 3" in output
    assert "event 601" not in output
    assert "truncated:" in output
    assert "events:" in output
    assert "c1" in output or "nextCursor" in output or "firstCursor" in output


def test_logs_json_keeps_page_cursors_without_prose(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pages = _pages()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[request.url.params.get("eventCursor")])

    monkeypatch.setattr(cli, "_make_client", lambda _args: _client(handler))
    assert cli.main(["gp", "logs", "job-1", "--json", "--events", "2", "--base-url", "http://example.test"]) == 0
    raw = capsys.readouterr().out
    assert "next:" not in raw
    decoded = [json.loads(line) for line in raw.splitlines() if line.strip()]
    assert len(decoded) == 2
    assert decoded[0]["events"]["nextCursor"] == "c1"
    assert decoded[0]["events"]["truncated"] is True
    assert decoded[0]["evidence"]["missing"]
    assert decoded[0]["evidence"]["truncated"]
    assert "nextCursor" not in decoded[1]["events"]
    assert decoded[1]["evidence"]["truncated"][0].startswith("events:")


def test_human_logs_redact_remote_event_and_disclosure_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "leaked-secret"
    api_key = "caller-api-key-9f3c"
    document = _projection(
        events={
            "state": "available",
            "items": [_event(f"token={secret} {api_key}")],
            "totalCount": 1,
            "limit": 1,
            "firstCursor": "start",
            "mode": "page",
            "truncated": False,
        },
        evidence={
            "missing": [f"journal retained token={secret}"],
            "truncated": [f"note {api_key}"],
            "notes": [],
        },
    )
    document["events"].pop("nextCursor", None)

    monkeypatch.setattr(
        cli,
        "_make_client",
        lambda _args: _client(lambda _request: httpx.Response(200, json=document), api_key=api_key),
    )
    code = cli.main(["gp", "logs", "job-1", "--base-url", "http://example.test", "--api-key", api_key])
    output = capsys.readouterr().out
    assert code == 0
    assert secret not in output
    assert api_key not in output
    assert "[REDACTED]" in output
    assert "token=[REDACTED]" in output


def test_human_logs_disclose_missing_evidence_when_no_events_remain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    explanation = "journal: events.jsonl is missing; no retained events were available"
    document = _projection(
        events={
            "state": "unavailable",
            "items": [],
            "totalCount": 0,
            "limit": 1,
            "mode": "page",
            "truncated": False,
        },
        evidence={
            "missing": [explanation],
            "truncated": [],
            "notes": [],
        },
    )
    document["events"].pop("nextCursor", None)
    document["events"].pop("firstCursor", None)

    monkeypatch.setattr(cli, "_make_client", lambda _args: _client(lambda _request: httpx.Response(200, json=document)))
    code = cli.main(["gp", "logs", "job-1", "--base-url", "http://example.test"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip()
    assert explanation in captured.out
    assert "missing evidence" in captured.out
    assert captured.err == ""


def test_403_is_unauthorized_not_missing_evidence(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == _SECRET
        return httpx.Response(
            403,
            json={"status": 403, "title": "Forbidden", "detail": "The credential cannot read this job."},
        )

    with _client(handler, api_key=_SECRET) as client:
        with pytest.raises(HonuaAuthError) as caught:
            client.gp.diagnostics("job-1")
    assert caught.value.status_code == 403

    monkeypatch.setattr(cli, "_make_client", lambda _args: _client(handler, api_key=_SECRET))
    monkeypatch.setattr(cli, "_delegate_gp", lambda _args: (_ for _ in ()).throw(AssertionError("devkit")))
    with caplog.at_level("DEBUG"):
        code = cli.main(["gp", "inspect", "job-1", "--base-url", "http://example.test", "--api-key", _SECRET])
    captured = capsys.readouterr()
    assert code == EXIT_UNAUTHORIZED
    assert code != EXIT_MISSING
    assert "unauthorized" in captured.err.lower()
    assert "HTTP 403" in captured.err
    assert "missing evidence" not in captured.err.lower()
    assert "not found" not in captured.err.lower()
    assert _SECRET not in captured.err
    assert _SECRET not in captured.out
    assert _SECRET not in caplog.text
    assert captured.out == ""


def test_missing_expired_and_interrupted_are_distinct(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def install(handler: Any) -> None:
        monkeypatch.setattr(cli, "_make_client", lambda _args: _client(handler, api_key=_SECRET))

    install(lambda _request: httpx.Response(404, json={"detail": "Job 'job-1' was not found."}))
    missing = cli.main(["gp", "inspect", "job-1", "--base-url", "http://example.test", "--api-key", _SECRET])
    missing_err = capsys.readouterr().err
    assert missing == EXIT_MISSING
    assert missing != EXIT_UNAUTHORIZED
    assert "not found" in missing_err.lower()
    assert "unauthorized" not in missing_err.lower()
    assert "missing evidence" not in missing_err.lower()
    assert _SECRET not in missing_err

    install(lambda _request: httpx.Response(410, json={"detail": "retained job evidence expired"}))
    expired = cli.main(["gp", "logs", "job-1", "--base-url", "http://example.test", "--api-key", _SECRET])
    expired_err = capsys.readouterr().err
    assert expired == EXIT_EXPIRED
    assert expired != EXIT_MISSING
    assert "expired" in expired_err.lower()
    assert "not found" not in expired_err.lower()
    assert "missing evidence" not in expired_err.lower()
    assert _SECRET not in expired_err

    calls = {"n": 0}

    def interrupt(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=_pages()["start"])
        raise httpx.ConnectError(f"connection dropped while using {request.headers['X-API-Key']}")

    install(interrupt)
    interrupted = cli.main(
        ["gp", "logs", "job-1", "--events", "2", "--base-url", "http://example.test", "--api-key", _SECRET]
    )
    captured = capsys.readouterr()
    assert interrupted == EXIT_INTERRUPTED
    assert interrupted not in {EXIT_MISSING, EXIT_UNAUTHORIZED, EXIT_EXPIRED}
    assert "interrupted" in captured.err.lower()
    assert "event 0" in captured.out
    assert "event 1" in captured.out
    assert _SECRET not in captured.out
    assert _SECRET not in captured.err
    assert "not found" not in captured.err.lower()
    assert "missing evidence" not in captured.err.lower()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_async_client_pages_the_same_projection() -> None:
    pages = _pages()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[request.url.params.get("eventCursor")])

    async with AsyncHonuaClient(
        "http://example.test",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        max_retries=0,
    ) as client:
        tail = await client.gp.diagnostics("job-1", events=2)
        assert tail.events.first_cursor == "start"
        assert tail.evidence.missing
        collected = []
        async for page in client.gp.iter_event_pages("job-1", events=2):
            collected.append(page.events.next_cursor)
            assert page.evidence.notes == ("kept-note",)
    assert collected == ["c1", None]
