from __future__ import annotations

from pathlib import Path
from uuid import UUID

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


def test_probe_query_seeded_layer_matches_current_seed_contract() -> None:
    class FakeClient:
        def query_features(
            self,
            service_id: str,
            layer_id: int,
            *,
            out_fields: list[str],
            return_geometry: bool,
            extra_params: dict[str, int],
        ) -> dict[str, object]:
            assert service_id == "test_service"
            assert layer_id == 0
            assert out_fields == ["*"]
            assert return_geometry is True
            assert extra_params == {"resultRecordCount": smoke.READ_QUERY_LIMIT}
            return {
                "spatialReference": {"wkid": 4326},
                "features": [
                    {
                        "attributes": {
                            "objectid": 10,
                            "name": "MCP Feature 01",
                            "count": 10,
                            "ratio": 1.5,
                            "status": "active",
                        },
                        "geometry": {"x": -122.45, "y": 37.75},
                    }
                ],
            }

    result = smoke.probe_query_seeded_layer(
        FakeClient(),
        smoke.SmokeConfig(base_url="https://staging.example.test"),
    )

    assert result["sample_objectid"] == 10
    assert result["observed_fields"] == ["count", "name", "objectid", "ratio", "status"]


def test_probe_apply_edits_roundtrip_uses_uuid_uid_and_description_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_uid = UUID("12345678-1234-5678-1234-567812345678")
    monkeypatch.setattr(smoke, "uuid4", lambda: expected_uid)

    class FakeClient:
        def __init__(self) -> None:
            self.feature: dict[str, object] | None = None

        def query_features(
            self,
            service_id: str,
            layer_id: int,
            *,
            where: str,
            out_fields: list[str],
            return_geometry: bool,
            extra_params: dict[str, int],
        ) -> dict[str, object]:
            assert service_id == "test_service"
            assert layer_id == 0
            assert where == smoke.build_uid_where(str(expected_uid))
            assert extra_params["resultRecordCount"] in {2, smoke.WRITE_QUERY_LIMIT}
            return {
                "spatialReference": {"wkid": 4326},
                "features": [] if self.feature is None else [self.feature],
            }

        def apply_edits(
            self,
            service_id: str,
            layer_id: int,
            *,
            adds: list[dict[str, object]] | None = None,
            updates: list[dict[str, object]] | None = None,
            deletes: list[int] | None = None,
            rollback_on_failure: bool = True,
        ) -> dict[str, object]:
            assert service_id == "test_service"
            assert layer_id == 0
            assert rollback_on_failure is True

            if adds is not None:
                assert len(adds) == 1
                attributes = dict(adds[0]["attributes"])
                assert attributes["uid"] == str(expected_uid)
                assert attributes["description"] == f"sdk-python-smoke:{expected_uid}"
                self.feature = {
                    "attributes": {
                        **attributes,
                        "objectid": 1001,
                    },
                    "geometry": dict(adds[0]["geometry"]),
                }
                return {"addResults": [{"success": True, "objectId": 1001}]}

            if updates is not None:
                assert len(updates) == 1
                attributes = dict(updates[0]["attributes"])
                assert attributes["uid"] == str(expected_uid)
                assert attributes["description"] == f"sdk-python-smoke:{expected_uid}"
                assert attributes["objectid"] == 1001
                self.feature = {
                    "attributes": dict(attributes),
                    "geometry": dict(updates[0]["geometry"]),
                }
                return {"updateResults": [{"success": True, "objectId": 1001}]}

            assert deletes == [1001]
            self.feature = None
            return {"deleteResults": [{"success": True, "objectId": 1001}]}

    result = smoke.probe_apply_edits_roundtrip(
        FakeClient(),
        smoke.SmokeConfig(base_url="https://staging.example.test"),
    )

    assert result["uid"] == str(expected_uid)
    assert result["description"] == f"sdk-python-smoke:{expected_uid}"
    assert result["cleanup"]["deleted_objectids"] == [1001]
    assert result["cleanup"]["remaining_feature_count"] == 0


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
