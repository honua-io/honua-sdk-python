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
    monkeypatch.delenv("HONUA_SERVER_COMMIT", raising=False)
    monkeypatch.delenv("HONUA_SERVER_IMAGE", raising=False)
    monkeypatch.delenv("HONUA_SEED_PROFILE", raising=False)
    monkeypatch.delenv("HONUA_OGC_COLLECTION_ID", raising=False)
    monkeypatch.delenv("HONUA_STAC_COLLECTION_ID", raising=False)
    monkeypatch.delenv("HONUA_OGC_PROCESS_ID", raising=False)
    monkeypatch.delenv("HONUA_OGC_PROCESS_PAYLOAD_JSON", raising=False)
    monkeypatch.delenv("HONUA_PROTOCOL_BBOX", raising=False)

    config = smoke.load_smoke_config_from_env()

    assert config.base_url == "https://staging.example.test"
    assert config.service_id == smoke.DEFAULT_SERVICE_ID
    assert config.layer_id == smoke.DEFAULT_LAYER_ID
    assert config.api_key is None
    assert config.enable_write_smoke is False
    assert config.uid_prefix == smoke.DEFAULT_UID_PREFIX
    assert config.results_path == smoke.DEFAULT_RESULTS_PATH
    assert config.server_commit is None
    assert config.server_image is None
    assert config.seed_profile is None
    assert config.ogc_collection_id is None
    assert config.stac_collection_id is None
    assert config.ogc_process_id is None
    assert config.ogc_process_payload is None
    assert config.protocol_bbox == smoke.DEFAULT_PROTOCOL_BBOX


def test_load_smoke_config_from_env_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HONUA_BASE_URL", raising=False)

    with pytest.raises(smoke.SmokeConfigError, match="HONUA_BASE_URL is required"):
        smoke.load_smoke_config_from_env()


def test_load_smoke_config_from_env_rejects_bad_layer_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_BASE_URL", "https://staging.example.test")
    monkeypatch.setenv("HONUA_LAYER_ID", "abc")

    with pytest.raises(smoke.SmokeConfigError, match="HONUA_LAYER_ID must be an integer"):
        smoke.load_smoke_config_from_env()


def test_load_smoke_config_from_env_records_protocol_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_BASE_URL", "https://staging.example.test")
    monkeypatch.setenv("HONUA_SERVER_COMMIT", "abc123")
    monkeypatch.setenv("HONUA_SERVER_IMAGE", "ghcr.io/honua/server:staging")
    monkeypatch.setenv("HONUA_SEED_PROFILE", "sdk-smoke")
    monkeypatch.setenv("HONUA_OGC_COLLECTION_ID", "parcels")
    monkeypatch.setenv("HONUA_STAC_COLLECTION_ID", "imagery")
    monkeypatch.setenv("HONUA_OGC_PROCESS_ID", "buffer")
    monkeypatch.setenv("HONUA_OGC_PROCESS_PAYLOAD_JSON", '{"inputs":{"distance":10}}')
    monkeypatch.setenv("HONUA_PROTOCOL_BBOX", "-158,21,-157,22")

    config = smoke.load_smoke_config_from_env()
    target = config.target_dict()

    assert config.server_commit == "abc123"
    assert config.server_image == "ghcr.io/honua/server:staging"
    assert config.seed_profile == "sdk-smoke"
    assert config.ogc_collection_id == "parcels"
    assert config.stac_collection_id == "imagery"
    assert config.ogc_process_id == "buffer"
    assert config.ogc_process_payload == {"inputs": {"distance": 10}}
    assert config.protocol_bbox == (-158.0, 21.0, -157.0, 22.0)
    assert target["sdk_package_version"]
    assert target["server_commit"] == "abc123"
    assert target["protocol_bbox"] == [-158.0, 21.0, -157.0, 22.0]


def test_load_smoke_config_from_env_rejects_bad_protocol_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_BASE_URL", "https://staging.example.test")
    monkeypatch.setenv("HONUA_OGC_PROCESS_PAYLOAD_JSON", "[1, 2]")

    with pytest.raises(smoke.SmokeConfigError, match="must be a JSON object"):
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
    assert result.error["body_summary"] == '{"retry": true}'
    assert result.error["context"]["base_url"] == "https://staging.example.test"


def test_run_probe_can_skip_optional_unsupported_http_status() -> None:
    result = smoke.run_probe(
        "map_server_metadata",
        lambda: (_ for _ in ()).throw(HonuaHttpError(404, "not found", body={"detail": "missing"})),
        required=False,
        context={
            "protocol_surface": "GeoServices MapServer",
            "sdk_method": "HonuaClient.map_server(...).metadata",
            "request_path": "/rest/services/test_service/MapServer",
        },
        skip_http_statuses=smoke.OPTIONAL_PROTOCOL_SKIP_HTTP_STATUSES,
    )

    assert result.status == "skipped"
    assert result.error is None
    assert result.details["error"]["status_code"] == 404
    assert result.details["context"]["sdk_method"] == "HonuaClient.map_server(...).metadata"


