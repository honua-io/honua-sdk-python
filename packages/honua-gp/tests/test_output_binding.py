"""honua-sdk-python#226: a GP tool's output binds to the job's real result.

honua-server returns a layer-aware tool's FeatureLayer output by value in the
job results document (``outputFeatureLayer.value``); nothing is persisted as a
server layer. These tests answer with that document shape and pair it with a
Source client whose workspace layer 0 holds a *different* dataset (five line
segments), so any fallback to layer 0 or to the input shows up as the wrong
count or geometry. The live-server counterpart is
``test_output_binding_live.py``.
"""

from __future__ import annotations

import base64
import json
import struct
from pathlib import Path
from typing import Any

import pytest

import honua_gp

INPUT = "honua://services/roads/0"

# Workspace layer 0 / the input: five segments.
INPUT_FEATURES = [
    {"attributes": {"OBJECTID": i, "name": f"segment-{i}"}, "geometry": {"paths": [[[i, 0], [i, 1]]]}}
    for i in range(1, 6)
]
# Authored independently of the implementation: buffering the segments into
# two groups, then dissolving everything into one polygon.
BUFFER_FEATURES = [
    {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[0, -1], [3, -1], [3, 2], [0, 2], [0, -1]]]},
        "properties": {"COUNT": 3},
    },
    {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[3, -1], [6, -1], [6, 2], [3, 2], [3, -1]]]},
        "properties": {"COUNT": 2},
    },
]
DISSOLVE_FEATURES = [
    {
        "type": "Feature",
        "geometry": {"type": "MultiPolygon", "coordinates": [[[[0, -1], [6, -1], [6, 2], [0, 2], [0, -1]]]]},
        "properties": {"COUNT": 5},
    },
]
PROJECT_FEATURES = [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(i), 0.0]}, "properties": {"objectid": i}}
    for i in range(1, 4)
]


def _feature_layer(features: list[dict[str, Any]], *, feature_count: int | None = None) -> dict[str, Any]:
    return {
        "outputFeatureLayer": {
            "mediaType": "application/geo+json",
            "value": {
                "type": "FeatureCollection",
                "featureCount": len(features) if feature_count is None else feature_count,
                "features": features,
            },
        }
    }


class _ResultsGoneError(Exception):
    """Stands in for the HTTP 410 a results fetch gets once job results expire."""

    status_code = 410


class _QueryResult:
    def __init__(self, features: list[dict[str, Any]]) -> None:
        self.features = features
        self.total_count = None


class _LayerZeroSource:
    def __init__(self, features: list[dict[str, Any]]) -> None:
        self._features = features

    def query(self, where: str | None = None, **_: Any) -> _QueryResult:
        return _QueryResult(list(self._features))

    def iter_features(self, **_: Any):
        yield from self._features


class _LayerZeroClient:
    """Every server read lands here and is recorded; it only knows the input dataset."""

    def __init__(self) -> None:
        self.descriptors: list[dict[str, Any]] = []

    def source(self, descriptor: dict[str, Any]) -> _LayerZeroSource:
        self.descriptors.append(descriptor)
        return _LayerZeroSource(INPUT_FEATURES)


