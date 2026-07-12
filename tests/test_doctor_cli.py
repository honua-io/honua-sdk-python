from __future__ import annotations

import json
import io
import stat
from pathlib import Path
import pytest

from honua_sdk import cli, diagnostics


def test_doctor_emits_valid_sanitized_bundle_and_machine_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "cli-super-secret-token"
    capture = tmp_path / "failure.json"
    capture.write_text(
        json.dumps(
            {
                "request": {
                    "method": "POST",
                    "url": f"https://example.test/rest/services/private/FeatureServer/7/query?token={secret}",
                    "headers": {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
                    "body": {"password": secret, "query": "customer data"},
                },
                "response": {
                    "status": 500,
                    "mediaType": "application/problem+json",
                    "headers": {"Set-Cookie": secret, "Content-Type": "application/problem+json"},
                    "body": {"error": secret},
                },
            }
        )
    )
    output = tmp_path / "bundle.json"

    result = cli.main(
        [
            "doctor",
            "--exchange",
            str(capture),
            "--classification",
            "customer-data",
            "--redaction-acknowledged",
            "true",
            "--share-with-support",
            "false",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    bundle = json.loads(output.read_text())
    diagnostics.assert_diagnostic_bundle(bundle)
    assert secret not in output.read_text()
    assert "customer data" not in output.read_text()
    assert all(value is not None for value in _walk_values(bundle))
    summary = json.loads(capsys.readouterr().out)
    assert summary["outcome"] == "emitted"
    assert summary["schemaSha256"] == diagnostics.DIAGNOSTIC_SCHEMA_SHA256
    assert summary["uploaded"] is False
    assert str(output) not in json.dumps(summary)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_doctor_probe_failure_keeps_supplied_failure_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "probe_capabilities",
        lambda _base_url, *, timeout: {"method": "GET", "url": "https://example.test/api/v1/services?limit=1"},
    )
    capture = tmp_path / "failure.json"
    capture.write_text(
        json.dumps(
            {
                "request": {"method": "GET", "url": "https://example.test/healthz/ready"},
                "response": {"status": 503},
            }
        )
    )
    output = tmp_path / "bundle.json"

    result = cli.main(
        [
            "doctor",
            "--base-url",
            "https://example.test",
            "--exchange",
            str(capture),
            "--classification",
            "internal",
            "--redaction-acknowledged",
            "true",
            "--share-with-support",
            "false",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    envelopes = json.loads(output.read_text())["envelopes"]
    assert len(envelopes) == 2
    assert envelopes[-1]["normalizedPath"] == "/healthz/ready"
    assert envelopes[-1]["statusCode"] == 503


def test_doctor_invalid_metadata_writes_no_artifact_and_leaks_no_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "Bearer secret-metadata-value"
    capture = tmp_path / "failure.json"
    capture.write_text(json.dumps({"request": {"method": "GET", "url": "https://example.test/healthz/ready"}}))
    output = tmp_path / "bundle.json"

    result = cli.main(
        [
            "doctor",
            "--exchange",
            str(capture),
            "--classification",
            "internal",
            "--redaction-acknowledged",
            "true",
            "--share-with-support",
            "false",
            "--bundle-id",
            secret,
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert not output.exists()
    assert secret not in captured.out
    assert secret not in captured.err
    assert "unsafe or invalid" in captured.err


def test_doctor_validates_final_serialized_bundle_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = tmp_path / "failure.json"
    capture.write_text(json.dumps({"request": {"method": "GET", "url": "https://example.test/healthz/ready"}}))
    output = tmp_path / "bundle.json"
    monkeypatch.setattr(
        cli,
        "assert_diagnostic_bundle",
        lambda _bundle: (_ for _ in ()).throw(diagnostics.DiagnosticValidationError(("forced drift",))),
    )

    result = cli.main(
        [
            "doctor",
            "--exchange",
            str(capture),
            "--classification",
            "internal",
            "--redaction-acknowledged",
            "true",
            "--share-with-support",
            "false",
            "--output",
            str(output),
        ]
    )

    assert result == 1
    assert not output.exists()


def test_doctor_help_describes_local_no_upload_workflow(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["doctor", "--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "sanitized diagnostic-bundle.v1" in help_text
    assert "never uploads" in help_text


def test_cli_empty_table_message_remains_covered() -> None:
    output = io.StringIO()

    cli._print_table([], ["name"], output)

    assert output.getvalue() == "(no entries)\n"


def test_doctor_replay_validates_then_writes_new_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_bundle = diagnostics.create_diagnostic_bundle(
        content_classification="internal",
        redaction_acknowledged=True,
        share_with_support=False,
        exchanges=[{"method": "GET", "url": "https://source.test/healthz/ready"}],
    )
    source = tmp_path / "source.json"
    source.write_text(json.dumps(source_bundle))
    output = tmp_path / "replayed.json"
    replayed = diagnostics.create_diagnostic_bundle(
        content_classification="internal",
        redaction_acknowledged=True,
        share_with_support=False,
        exchanges=[{"method": "GET", "url": "https://target.test/healthz/ready", "statusCode": 200}],
    )
    monkeypatch.setattr(cli, "replay_diagnostic_bundle", lambda *_args, **_kwargs: replayed)

    result = cli.main(
        [
            "doctor",
            "--replay",
            str(source),
            "--base-url",
            "https://target.test",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    diagnostics.assert_diagnostic_bundle(json.loads(output.read_text()))
    assert json.loads(capsys.readouterr().out)["outcome"] == "replayed"


def test_doctor_rejects_incomplete_emit_and_replay_invocations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HONUA_BASE_URL", raising=False)
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            diagnostics.create_diagnostic_bundle(
                content_classification="internal",
                redaction_acknowledged=True,
                share_with_support=False,
                exchanges=[{"method": "GET", "url": "https://source.test/healthz/ready"}],
            )
        )
    )
    base = {"output": str(tmp_path / "out.json"), "timeout": 1.0}
    invalid = [
        {**base, "replay": str(source), "exchange": "also.json", "base_url": "https://target.test"},
        {**base, "replay": str(source), "exchange": None, "base_url": None},
        {
            **base,
            "replay": None,
            "exchange": None,
            "base_url": None,
            "classification": None,
            "redaction_acknowledged": None,
            "share_with_support": None,
        },
        {
            **base,
            "replay": None,
            "exchange": None,
            "base_url": None,
            "classification": "internal",
            "redaction_acknowledged": "true",
            "share_with_support": "false",
            "bundle_id": None,
            "granted_by": None,
        },
    ]
    for arguments in invalid:
        with pytest.raises(cli._DoctorCliError):
            cli._cmd_doctor(_Namespace(**arguments), io.StringIO())


def test_doctor_input_shape_and_file_failures_are_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(cli._DoctorCliError):
        cli._read_diagnostic_json(str(missing))
    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(cli._DoctorCliError):
        cli._read_diagnostic_json(str(directory))
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not-json")
    with pytest.raises(cli._DoctorCliError):
        cli._read_diagnostic_json(str(malformed))

    for value in (None, {}, {"request": {}}, {"request": {"method": 42, "url": "/x"}}):
        with pytest.raises(cli._DoctorCliError):
            cli._captured_exchange(value)
    with pytest.raises(cli._DoctorCliError):
        cli._captured_exchange({"request": {"method": "GET", "url": "/x"}, "response": "bad"})
    with pytest.raises(cli._DoctorCliError):
        cli._explicit_bool("yes")

    monkeypatch.setattr(cli, "_write_diagnostic_bundle", lambda *_args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(cli._DoctorCliError):
        cli._write_diagnostic_bundle_safe(str(tmp_path / "out.json"), {})


def _walk_values(value: object) -> list[object]:
    if isinstance(value, dict):
        return [item for nested in value.values() for item in _walk_values(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in _walk_values(nested)]
    return [value]


class _Namespace:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)