def test_run_protocol_surface_smoke_records_public_sdk_probe_metadata() -> None:
    class FakeFeatureServer:
        def metadata(self) -> dict[str, object]:
            return {"name": "test_service", "currentVersion": 11.3}

        def layer_metadata(self, layer_id: int) -> dict[str, object]:
            assert layer_id == 0
            return {"id": 0, "name": "parcels"}

    class FakeMapServer:
        def metadata(self) -> dict[str, object]:
            return {"name": "test_service"}

        def export(self, bbox, *, size: tuple[int, int], image_format: str) -> bytes:
            assert list(bbox) == list(smoke.DEFAULT_PROTOCOL_BBOX)
            assert size == (256, 256)
            assert image_format == "png"
            return b"map"

        def identify(
            self,
            *,
            geometry: dict[str, float],
            map_extent,
            image_display: str,
            layers: str,
            return_geometry: bool,
        ) -> dict[str, object]:
            assert geometry == smoke.INITIAL_GEOMETRY
            assert list(map_extent) == list(smoke.DEFAULT_PROTOCOL_BBOX)
            assert image_display == smoke.DEFAULT_IMAGE_DISPLAY
            assert layers == "all:0"
            assert return_geometry is False
            return {"results": []}

    class FakeImageServer:
        def metadata(self) -> dict[str, object]:
            return {"name": "imagery"}

        def export_image(self, bbox, *, size: tuple[int, int], image_format: str) -> bytes:
            assert list(bbox) == list(smoke.DEFAULT_PROTOCOL_BBOX)
            assert size == (256, 256)
            assert image_format == "png"
            return b"image"

        def identify(self, geometry: dict[str, float]) -> dict[str, object]:
            assert geometry == smoke.INITIAL_GEOMETRY
            return {"value": 1}

    class FakeOgcFeatureCollection:
        def metadata(self) -> dict[str, object]:
            return {"id": "parcels"}

        def items(self, *, limit: int) -> dict[str, object]:
            assert limit == smoke.READ_QUERY_LIMIT
            return {"features": [{"id": "1"}]}

    class FakeOgcFeatures:
        def landing(self) -> dict[str, object]:
            return {"title": "Features"}

        def collections(self) -> dict[str, object]:
            return {"collections": [{"id": "parcels"}]}

        def collection(self, collection_id: str) -> FakeOgcFeatureCollection:
            assert collection_id == "parcels"
            return FakeOgcFeatureCollection()

    class FakeOgcMaps:
        def landing(self) -> dict[str, object]:
            return {"title": "Maps"}

        def collection_map(self, collection_id: str, *, bbox) -> bytes:
            assert collection_id == "parcels"
            assert list(bbox) == list(smoke.DEFAULT_PROTOCOL_BBOX)
            return b"map"

    class FakeOgcTiles:
        def collections(self) -> dict[str, object]:
            return {"collections": [{"id": "parcels"}]}

        def collection_tilesets(self, collection_id: str) -> dict[str, object]:
            assert collection_id == "parcels"
            return {"tilesets": [{"tileMatrixSetURI": "WebMercatorQuad"}]}

    class FakeOgcProcesses:
        def processes(self) -> dict[str, object]:
            return {"processes": [{"id": "buffer"}]}

    class FakeStac:
        def catalog(self) -> dict[str, object]:
            return {"type": "Catalog"}

        def collections(self) -> dict[str, object]:
            return {"collections": [{"id": "imagery"}]}

        def items(self, collection_id: str, *, extra_params: dict[str, int]) -> dict[str, object]:
            assert collection_id == "imagery"
            assert extra_params == {"limit": smoke.READ_QUERY_LIMIT}
            return {"features": [{"id": "scene-1"}]}

    class FakeOData:
        def service_document(self) -> dict[str, object]:
            return {"value": [{"name": "Layers"}]}

        def features(self, *, layer_id: int, extra_params: dict[str, int]) -> dict[str, object]:
            assert layer_id == 0
            assert extra_params == {"$top": smoke.READ_QUERY_LIMIT}
            return {"value": [{"ObjectId": 1}]}

    class FakeClient:
        def feature_server(self, service_id: str) -> FakeFeatureServer:
            assert service_id == "test_service"
            return FakeFeatureServer()

        def map_server(self, service_id: str) -> FakeMapServer:
            assert service_id == "test_service"
            return FakeMapServer()

        def image_server(self, service_id: str) -> FakeImageServer:
            assert service_id == "test_service"
            return FakeImageServer()

        def ogc_features(self) -> FakeOgcFeatures:
            return FakeOgcFeatures()

        def ogc_maps(self) -> FakeOgcMaps:
            return FakeOgcMaps()

        def ogc_tiles(self) -> FakeOgcTiles:
            return FakeOgcTiles()

        def ogc_processes(self) -> FakeOgcProcesses:
            return FakeOgcProcesses()

        def stac(self) -> FakeStac:
            return FakeStac()

        def odata(self) -> FakeOData:
            return FakeOData()

    config = smoke.SmokeConfig(
        base_url="https://staging.example.test",
        server_commit="abc123",
        server_image="ghcr.io/honua/server:staging",
        seed_profile="sdk-smoke",
        ogc_collection_id="parcels",
        stac_collection_id="imagery",
    )
    report = smoke.SmokeReport(config=config)

    results = smoke.run_protocol_surface_smoke(FakeClient(), config, report)
    by_name = {result.name: result for result in results}

    assert by_name["feature_server_metadata"].status == "passed"
    assert by_name["feature_server_metadata"].details["protocol_surface"] == "GeoServices FeatureServer"
    assert by_name["feature_server_metadata"].details["server_commit"] == "abc123"
    assert by_name["feature_server_metadata"].details["sdk_package_version"]
    assert by_name["ogc_features_collection_items"].details["collection_id"] == "parcels"
    assert by_name["stac_collection_items"].details["collection_id"] == "imagery"
    assert by_name["ogc_processes_execute"].status == "skipped"


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
                            "uid": "11111111-1111-1111-1111-111111111111",
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
    assert result["observed_fields"] == [
        "count",
        "name",
        "objectid",
        "ratio",
        "status",
        "uid",
    ]


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
    assert result["added_geometry"] == smoke.INITIAL_GEOMETRY
    assert result["updated_geometry"] == smoke.UPDATED_GEOMETRY
    assert result["cleanup"]["deleted_objectids"] == [1001]
    assert result["cleanup"]["remaining_feature_count"] == 0


