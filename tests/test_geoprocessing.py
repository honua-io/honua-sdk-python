"""Tests for the OGC API Processes geoprocessing clients.

Transport is mocked with :class:`httpx.MockTransport` (no live server/Docker),
mirroring the existing client tests. The wire shapes mirror the reconciled
honua-server OGC API Processes contract:

* ``POST /ogc/processes/processes/{id}/execution`` -> ``201`` + StatusInfo,
* ``GET /ogc/processes/jobs/{id}`` -> StatusInfo (polled to terminal),
* ``GET /ogc/processes/jobs/{id}/results`` -> document-mode outputs map.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import AsyncHonuaClient, HonuaClient
from honua_sdk.geoprocessing import (
    CANONICAL_PROCESS_ID,
    LAYER_SCOPE_PROCESS_IDS,
    AsyncHonuaGeoprocessing,
    GeoprocessingJob,
    GeoprocessingJobError,
    HonuaGeoprocessing,
    LayerReference,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROCESS_LIST = {
    "processes": [
        {"id": "honua-geoprocessing", "title": "Honua Geoprocessing", "version": "1.0.0"},
        {"id": "geometry.buffer", "title": "Buffer", "version": "1.0.0"},
    ],
    "links": [],
}

PROCESS_DESCRIPTION = {
    "id": "geometry.buffer",
    "title": "Buffer",
    "version": "1.0.0",
    "jobControlOptions": ["async-execute"],
    "inputs": {"inputGeoJson": {"title": "Input"}, "distance": {"title": "Distance"}},
    "outputs": {"outputFeatureLayer": {"title": "Output"}},
}

FEATURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"name": "a"},
            "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
        }
    ],
}

RESULTS_DOCUMENT = {
    "outputFeatureLayer": {
        "id": "artifact-1",
        "kind": "FeatureLayer",
        "href": "https://api.honua.test/artifacts/artifact-1",
        "type": "application/geo+json",
    }
}


def _status(job_id: str, status: str, *, process_id: str = "geometry.buffer") -> dict[str, Any]:
    return {"jobID": job_id, "status": status, "processID": process_id, "type": "process"}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_processes_and_describe() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/ogc/processes/processes":
            return httpx.Response(200, json=PROCESS_LIST)
        if request.url.path == "/ogc/processes/processes/geometry.buffer":
            return httpx.Response(200, json=PROCESS_DESCRIPTION)
        raise AssertionError(f"unexpected {request.url.path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        gp = client.geoprocessing()
        assert isinstance(gp, HonuaGeoprocessing)
        listing = gp.processes()
        described = gp.describe("geometry.buffer")

    assert {p["id"] for p in listing["processes"]} == {"honua-geoprocessing", "geometry.buffer"}
    assert described["id"] == "geometry.buffer"
    assert ("GET", "/ogc/processes/processes") in seen
    assert ("GET", "/ogc/processes/processes/geometry.buffer") in seen


# ---------------------------------------------------------------------------
# Layer-scope execute: submit -> poll -> results
# ---------------------------------------------------------------------------


def test_execute_layer_submit_poll_results() -> None:
    poll_count = {"n": 0}
    captured_body: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/ogc/processes/processes/geometry.buffer/execution":
            captured_body.update(json.loads(request.content))
            assert request.headers.get("Prefer") == "respond-async"
            return httpx.Response(
                201,
                json=_status("job-1", "accepted"),
                headers={"Location": "http://example.test/ogc/processes/jobs/job-1"},
            )
        if request.method == "GET" and path == "/ogc/processes/jobs/job-1":
            poll_count["n"] += 1
            status = "running" if poll_count["n"] < 2 else "successful"
            return httpx.Response(200, json=_status("job-1", status))
        if request.method == "GET" and path == "/ogc/processes/jobs/job-1/results":
            return httpx.Response(200, json=RESULTS_DOCUMENT)
        raise AssertionError(f"unexpected {request.method} {path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        gp = client.geoprocessing()
        layer = LayerReference.from_geojson(FEATURE_COLLECTION)
        result = gp.execute("geometry.buffer", layer, parameters={"distance": 100}, poll_interval=0.0)

    assert result == RESULTS_DOCUMENT
    # Inline GeoJSON is serialized into the inputGeoJson string input.
    assert "inputGeoJson" in captured_body["inputs"]
    assert json.loads(captured_body["inputs"]["inputGeoJson"]) == FEATURE_COLLECTION
    # Numeric parameters are stringified for the canonical input bag.
    assert captured_body["inputs"]["distance"] == "100"
    assert captured_body["response"] == "document"
    assert poll_count["n"] == 2


def test_submit_returns_pending_job() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=_status("job-2", "accepted"))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        job = client.geoprocessing().submit(
            "geometry.buffer", LayerReference.from_geojson(FEATURE_COLLECTION)
        )

    assert isinstance(job, GeoprocessingJob)
    assert job.job_id == "job-2"
    assert job.status == "accepted"
    assert not job.is_terminal


def test_query_result_reference_inputs() -> None:
    ref = LayerReference.from_query_result("qr-9", where="status = 'open'")
    inputs = ref.to_inputs()
    assert inputs == {"queryResultId": "qr-9", "where": "status = 'open'"}


def test_inline_geojson_reference_requires_collection() -> None:
    with pytest.raises(ValueError, match="inlineGeoJson"):
        LayerReference(kind="inlineGeoJson").to_inputs()


def test_query_result_reference_requires_id() -> None:
    with pytest.raises(ValueError, match="queryResult"):
        LayerReference(kind="queryResult").to_inputs()


# ---------------------------------------------------------------------------
# Single-geometry primitive
# ---------------------------------------------------------------------------


def test_execute_geometry_primitive() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/ogc/processes/processes/geometry.area/execution":
            captured.update(json.loads(request.content))
            return httpx.Response(201, json=_status("job-3", "accepted", process_id="geometry.area"))
        if path == "/ogc/processes/jobs/job-3":
            return httpx.Response(200, json=_status("job-3", "successful", process_id="geometry.area"))
        if path == "/ogc/processes/jobs/job-3/results":
            return httpx.Response(200, json={"outputScalar": 42.0})
        raise AssertionError(f"unexpected {path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        result = client.geoprocessing().execute_geometry(
            "geometry.area", {"geometry": "AAAA", "srid": "4326"}, poll_interval=0.0
        )

    assert result == {"outputScalar": 42.0}
    assert captured["inputs"] == {"geometry": "AAAA", "srid": "4326"}


# ---------------------------------------------------------------------------
# Canonical multi-step plan
# ---------------------------------------------------------------------------


def test_execute_plan_targets_canonical_process() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == f"/ogc/processes/processes/{CANONICAL_PROCESS_ID}/execution":
            captured.update(json.loads(request.content))
            return httpx.Response(201, json=_status("job-4", "accepted", process_id=CANONICAL_PROCESS_ID))
        if path == "/ogc/processes/jobs/job-4":
            return httpx.Response(200, json=_status("job-4", "successful", process_id=CANONICAL_PROCESS_ID))
        if path == "/ogc/processes/jobs/job-4/results":
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected {path}")

    plan = {
        "planId": "p-1",
        "steps": [
            {"stepId": "s1", "kind": "geoprocess", "processId": "geometry.buffer", "inputs": {"distance": "10"}},
        ],
    }

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        result = client.geoprocessing().execute_plan(plan, poll_interval=0.0)

    assert result == {}
    assert captured["inputs"]["plan"] == plan


# ---------------------------------------------------------------------------
# Error / lifecycle paths
# ---------------------------------------------------------------------------


def test_execute_raises_on_failed_job() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(201, json=_status("job-5", "accepted"))
        if path == "/ogc/processes/jobs/job-5":
            return httpx.Response(200, json={"jobID": "job-5", "status": "failed", "message": "boom"})
        raise AssertionError(f"unexpected {path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GeoprocessingJobError, match="boom") as exc:
            client.geoprocessing().execute(
                "geometry.buffer", LayerReference.from_geojson(FEATURE_COLLECTION), poll_interval=0.0
            )
    assert exc.value.job.status == "failed"


def test_execute_no_raise_returns_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(201, json=_status("job-6", "accepted"))
        if path == "/ogc/processes/jobs/job-6":
            return httpx.Response(200, json=_status("job-6", "failed"))
        if path == "/ogc/processes/jobs/job-6/results":
            return httpx.Response(200, json={"error": "partial"})
        raise AssertionError(f"unexpected {path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        result = client.geoprocessing().execute(
            "geometry.buffer",
            LayerReference.from_geojson(FEATURE_COLLECTION),
            poll_interval=0.0,
            raise_on_failure=False,
        )
    assert result == {"error": "partial"}


def test_wait_times_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_status("job-7", "running"))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        gp = client.geoprocessing()
        with pytest.raises(TimeoutError, match="terminal status"):
            gp.wait("job-7", poll_interval=0.0, timeout=0.0)


def test_jobs_and_dismiss() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/ogc/processes/jobs":
            return httpx.Response(200, json={"jobs": [_status("job-8", "running")]})
        if request.method == "DELETE":
            return httpx.Response(200, json=_status("job-8", "dismissed"))
        raise AssertionError(f"unexpected {request.url.path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        gp = client.geoprocessing()
        listing = gp.jobs()
        gp.dismiss("job-8")

    assert listing["jobs"][0]["jobID"] == "job-8"
    assert ("GET", "/ogc/processes/jobs") in seen
    assert ("DELETE", "/ogc/processes/jobs/job-8") in seen


def test_submit_raw_forwards_body_verbatim() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(201, json=_status("job-9", "accepted"))

    body = {"inputs": {"inputGeoJson": "{}"}, "outputs": {}, "metadata": {"x": "y"}}
    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        job = client.geoprocessing().submit_raw("geometry.buffer", body)

    assert job.job_id == "job-9"
    assert captured == body


def test_status_info_parsing_alternate_keys() -> None:
    job = GeoprocessingJob.from_status_info(
        {"jobId": "j", "status": "successful", "processId": "geometry.buffer", "progress": 100, "links": [{"rel": "self"}]}
    )
    assert job.job_id == "j"
    assert job.succeeded
    assert job.progress == 100
    assert job.links == ({"rel": "self"},)


def test_layer_scope_ids_constant() -> None:
    assert "geometry.buffer" in LAYER_SCOPE_PROCESS_IDS
    assert "conversion.feature-project" in LAYER_SCOPE_PROCESS_IDS


# ---------------------------------------------------------------------------
# GeoPandas integration
# ---------------------------------------------------------------------------


def test_execute_dataframe_roundtrip() -> None:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    captured: dict[str, Any] = {}
    gdf = gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(1.0, 2.0)], crs="EPSG:4326")

    # The /results endpoint returns a document-mode OUTPUTS MAP keyed by output
    # id, not a bare FeatureCollection; execute_dataframe must select the
    # FeatureCollection-valued member before converting.
    results_outputs_map = {"outputFeatureLayer": FEATURE_COLLECTION}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            captured.update(json.loads(request.content))
            return httpx.Response(201, json=_status("job-df", "accepted"))
        if path == "/ogc/processes/jobs/job-df":
            return httpx.Response(200, json=_status("job-df", "successful"))
        if path == "/ogc/processes/jobs/job-df/results":
            return httpx.Response(200, json=results_outputs_map)
        raise AssertionError(f"unexpected {path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        out = client.geoprocessing().execute_dataframe(
            "geometry.buffer", gdf, parameters={"distance": 5}, poll_interval=0.0
        )

    assert list(out["name"]) == ["a"]
    sent = json.loads(captured["inputs"]["inputGeoJson"])
    assert sent["type"] == "FeatureCollection"
    assert sent["features"][0]["geometry"]["type"] == "Point"


def test_execute_dataframe_selects_value_wrapped_output() -> None:
    """An OGC ``value``-wrapped output member is unwrapped to a FeatureCollection."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    gdf = gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(1.0, 2.0)], crs="EPSG:4326")
    # Document-mode outputs map where the member wraps the data under "value".
    results_outputs_map = {
        "outputFeatureLayer": {
            "value": FEATURE_COLLECTION,
            "mediaType": "application/geo+json",
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(201, json=_status("job-vw", "accepted"))
        if path == "/ogc/processes/jobs/job-vw":
            return httpx.Response(200, json=_status("job-vw", "successful"))
        if path == "/ogc/processes/jobs/job-vw/results":
            return httpx.Response(200, json=results_outputs_map)
        raise AssertionError(f"unexpected {path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        out = client.geoprocessing().execute_dataframe(
            "geometry.buffer", gdf, poll_interval=0.0
        )

    assert list(out["name"]) == ["a"]


def test_execute_dataframe_passes_bare_feature_collection_through() -> None:
    """A results document that is itself a bare FeatureCollection is accepted."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    gdf = gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(1.0, 2.0)], crs="EPSG:4326")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(201, json=_status("job-bare", "accepted"))
        if path == "/ogc/processes/jobs/job-bare":
            return httpx.Response(200, json=_status("job-bare", "successful"))
        if path == "/ogc/processes/jobs/job-bare/results":
            return httpx.Response(200, json=FEATURE_COLLECTION)
        raise AssertionError(f"unexpected {path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        out = client.geoprocessing().execute_dataframe(
            "geometry.buffer", gdf, poll_interval=0.0
        )

    assert list(out["name"]) == ["a"]


def test_execute_dataframe_raises_when_no_feature_collection_output() -> None:
    """A results map with no FeatureCollection output raises a clear error."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    from honua_sdk.errors import HonuaError

    gdf = gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(1.0, 2.0)], crs="EPSG:4326")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(201, json=_status("job-bad", "accepted"))
        if path == "/ogc/processes/jobs/job-bad":
            return httpx.Response(200, json=_status("job-bad", "successful"))
        if path == "/ogc/processes/jobs/job-bad/results":
            return httpx.Response(200, json={"outputScalar": {"value": 42.0}})
        raise AssertionError(f"unexpected {path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(HonuaError, match="does not contain a FeatureCollection"):
            client.geoprocessing().execute_dataframe("geometry.area", gdf, poll_interval=0.0)


# ---------------------------------------------------------------------------
# Async parity
# ---------------------------------------------------------------------------


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_async_execute_submit_poll_results() -> None:
    poll_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(201, json=_status("ajob-1", "accepted"))
        if path == "/ogc/processes/jobs/ajob-1":
            poll_count["n"] += 1
            status = "running" if poll_count["n"] < 2 else "successful"
            return httpx.Response(200, json=_status("ajob-1", status))
        if path == "/ogc/processes/jobs/ajob-1/results":
            return httpx.Response(200, json=RESULTS_DOCUMENT)
        raise AssertionError(f"unexpected {path}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        gp = client.geoprocessing()
        assert isinstance(gp, AsyncHonuaGeoprocessing)
        result = await gp.execute(
            "geometry.buffer", LayerReference.from_geojson(FEATURE_COLLECTION), poll_interval=0.0
        )

    assert result == RESULTS_DOCUMENT
    assert poll_count["n"] == 2


@pytest.mark.anyio
async def test_async_discovery_and_plan_and_geometry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/ogc/processes/processes":
            return httpx.Response(200, json=PROCESS_LIST)
        if path == "/ogc/processes/processes/geometry.buffer":
            return httpx.Response(200, json=PROCESS_DESCRIPTION)
        if request.method == "POST":
            return httpx.Response(201, json=_status("ajob-2", "accepted"))
        if path == "/ogc/processes/jobs/ajob-2":
            return httpx.Response(200, json=_status("ajob-2", "successful"))
        if path == "/ogc/processes/jobs/ajob-2/results":
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected {path}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        gp = client.geoprocessing()
        listing = await gp.processes()
        described = await gp.describe("geometry.buffer")
        plan_result = await gp.execute_plan({"planId": "p", "steps": []}, poll_interval=0.0)
        geom_result = await gp.execute_geometry("geometry.area", {"geometry": "AA"}, poll_interval=0.0)

    assert len(listing["processes"]) == 2
    assert described["id"] == "geometry.buffer"
    assert plan_result == {"ok": True}
    assert geom_result == {"ok": True}


@pytest.mark.anyio
async def test_async_error_path_and_lifecycle() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/ogc/processes/jobs":
            return httpx.Response(200, json={"jobs": []})
        if request.method == "DELETE":
            return httpx.Response(200, json=_status("ajob-3", "dismissed"))
        if request.method == "POST":
            return httpx.Response(201, json=_status("ajob-3", "accepted"))
        if path == "/ogc/processes/jobs/ajob-3":
            return httpx.Response(200, json=_status("ajob-3", "failed"))
        raise AssertionError(f"unexpected {path}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        gp = client.geoprocessing()
        assert await gp.jobs() == {"jobs": []}
        await gp.dismiss("ajob-3")
        with pytest.raises(GeoprocessingJobError):
            await gp.execute(
                "geometry.buffer", LayerReference.from_geojson(FEATURE_COLLECTION), poll_interval=0.0
            )