class _ScriptedProcesses:
    """Job N (1-based) follows ``outcomes[N-1]``: ``(status, results_document)``.

    ``status`` is a terminal OGC status, or ``"expired"`` for a job that
    succeeded but whose results are gone by the time they are fetched.
    """

    def __init__(self, *outcomes: tuple[str, Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _outcome(self, job_id: str) -> tuple[str, Any]:
        return self._outcomes[int(job_id.rsplit("-", 1)[1]) - 1]

    def execute(self, process_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((process_id, payload))
        return {"jobID": f"job-{len(self.calls)}", "status": "accepted"}

    def job(self, job_id: str) -> dict[str, Any]:
        status, _ = self._outcome(job_id)
        status = "successful" if status == "expired" else status
        return {"jobID": job_id, "status": status, "message": "boom" if status == "failed" else None}

    def job_results(self, job_id: str) -> Any:
        status, document = self._outcome(job_id)
        if status == "expired":
            raise _ResultsGoneError(f"results for {job_id} are no longer available (HTTP 410)")
        return document

    def dismiss_job(self, job_id: str) -> None:
        return None


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    import honua_gp._process_jobs as jobs

    monkeypatch.setattr(jobs.time, "sleep", lambda _seconds: None)


def _configure(*outcomes: tuple[str, Any]) -> tuple[_LayerZeroClient, _ScriptedProcesses]:
    client = _LayerZeroClient()
    processes = _ScriptedProcesses(*outcomes)
    honua_gp.configure(client=client, processes_client=processes)
    honua_gp.env.workspace = "honua://services/roads"
    honua_gp.env.overwriteOutput = True
    return client, processes


def _rows(name: str, fields: list[str]) -> list[tuple[Any, ...]]:
    with honua_gp.da.SearchCursor(name, fields) as cursor:
        return list(cursor)


def test_buffer_output_getcount_searchcursor_then_dissolve(_isolated_audit_dir: Path) -> None:
    client, processes = _configure(
        ("successful", _feature_layer(BUFFER_FEATURES)),
        ("successful", _feature_layer(DISSOLVE_FEATURES)),
    )

    assert honua_gp.management.GetCount(INPUT) == 5

    result = honua_gp.analysis.Buffer(INPUT, "roads_buffer", "50 Meters")
    assert str(result) == "roads_buffer"
    assert result[0] == "roads_buffer"
    assert result.getOutput(0) == "roads_buffer"
    alias = honua_gp.get_session().get_layer("roads_buffer")
    assert alias is not None
    assert alias.kind == "gp-output"
    assert alias.output is not None
    assert alias.output.job_id == "job-1"

    assert honua_gp.management.GetCount("roads_buffer") == 2
    assert honua_gp.management.GetCount(result[0]) == 2
    rows = _rows("roads_buffer", ["SHAPE@JSON", "COUNT"])
    assert [json.loads(row[0]) for row in rows] == [feature["geometry"] for feature in BUFFER_FEATURES]
    assert [row[1] for row in rows] == [3, 2]

    honua_gp.management.MakeFeatureLayer("roads_buffer", "buffer_lyr")
    assert honua_gp.management.GetCount("buffer_lyr") == 2

    dissolved = honua_gp.management.Dissolve(INPUT, "roads_dissolved")
    assert processes.calls[1][1]["inputs"]["layerId"] == 0
    assert honua_gp.management.GetCount(dissolved[0]) == 1
    [(geometry, count)] = _rows("roads_dissolved", ["SHAPE@JSON", "COUNT"])
    assert json.loads(geometry) == DISSOLVE_FEATURES[0]["geometry"]
    assert count == 5

    # The only server reads were the two explicit reads of the input.
    assert [descriptor["id"] for descriptor in client.descriptors] == [INPUT]
    assert [call[0] for call in processes.calls] == ["analytics.buffer-aggregate", "generalization.dissolve"]


def _decode_wkb_polygon(encoded: str) -> dict[str, Any]:
    """Read a little-endian 2D WKB Polygon back into GeoJSON (test oracle)."""

    raw = base64.b64decode(encoded)
    byte_order, geometry_type, ring_count = struct.unpack_from("<BII", raw, 0)
    assert (byte_order, geometry_type) == (1, 3)
    offset, rings = 9, []
    for _ in range(ring_count):
        (point_count,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        ring = [list(struct.unpack_from("<dd", raw, offset + 16 * i)) for i in range(point_count)]
        offset += 16 * point_count
        rings.append(ring)
    assert offset == len(raw)
    return {"type": "Polygon", "coordinates": rings}


def _dissolve_result(groups: list[tuple[str, dict[str, Any]]], *, input_count: int, srid: int) -> dict[str, Any]:
    """``geometry.dissolve``'s results document (GeometryDissolveJobExecutor)."""

    return {
        "outputFeatureLayer": {
            "mediaType": "application/geo+json",
            "value": {
                "type": "FeatureCollection",
                "processId": "geometry.dissolve",
                "inputSrid": srid,
                "inputCount": input_count,
                "groupCount": len(groups),
                "features": [
                    {
                        "type": "Feature",
                        "geometry": geometry,
                        "properties": {"processId": "geometry.dissolve", "groupKey": key, "inputSrid": srid},
                    }
                    for key, geometry in groups
                ],
            },
        }
    }


class _Schema:
    def __init__(self, srid: int | None) -> None:
        self.srid = srid


class _FeatureServer:
    def __init__(self, calls: list[tuple[str, int]], service_id: str, srid: int | None) -> None:
        self._calls = calls
        self._service_id = service_id
        self._srid = srid

    def schema(self, layer_id: int) -> _Schema:
        self._calls.append((self._service_id, layer_id))
        return _Schema(self._srid)


class _LayerClient(_LayerZeroClient):
    """``_LayerZeroClient`` plus FeatureServer layer metadata in ``srid``."""

    def __init__(self, srid: int | None = 3857) -> None:
        super().__init__()
        self.srid = srid
        self.schema_calls: list[tuple[str, int]] = []

    def feature_server(self, service_id: str) -> _FeatureServer:
        return _FeatureServer(self.schema_calls, service_id, self.srid)


def _configure_layers(*outcomes: tuple[str, Any], srid: int | None = 3857) -> tuple[_LayerClient, _ScriptedProcesses]:
    client = _LayerClient(srid)
    processes = _ScriptedProcesses(*outcomes)
    honua_gp.configure(client=client, processes_client=processes)
    honua_gp.env.workspace = "honua://services/roads"
    honua_gp.env.overwriteOutput = True
    return client, processes


def test_buffer_output_chains_into_dissolve_via_geometry_dissolve(_isolated_audit_dir: Path) -> None:
    client, processes = _configure_layers(
        ("successful", _feature_layer(BUFFER_FEATURES)),
        ("successful", _dissolve_result([("__all__", DISSOLVE_FEATURES[0]["geometry"])], input_count=2, srid=3857)),
    )

    honua_gp.analysis.Buffer(INPUT, "roads_buffer", "50 Meters")
    assert honua_gp.management.GetCount("roads_buffer") == 2

    result = honua_gp.management.Dissolve("roads_buffer", "chained")

    assert str(result) == "chained"
    process_id, payload = processes.calls[1]
    assert process_id == "geometry.dissolve"
    # The buffer output carries no srid member, so it is in the input layer's CRS.
    assert client.schema_calls == [("roads", 0)]
    assert set(payload["inputs"]) == {"wkbs", "srid"}
    assert payload["inputs"]["srid"] == 3857
    assert [_decode_wkb_polygon(wkb) for wkb in json.loads(payload["inputs"]["wkbs"])] == [
        feature["geometry"] for feature in BUFFER_FEATURES
    ]

    # Two buffer polygons in, one dissolved polygon out -- never layer 0's five segments.
    assert honua_gp.management.GetCount("chained") == 1
    [(geometry, group_key)] = _rows("chained", ["SHAPE@JSON", "groupKey"])
    assert json.loads(geometry) == DISSOLVE_FEATURES[0]["geometry"]
    assert group_key == "__all__"
    chained = honua_gp.get_session().get_layer("chained")
    assert chained is not None
    assert chained.output is not None
    assert (chained.output.srid, chained.output.origin, chained.output.job_id) == (3857, INPUT, "job-2")
    assert client.descriptors == []

    # The audit line records the dispatched process and a placeholder, not the WKB.
    records = [
        json.loads(line)
        for file in sorted(_isolated_audit_dir.glob("audit-*.jsonl"))
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    dissolve_record = next(record for record in records if record.get("function") == "management.Dissolve")
    assert dissolve_record["process_id"] == "geometry.dissolve"
    assert dissolve_record["process_inputs"] == {"wkbs": "<base64 WKB geometries of the input result>", "srid": 3857}


def test_chained_dissolve_groups_by_dissolve_field_and_restores_the_values(_isolated_audit_dir: Path) -> None:
    zoned = [
        {**BUFFER_FEATURES[0], "properties": {"COUNT": 3, "zone": "north"}},
        {**BUFFER_FEATURES[1], "properties": {"COUNT": 2, "zone": "south"}},
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 2], [3, 2], [3, 4], [0, 4], [0, 2]]]},
            "properties": {"COUNT": 1, "zone": "north"},
        },
    ]
    north = {"type": "Polygon", "coordinates": [[[0, -1], [3, -1], [3, 4], [0, 4], [0, -1]]]}
    south = BUFFER_FEATURES[1]["geometry"]
    _client, processes = _configure_layers(
        ("successful", _feature_layer(zoned)),
        ("successful", _dissolve_result([('["north"]', north), ('["south"]', south)], input_count=3, srid=3857)),
    )
    honua_gp.analysis.Buffer(INPUT, "zones", "50 Meters")

    honua_gp.management.Dissolve("zones", "by_zone", "zone")

    inputs = processes.calls[1][1]["inputs"]
    assert json.loads(inputs["groupKeys"]) == ['["north"]', '["south"]', '["north"]']
    assert len(json.loads(inputs["wkbs"])) == 3
    rows = _rows("by_zone", ["zone", "SHAPE@JSON"])
    assert [(zone, json.loads(shape)) for zone, shape in rows] == [("north", north), ("south", south)]