def test_probe_apply_edits_roundtrip_rejects_geometry_drift(
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
                attributes = dict(adds[0]["attributes"])
                self.feature = {
                    "attributes": {
                        **attributes,
                        "objectid": 1001,
                    },
                    "geometry": dict(adds[0]["geometry"]),
                }
                return {"addResults": [{"success": True, "objectId": 1001}]}

            if updates is not None:
                attributes = dict(updates[0]["attributes"])
                self.feature = {
                    "attributes": dict(attributes),
                    "geometry": {
                        "x": smoke.UPDATED_GEOMETRY["x"] + 0.01,
                        "y": smoke.UPDATED_GEOMETRY["y"],
                    },
                }
                return {"updateResults": [{"success": True, "objectId": 1001}]}

            assert deletes == [1001]
            self.feature = None
            return {"deleteResults": [{"success": True, "objectId": 1001}]}

    with pytest.raises(AssertionError, match="Expected geometry x"):
        smoke.probe_apply_edits_roundtrip(
            FakeClient(),
            smoke.SmokeConfig(base_url="https://staging.example.test"),
        )


def test_probe_apply_edits_roundtrip_preserves_http_error_when_cleanup_also_fails() -> None:
    config = smoke.SmokeConfig(base_url="https://staging.example.test")

    class FakeClient:
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
            assert where.startswith("uid = '")
            assert out_fields == ["objectid", "uid"]
            assert return_geometry is False
            assert extra_params == {"resultRecordCount": smoke.WRITE_QUERY_LIMIT}
            raise HonuaHttpError(500, "cleanup denied", body={"stage": "cleanup"})

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
            assert adds is not None
            assert updates is None
            assert deletes is None
            raise HonuaHttpError(403, "write denied", body={"stage": "write"})

    result = smoke.run_probe(
        "apply_edits_roundtrip",
        lambda: smoke.probe_apply_edits_roundtrip(FakeClient(), config),
        context=config.target_dict(),
    )

    assert result.status == "failed"
    assert result.error is not None
    assert result.error["type"] == "HonuaHttpError"
    assert result.error["message"] == "write denied"
    assert result.error["status_code"] == 403
    assert result.error["body"] == {"stage": "write"}
    assert result.error["context"]["cleanup_error"] == {
        "type": "HonuaHttpError",
        "message": "cleanup denied",
        "status_code": 500,
        "body": {"stage": "cleanup"},
        "body_summary": '{"stage": "cleanup"}',
    }


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
