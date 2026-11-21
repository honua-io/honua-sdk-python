"""Regression tests for honua-gp geoprocessing tool contracts and cursor validation (GP-P0-4 and GP-P1-9)."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

import honua_gp
from honua_gp._process_tools import _parse_search_radius
from honua_gp._resolve import resolve_layer_id
from honua_gp._session import HonuaSession


class _FakeProcessesClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, process_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((process_id, payload))
        return {"processID": process_id, "jobID": "job-1", "status": "accepted"}

    def job(self, job_id: str) -> dict[str, Any]:
        return {"jobID": job_id, "status": "successful"}

    def job_results(self, job_id: str) -> dict[str, Any]:
        return {
            "outputFeatureLayer": {
                "mediaType": "application/geo+json",
                "value": {
                    "type": "FeatureCollection",
                    "featureCount": 1,
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                            "properties": {},
                        }
                    ],
                },
            }
        }

    def dismiss_job(self, job_id: str) -> None:
        return None


class _FakeRasterClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def ogc_processes(self) -> "_FakeRasterClient":
        return self

    def execute(self, process_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((process_id, payload))
        return {"processID": process_id, "jobID": "job-1", "status": "accepted"}

    def job(self, job_id: str) -> dict[str, Any]:
        return {"jobID": job_id, "status": "successful"}

    def job_results(self, job_id: str) -> dict[str, Any]:
        return {"out": {"kind": "Raster", "value": "data:image/tiff;base64,AAAA"}}

    def dismiss_job(self, job_id: str) -> None:
        return None


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    import honua_gp._process_jobs as jobs

    monkeypatch.setattr(jobs.time, "sleep", lambda _s: None)


# GP-P0-4: SpatialJoin CONTAINS / WITHIN predicate semantics + CLOSEST rejection


@pytest.mark.parametrize(
    ("match_option", "expected_predicate"),
    [
        ("INTERSECT", "intersects"),
        ("CONTAINS", "within"),
        ("WITHIN", "contains"),
    ],
)
def test_spatial_join_predicate_matches_server_join_subject_semantics(
    _isolated_audit_dir: Path, match_option: str, expected_predicate: str
) -> None:
    proc = _FakeProcessesClient()
    honua_gp.configure(processes_client=proc)
    honua_gp.env.overwriteOutput = True

    honua_gp.analysis.SpatialJoin(
        "honua://services/target/1",
        "honua://services/join/2",
        "out",
        match_option=match_option,
    )

    assert proc.calls[0][0] == "analytics.spatial-join"
    assert proc.calls[0][1]["inputs"]["predicate"] == expected_predicate


def test_spatial_join_rejects_closest_match_option(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    honua_gp.configure(processes_client=proc)

    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.analysis.SpatialJoin(
            "honua://services/target/1",
            "honua://services/join/2",
            "out",
            match_option="CLOSEST",
            search_radius="100 Meters",
        )
    assert proc.calls == []


# GP-P1-9: _parse_search_radius unit conversions to meters


@pytest.mark.parametrize(
    ("raw", "expected_meters"),
    [
        (25, 25.0),
        (12.5, 12.5),
        ("100 Meters", 100.0),
        ("2 Kilometers", 2000.0),
        ("100 Feet", 30.48),
        ("100 Foot_US", 100.0 * 1200.0 / 3937.0),
        ("100 SurveyFeet", 100.0 * 1200.0 / 3937.0),
        ("100 Survey Feet", 100.0 * 1200.0 / 3937.0),
        ("1 Mile", 1609.344),
        ("2 Miles", 3218.688),
        ("1 NauticalMiles", 1852.0),
        ("2 Nautical Miles", 3704.0),
        ("10 Yards", 9.144),
    ],
)
def test_parse_search_radius_converts_units_to_meters(raw: Any, expected_meters: float) -> None:
    assert _parse_search_radius(raw) == pytest.approx(expected_meters)


def test_spatial_join_converts_search_radius_miles_to_meters(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    honua_gp.configure(processes_client=proc)
    honua_gp.env.overwriteOutput = True

    honua_gp.analysis.SpatialJoin(
        "honua://services/fac/0",
        "honua://services/parcels/1",
        "out",
        match_option="WITHIN_A_DISTANCE",
        search_radius="1 Mile",
    )

    inputs = proc.calls[0][1]["inputs"]
    assert inputs["predicate"] == "dwithin"
    assert inputs["distance"] == pytest.approx(1609.344)


@pytest.mark.parametrize("bad_radius", ["10 Parsecs", "-5 Meters", True, ""])
def test_parse_search_radius_rejects_invalid_values(bad_radius: Any) -> None:
    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        _parse_search_radius(bad_radius)


# GP-P1-9: da.UpdateCursor / InsertCursor OID field resolution & apply_edits error checking


def test_da_cursors_use_layer_object_id_field_name_from_schema() -> None:
    from honua_sdk.models import LayerSchema

    captured_query: dict[str, Any] = {}
    captured_edits: list[dict[str, Any]] = []

    class _CustomOidSource:
        def schema(self) -> LayerSchema:
            return LayerSchema.from_metadata(
                {
                    "id": 0,
                    "name": "Custom",
                    "objectIdField": "fid_pk",
                    "fields": [{"name": "fid_pk", "type": "esriFieldTypeOID"}],
                }
            )

        def iter_features(self, **kwargs: Any) -> Any:
            captured_query.update(kwargs)
            return iter([{"attributes": {"fid_pk": 42, "STATUS": "OPEN"}}])

        def apply_edits(self, **kwargs: Any) -> dict[str, Any]:
            captured_edits.append(dict(kwargs))
            return {
                "addResults": [{"objectId": 43, "success": True}],
                "updateResults": [{"objectId": 42, "success": True}],
            }

    class _CustomOidClient:
        def source(self, descriptor: Any) -> Any:
            return _CustomOidSource()

    honua_gp.configure(client=_CustomOidClient())

    with honua_gp.da.UpdateCursor("honua://services/custom/0", ["OID@", "STATUS"]) as cursor:
        row = next(cursor)
        assert row == [42, "OPEN"]
        row[1] = "CLOSED"
        cursor.updateRow(row)

    assert captured_query["out_fields"] == ("fid_pk", "STATUS")
    assert captured_edits[0]["updates"][0]["attributes"]["fid_pk"] == 42
    assert "OBJECTID" not in captured_edits[0]["updates"][0]["attributes"]

    with honua_gp.da.InsertCursor("honua://services/custom/0", ["OID@", "STATUS"]) as cursor:
        cursor.insertRow([99, "NEW"])

    assert captured_edits[1]["adds"][0]["attributes"]["fid_pk"] == 99
    assert "OBJECTID" not in captured_edits[1]["adds"][0]["attributes"]


def test_da_update_cursor_raises_on_failed_update_or_delete_results() -> None:
    class _FailingEditSource:
        def iter_features(self, **_: Any) -> Any:
            return iter([{"attributes": {"OBJECTID": 7, "STATUS": "OPEN"}}])

        def apply_edits(self, **_: Any) -> dict[str, Any]:
            return {
                "updateResults": [
                    {
                        "objectId": 7,
                        "success": False,
                        "error": {"code": 1001, "description": "row locked"},
                    }
                ]
            }

    class _Client:
        def source(self, descriptor: Any) -> Any:
            return _FailingEditSource()

    honua_gp.configure(client=_Client())

    with pytest.raises(honua_gp.ExecuteError, match="row locked") as exc_info:
        with honua_gp.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
            row = next(cursor)
            row[1] = "CLOSED"
            cursor.updateRow(row)
    assert exc_info.value.error_kind == "apply_edits_failed"


def test_da_insert_cursor_raises_on_failed_add_results() -> None:
    class _FailingAddSource:
        def apply_edits(self, **_: Any) -> dict[str, Any]:
            return {
                "addResults": [
                    {
                        "success": False,
                        "error": {"code": 1000, "description": "constraint failed"},
                    }
                ]
            }

    class _Client:
        def source(self, descriptor: Any) -> Any:
            return _FailingAddSource()

    honua_gp.configure(client=_Client())

    with pytest.raises(honua_gp.ExecuteError, match="constraint failed") as exc_info:
        with honua_gp.da.InsertCursor("roads", ["STATUS"]) as cursor:
            cursor.insertRow(["OPEN"])
    assert exc_info.value.error_kind == "apply_edits_failed"


# GP-P1-9: RasterCalculator single-raster support


def test_raster_calculator_accepts_single_raster(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    honua_gp.configure(client=client)

    honua_gp.sa.RasterCalculator("A * 2.0", [b"single-dem"])

    step = client.calls[0][1]["inputs"]["plan"]["steps"][0]
    assert step["processId"] == "raster.map-algebra"
    assert step["inputs"]["expression"] == "A * 2.0"
    assert step["inputs"]["sources"] == base64.b64encode(b"single-dem").decode()


def test_raster_calculator_rejects_empty_list(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    honua_gp.configure(client=client)

    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.sa.RasterCalculator("A * 2.0", [])
    assert client.calls == []


def test_mosaic_still_requires_two_rasters(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    honua_gp.configure(client=client)

    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.sa.Mosaic([b"only-one"])
    assert client.calls == []


# GP-P1-9: HonuaSession redacts credentials in repr


def test_honua_session_repr_hides_credentials() -> None:
    session = HonuaSession(
        base_url="https://honua.example.test",
        api_key="super-secret-api-key",
        bearer_token="super-secret-bearer-token",
    )
    rendered = repr(session)
    assert "super-secret-api-key" not in rendered
    assert "super-secret-bearer-token" not in rendered
    assert "honua.example.test" in rendered


# GP-P1-9: _resolve.py rejects unresolved bare layer names instead of layerId=0


def test_resolve_layer_id_rejects_unresolved_bare_names() -> None:
    with pytest.raises(honua_gp.HonuaGpResolveError):
        resolve_layer_id("roads")
    with pytest.raises(honua_gp.HonuaGpResolveError):
        resolve_layer_id("parcels")


def test_spatial_join_rejects_bare_unresolved_layer_names(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    honua_gp.configure(processes_client=proc)

    with pytest.raises(honua_gp.HonuaGpResolveError):
        honua_gp.analysis.SpatialJoin("roads", "parcels", "joined")
    assert proc.calls == []


def test_resolve_layer_id_accepts_int_numeric_str_and_service_layer_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert resolve_layer_id(4) == 4
    assert resolve_layer_id("7") == 7
    assert resolve_layer_id("transport/3") == 3
    assert resolve_layer_id("honua://services/transport/5") == 5
    monkeypatch.setenv("HONUA_GP_PATH_MAP", '{"roads": "honua://services/transport/2"}')
    assert resolve_layer_id("roads") == 2