def test_chained_dissolve_rejects_a_group_the_server_was_not_asked_for(_isolated_audit_dir: Path) -> None:
    zoned = [{**feature, "properties": {"zone": "north"}} for feature in BUFFER_FEATURES]
    _configure_layers(
        ("successful", _feature_layer(zoned)),
        ("successful", _dissolve_result([('["east"]', DISSOLVE_FEATURES[0]["geometry"])], input_count=2, srid=3857)),
    )
    honua_gp.analysis.Buffer(INPUT, "zones", "50 Meters")

    with pytest.raises(honua_gp.ExecuteError) as info:
        honua_gp.management.Dissolve("zones", "by_zone", "zone")

    assert info.value.error_kind == "unreadable_output"
    with pytest.raises(honua_gp.HonuaGpResolveError):
        honua_gp.management.GetCount("by_zone")


def test_chained_dissolve_uses_the_srid_the_output_declares(_isolated_audit_dir: Path) -> None:
    collection = _feature_layer(PROJECT_FEATURES)
    collection["outputFeatureLayer"]["value"]["srid"] = 3857
    client, processes = _configure_layers(
        ("successful", collection),
        ("successful", _dissolve_result([("__all__", {"type": "MultiPoint", "coordinates": [[1, 0], [2, 0], [3, 0]]})],
                                        input_count=3, srid=3857)),
        srid=4326,
    )
    honua_gp.management.Project(INPUT, "projected", 3857)

    honua_gp.management.Dissolve("projected", "points")

    assert processes.calls[1][1]["inputs"]["srid"] == 3857
    assert client.schema_calls == []
    assert honua_gp.management.GetCount("points") == 1


