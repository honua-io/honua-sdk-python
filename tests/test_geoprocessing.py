from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import (
    AsyncHonuaClient,
    GeoprocessingJob,
    GeoprocessingJobError,
    HonuaClient,
    LayerReference,
)
from honua_sdk.geoprocessing import LAYER_SCOPE_PROCESS_IDS, TERMINAL_JOB_STATUSES


@pytest.fixture
def anyio_backend():
    return "asyncio"


FEATURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"name": "a"},
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
        }
    ],
}


def _layer_handler(seen: list[dict[str, Any]], *, fail: bool = False):
    """A mock transport that emulates submit -> poll(accepted->running->terminal) -> results."""
    state = {"polls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        entry: dict[str, Any] = {"method": request.method, "path": raw_path}
        if request.content:
            entry["body"] = json.loads(request.content.decode("utf-8"))
        entry["prefer"] = request.headers.get("Prefer")
        seen.append(entry)

        if raw_path.endswith("/execution"):
            return httpx.Response(201, json={"jobID": "job-1", "status": "accepted", "processID": "p"})
        if raw_path.endswith("/results"):
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [], "featureCount": 0})
        if "/jobs/" in raw_path:
            state["polls"] += 1
            if state["polls"] == 1:
                return httpx.Response(200, json={"jobID": "job-1", "status": "running", "progress": 40})
            terminal = "failed" if fail else "successful"
            return httpx.Response(
                200, json={"jobID": "job-1", "status": terminal, "progress": 100, "message": "done"}
            )
        return httpx.Response(200, json={"ok": True})

    return handler


def test_layer_scope_process_ids_are_the_four_server_processes() -> None:
    assert LAYER_SCOPE_PROCESS_IDS == frozenset(
        {
            "generalization.simplify-layer",
            "conversion.feature-project",
            "geometry.make-valid",
            "geometry.difference",
        }
    )
    assert TERMINAL_JOB_STATUSES == frozenset({"successful", "failed", "dismissed"})


def test_layer_reference_to_inputs_for_each_kind() -> None:
    inline = LayerReference.from_geojson(FEATURE_COLLECTION).to_inputs()
    assert json.loads(inline["inputGeoJson"]) == FEATURE_COLLECTION

    catalog = LayerReference.from_layer("roads", where="STATUS='OPEN'").to_inputs()
    assert catalog == {"layerId": "roads", "where": "STATUS='OPEN'"}

    query = LayerReference.from_query_result("qr-7").to_inputs()
    assert query == {"queryResultId": "qr-7"}


def test_processes_and_describe_build_expected_paths() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"method": request.method, "path": request.url.raw_path.decode("ascii").split("?")[0]})
        return httpx.Response(200, json={"ok": True})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        gp = client.geoprocessing()
        assert gp.processes()["ok"] is True
        assert gp.describe("geometry.make-valid")["ok"] is True

    assert [(e["method"], e["path"]) for e in seen] == [
        ("GET", "/ogc/processes/processes"),
        ("GET", "/ogc/processes/processes/geometry.make-valid"),
    ]


def test_execute_layer_submits_polls_to_terminal_and_returns_output_layer() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_layer_handler(seen))

    with HonuaClient("http://example.test", transport=transport) as client:
        result = client.geoprocessing().execute_layer(
            "generalization.simplify-layer",
            LayerReference.from_layer("roads", where="kind='primary'"),
            parameters={"tolerance": 10, "preserveTopology": True},
            poll_interval=0.0,
        )

    assert result["type"] == "FeatureCollection"
    paths = [(e["method"], e["path"]) for e in seen]
    assert paths == [
        ("POST", "/ogc/processes/processes/generalization.simplify-layer/execution"),
        ("GET", "/ogc/processes/jobs/job-1"),
        ("GET", "/ogc/processes/jobs/job-1"),
        ("GET", "/ogc/processes/jobs/job-1/results"),
    ]
    submit = seen[0]
    assert submit["prefer"] == "respond-async"
    assert submit["body"]["inputs"] == {
        "layerId": "roads",
        "where": "kind='primary'",
        "tolerance": "10",
        "preserveTopology": "true",
    }
    assert submit["body"]["response"] == "document"


def test_execute_layer_with_inline_geojson_serializes_feature_collection() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_layer_handler(seen))

    with HonuaClient("http://example.test", transport=transport) as client:
        client.geoprocessing().execute_layer(
            "geometry.make-valid",
            LayerReference.from_geojson(FEATURE_COLLECTION),
            poll_interval=0.0,
        )

    inline = seen[0]["body"]["inputs"]["inputGeoJson"]
    assert json.loads(inline) == FEATURE_COLLECTION


