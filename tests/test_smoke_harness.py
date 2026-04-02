from __future__ import annotations

from pathlib import Path

import pytest

from honua_sdk.errors import HonuaHttpError
from scripts import _smoke_harness as smoke


def test_load_smoke_config_from_env_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_BASE_URL", "https://staging.example.test")
    monkeypatch.delenv("HONUA_SERVICE_ID", raising=False)
    monkeypatch.delenv("HONUA_LAYER_ID", raising=False)
    monkeypatch.delenv("HONUA_API_KEY", raising=False)
    monkeypatch.delenv("HONUA_ENABLE_WRITE_SMOKE", raising=False)
    monkeypatch.delenv("HONUA_SMOKE_UID_PREFIX", raising=False)
    monkeypatch.delenv("HONUA_SMOKE_RESULTS_PATH", raising=False)

    config = smoke.load_smoke_config_from_env()

    assert config.base_url == "https://staging.example.test"
    assert config.service_id == smoke.DEFAULT_SERVICE_ID
    assert config.layer_id == smoke.DEFAULT_LAYER_ID
    assert config.api_key is None
    assert config.enable_write_smoke is False
    assert config.uid_prefix == smoke.DEFAULT_UID_PREFIX
    assert config.results_path == smoke.DEFAULT_RESULTS_PATH


def test_load_smoke_config_from_env_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HONUA_BASE_URL", raising=False)

    with pytest.raises(smoke.SmokeConfigError, match="HONUA_BASE_URL is required"):
        smoke.load_smoke_config_from_env()


def test_load_smoke_config_from_env_rejects_bad_layer_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_BASE_URL", "https://staging.example.test")
    monkeypatch.setenv("HONUA_LAYER_ID", "abc")

    with pytest.raises(smoke.SmokeConfigError, match="HONUA_LAYER_ID must be an integer"):
        smoke.load_smoke_config_from_env()


def test_run_probe_captures_honua_http_error() -> None:
    result = smoke.run_probe(
        "readiness",
        lambda: (_ for _ in ()).throw(HonuaHttpError(503, "staging unavailable", body={"retry": True})),
        context={"base_url": "https://staging.example.test"},
    )

    assert result.status == "failed"
    assert result.error is not None
    assert result.error["status_code"] == 503
    assert result.error["message"] == "staging unavailable"
    assert result.error["body"] == {"retry": True}
    assert result.error["context"]["base_url"] == "https://staging.example.test"


def test_smoke_report_writes_json_and_renders_summary(tmp_path: Path) -> None:
    config = smoke.SmokeConfig(
        base_url="https://staging.example.test",
        service_id="test_service",
        layer_id=0,
        results_path=tmp_path / "staging-smoke-results.json",
    )
    report = smoke.SmokeReport(config=config)
    report.record(
        smoke.ProbeResult(
            name="readiness",
            status="passed",
            required=True,
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:00:01Z",
            details={"status": "ready"},
        )
    )
    report.record(
        smoke.ProbeResult(
            name="apply_edits_roundtrip",
            status="failed",
            required=True,
            started_at="2026-01-01T00:00:02Z",
            completed_at="2026-01-01T00:00:03Z",
            details={},
            error={
                "type": "HonuaHttpError",
                "message": "write denied",
                "status_code": 403,
            },
        )
    )

    output_path = report.write()
    payload = smoke.load_smoke_report(output_path)
    summary = smoke.render_smoke_summary(payload)

    assert output_path == tmp_path / "staging-smoke-results.json"
    assert payload["overall_status"] == "failed"
    assert payload["probe_counts"] == {"passed": 1, "failed": 1, "skipped": 0}
    assert "Overall status: `failed`" in summary
    assert "`apply_edits_roundtrip`: HTTP 403 write denied" in summary