@pytest.mark.parametrize(
    ("features", "srid", "kwargs", "message"),
    [
        pytest.param([], 3857, {}, "empty GP job result", id="empty-output"),
        pytest.param(
            [{"type": "Feature", "geometry": None, "properties": {}}], 3857, {}, "null or empty geometry",
            id="null-geometry",
        ),
        pytest.param(
            [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}, "properties": {}}], 3857, {},
            "null or empty geometry", id="empty-geometry",
        ),
        pytest.param(
            [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2, 3, 4]}, "properties": {}}],
            3857, {}, "2D or all be 3D", id="measured-geometry",
        ),
        pytest.param(BUFFER_FEATURES, None, {}, "spatial reference is unknown", id="unknown-srid"),
        pytest.param(BUFFER_FEATURES, 3857, {"dissolve_field": "zone"}, "not an attribute", id="missing-field"),
        pytest.param(BUFFER_FEATURES, 3857, {"where_clause": "COUNT > 2"}, "where_clause", id="where-clause"),
    ],
)
def test_chained_dissolve_refuses_what_geometry_dissolve_cannot_take(
    _isolated_audit_dir: Path, features: list[dict[str, Any]], srid: int | None, kwargs: dict[str, Any], message: str
) -> None:
    _client, processes = _configure_layers(("successful", _feature_layer(features)), srid=srid)
    honua_gp.analysis.Buffer(INPUT, "roads_buffer", "50 Meters")

    with pytest.raises(honua_gp.HonuaGpConfigurationError, match=message):
        honua_gp.management.Dissolve("roads_buffer", "chained", **kwargs)

    assert len(processes.calls) == 1
    with pytest.raises(honua_gp.HonuaGpResolveError):
        honua_gp.management.GetCount("chained")