def test_execute_layer_raises_on_failed_job() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_layer_handler(seen, fail=True))

    with HonuaClient("http://example.test", transport=transport) as client:
        with pytest.raises(GeoprocessingJobError) as exc_info:
            client.geoprocessing().execute_layer(
                "geometry.make-valid",
                LayerReference.from_layer("roads"),
                poll_interval=0.0,
            )

    assert exc_info.value.job.status == "failed"
    assert exc_info.value.job.job_id == "job-1"


def test_submit_layer_returns_pending_job_without_polling() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_layer_handler(seen))

    with HonuaClient("http://example.test", transport=transport) as client:
        job = client.geoprocessing().submit_layer(
            "geometry.difference",
            LayerReference.from_layer("parcels"),
            parameters={"regionWkt": "POLYGON((0 0,1 0,1 1,0 1,0 0))"},
        )

    assert isinstance(job, GeoprocessingJob)
    assert job.status == "accepted"
    assert not job.is_terminal
    # Only the submit happened; no poll.
    assert [e["path"] for e in seen] == ["/ogc/processes/processes/geometry.difference/execution"]
    assert seen[0]["body"]["inputs"]["regionWkt"] == "POLYGON((0 0,1 0,1 1,0 1,0 0))"


def test_execute_geometry_primitive_path_posts_inputs_only() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        seen.append({"path": request.url.raw_path.decode("ascii").split("?")[0], "body": body})
        return httpx.Response(201, json={"jobID": "g-1", "status": "successful"})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        job = client.geoprocessing().execute_geometry(
            "geometry.buffer", {"geometry": "AAA=", "srid": 4326, "distance": 5}
        )

    assert job.succeeded
    assert seen[0]["path"] == "/ogc/processes/processes/geometry.buffer/execution"
    assert seen[0]["body"]["inputs"] == {"geometry": "AAA=", "srid": 4326, "distance": 5}


def test_wait_times_out_when_job_never_terminal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobID": "stuck", "status": "running"})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TimeoutError):
            client.geoprocessing().wait("stuck", poll_interval=0.0, timeout=0.05)


def test_dismiss_issues_delete() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"method": request.method, "path": request.url.raw_path.decode("ascii").split("?")[0]})
        return httpx.Response(204)

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        client.geoprocessing().dismiss("job-9")

    assert seen == [{"method": "DELETE", "path": "/ogc/processes/jobs/job-9"}]


def test_execute_layer_dataframe_roundtrips_through_geopandas() -> None:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append({"path": raw_path, "body": json.loads(request.content) if request.content else None})
        if raw_path.endswith("/execution"):
            return httpx.Response(201, json={"jobID": "df-1", "status": "successful"})
        if raw_path.endswith("/results"):
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "a"},
                            "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"jobID": "df-1", "status": "successful"})

    gdf = gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(1.0, 2.0)], crs="EPSG:4326")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        out = client.geoprocessing().execute_layer_dataframe(
            "geometry.make-valid", gdf, poll_interval=0.0
        )

    assert list(out["name"]) == ["a"]
    # The submitted inline GeoJSON carried the input feature.
    submit_body = seen[0]["body"]
    inline = json.loads(submit_body["inputs"]["inputGeoJson"])
    assert inline["features"][0]["geometry"] == {"type": "Point", "coordinates": [1.0, 2.0]}


pytestmark = pytest.mark.anyio


async def test_async_execute_layer_submits_polls_and_returns_results() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_layer_handler(seen))

    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        result = await client.geoprocessing().execute_layer(
            "conversion.feature-project",
            LayerReference.from_layer("roads"),
            parameters={"targetSrid": 3857},
            poll_interval=0.0,
        )

    assert result["type"] == "FeatureCollection"
    assert [(e["method"], e["path"]) for e in seen] == [
        ("POST", "/ogc/processes/processes/conversion.feature-project/execution"),
        ("GET", "/ogc/processes/jobs/job-1"),
        ("GET", "/ogc/processes/jobs/job-1"),
        ("GET", "/ogc/processes/jobs/job-1/results"),
    ]
    assert seen[0]["body"]["inputs"] == {"layerId": "roads", "targetSrid": "3857"}


async def test_async_processes_discovery() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"processes": []})

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        assert (await client.geoprocessing().processes())["processes"] == []