def test_chained_dissolve_refuses_a_selection_on_the_output(_isolated_audit_dir: Path) -> None:
    _client, processes = _configure_layers(("successful", _feature_layer(BUFFER_FEATURES)))
    honua_gp.analysis.Buffer(INPUT, "roads_buffer", "50 Meters")
    honua_gp.management.MakeFeatureLayer("roads_buffer", "big", "COUNT > 2")

    with pytest.raises(honua_gp.HonuaGpConfigurationError, match="cannot filter"):
        honua_gp.management.Dissolve("big", "chained")

    assert len(processes.calls) == 1


class _SynchronousDissolve(_ScriptedProcesses):
    """Answers ``geometry.dissolve`` inline, as honua-server does without ``Prefer: respond-async``."""

    def execute(self, process_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if process_id != "geometry.dissolve":
            return super().execute(process_id, payload)
        self.calls.append((process_id, payload))
        return _dissolve_result([("__all__", DISSOLVE_FEATURES[0]["geometry"])], input_count=2, srid=3857)


def test_synchronous_execution_result_is_bound(_isolated_audit_dir: Path) -> None:
    client = _LayerClient()
    processes = _SynchronousDissolve(("successful", _feature_layer(BUFFER_FEATURES)))
    honua_gp.configure(client=client, processes_client=processes)
    honua_gp.env.workspace = "honua://services/roads"
    honua_gp.env.overwriteOutput = True
    honua_gp.analysis.Buffer(INPUT, "roads_buffer", "50 Meters")

    result = honua_gp.management.Dissolve("roads_buffer", "chained")

    assert result.job_id == ""
    alias = honua_gp.get_session().get_layer("chained")
    assert alias is not None
    assert alias.output is not None
    assert alias.output.job_id.startswith("inline-")
    assert honua_gp.management.GetCount("chained") == 1


def test_empty_output_binds_as_zero_features(_isolated_audit_dir: Path) -> None:
    _configure(("successful", _feature_layer([])))

    honua_gp.analysis.Buffer(INPUT, "nothing", "5 Meters")

    assert honua_gp.management.GetCount("nothing") == 0
    assert _rows("nothing", ["SHAPE@JSON"]) == []


def test_geojson_data_uri_output_is_bound(_isolated_audit_dir: Path) -> None:
    collection = {"type": "FeatureCollection", "features": PROJECT_FEATURES}
    href = "data:application/geo+json;base64," + base64.b64encode(json.dumps(collection).encode()).decode()
    _configure(("successful", {"outputFeatureLayer": {"href": href}}))

    honua_gp.management.Project(INPUT, "projected", 3857)

    assert honua_gp.management.GetCount("projected") == 3
    assert [row[0] for row in _rows("projected", ["objectid"])] == [1, 2, 3]


@pytest.mark.parametrize(
    ("document", "error_kind"),
    [
        pytest.param({}, "missing_output", id="empty-document"),
        pytest.param(None, "missing_output", id="no-results-body"),
        pytest.param({"jobID": "job-1", "outputs": {}}, "missing_output", id="empty-outputs"),
        pytest.param({"outputTable": {"value": {"rows": []}}}, "missing_output", id="no-feature-layer"),
        pytest.param({"outputFeatureLayer": {"mediaType": "application/geo+json"}}, "missing_output", id="no-value"),
        pytest.param(
            {"outputFeatureLayer": {"href": "https://honua.example.com/jobs/job-1/results/outputFeatureLayer"}},
            "unreadable_output",
            id="by-reference-href",
        ),
        pytest.param({"outputFeatureLayer": {"value": {"type": "Feature"}}}, "unreadable_output", id="not-collection"),
        pytest.param(_feature_layer(BUFFER_FEATURES, feature_count=7), "unreadable_output", id="truncated"),
        pytest.param(
            {"outputFeatureLayer1": _feature_layer([])["outputFeatureLayer"],
             "outputFeatureLayer2": _feature_layer([])["outputFeatureLayer"]},
            "unreadable_output",
            id="ambiguous",
        ),
    ],
)
def test_missing_or_unreadable_output_is_a_typed_failure(
    _isolated_audit_dir: Path, document: Any, error_kind: str
) -> None:
    client, _processes = _configure(("successful", document))

    with pytest.raises(honua_gp.ExecuteError) as info:
        honua_gp.analysis.Buffer(INPUT, "out", "5 Meters")

    assert info.value.error_kind == error_kind
    assert honua_gp.get_session().get_layer("out") is None
    with pytest.raises(honua_gp.HonuaGpResolveError):
        honua_gp.management.GetCount("out")
    assert client.descriptors == []


@pytest.mark.parametrize(
    ("status", "error_kind"),
    [("failed", "failed"), ("dismissed", "dismissed"), ("expired", "missing_output")],
)
def test_failed_cancelled_or_expired_job_leaves_output_unresolvable(
    _isolated_audit_dir: Path, status: str, error_kind: str
) -> None:
    client, _processes = _configure((status, _feature_layer(BUFFER_FEATURES)))

    with pytest.raises(honua_gp.ExecuteError) as info:
        honua_gp.analysis.Buffer(INPUT, "roads_buffer", "50 Meters")

    assert info.value.error_kind == error_kind
    assert honua_gp.get_session().get_layer("roads_buffer") is None
    # Without the unbound marker this would count the workspace's layer 0 (5).
    with pytest.raises(honua_gp.HonuaGpResolveError):
        honua_gp.management.GetCount("roads_buffer")
    with pytest.raises(honua_gp.HonuaGpResolveError):
        honua_gp.management.MakeFeatureLayer("roads_buffer", "lyr")
    assert client.descriptors == []


def test_existing_output_survives_failed_and_cancelled_overwrites(_isolated_audit_dir: Path) -> None:
    _client, processes = _configure(
        ("successful", _feature_layer(PROJECT_FEATURES)),
        ("failed", None),
        ("dismissed", None),
    )
    honua_gp.management.Project(INPUT, "scratch", 3857)
    assert honua_gp.management.GetCount("scratch") == 3

    for expected_kind in ("failed", "dismissed"):
        with pytest.raises(honua_gp.ExecuteError) as info:
            honua_gp.analysis.Buffer(INPUT, "scratch", "5 Meters")
        assert info.value.error_kind == expected_kind
        alias = honua_gp.get_session().get_layer("scratch")
        assert alias is not None
        assert alias.output is not None
        assert alias.output.job_id == "job-1"
        assert honua_gp.management.GetCount("scratch") == 3

    honua_gp.env.overwriteOutput = False
    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.analysis.Buffer(INPUT, "scratch", "5 Meters")
    assert len(processes.calls) == 3


def test_operations_the_bound_output_cannot_honour_are_refused(_isolated_audit_dir: Path) -> None:
    client, processes = _configure(("successful", _feature_layer(BUFFER_FEATURES)))
    honua_gp.analysis.Buffer(INPUT, "roads_buffer", "50 Meters")

    with pytest.raises(honua_gp.ExecuteError) as where_info:
        _rows_with_where = honua_gp.da.SearchCursor("roads_buffer", ["COUNT"], "COUNT > 2")
        with _rows_with_where as cursor:
            list(cursor)
    assert where_info.value.error_kind == "unsupported_output_operation"

    with pytest.raises(honua_gp.ExecuteError) as sr_info:
        with honua_gp.da.SearchCursor("roads_buffer", ["COUNT"], spatial_reference=3857) as cursor:
            list(cursor)
    assert sr_info.value.error_kind == "unsupported_output_operation"

    with pytest.raises(honua_gp.ExecuteError):
        honua_gp.management.SelectLayerByAttribute("roads_buffer", "NEW_SELECTION", "COUNT > 2")
    assert honua_gp.get_session().get_layer("roads_buffer").where is None

    with pytest.raises(honua_gp.ExecuteError) as update_info:
        with honua_gp.da.UpdateCursor("roads_buffer", ["COUNT"]) as cursor:
            list(cursor)
    assert update_info.value.error_kind == "unsupported_output_operation"

    with pytest.raises(honua_gp.ExecuteError) as insert_info:
        with honua_gp.da.InsertCursor("roads_buffer", ["COUNT"]) as cursor:
            cursor.insertRow((1,))
    assert insert_info.value.error_kind == "unsupported_output_operation"

    with pytest.raises(honua_gp.HonuaGpResolveError):
        honua_gp.analysis.SpatialJoin(INPUT, "roads_buffer", "joined")

    assert client.descriptors == []
    assert len(processes.calls) == 1
