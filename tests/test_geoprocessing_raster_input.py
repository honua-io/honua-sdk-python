"""Tests for raster/surface process *input* wiring on the geoprocessing clients.

Covers:

* :class:`RasterReference` construction / ``to_inputs`` / mutual-exclusivity,
* the exact plan-wrapped execution body ``submit_raster_process`` /
  ``execute_raster_process`` send (raster ids 404 on direct execution, so they
  are auto-wrapped as a single ``geoprocess`` step inside the canonical
  ``honua-geoprocessing`` ``plan`` -- shape mirrors the real
  ``OgcProcessesExecutionSubmissionTests`` fixture),
* ``results_kind`` + kind-routed ``consume_result`` for all four
  ``ArtifactKind`` values (``Raster`` / ``FeatureLayer`` / ``Table`` / ``Scalar``)
  using representative result-document shapes.

Transport is mocked with :class:`httpx.MockTransport` (no live server). The
raster-conversion path additionally needs the optional ``raster`` extra and is
skipped via :func:`pytest.importorskip` when it is absent.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from honua_sdk import AsyncHonuaClient, HonuaClient
from honua_sdk.errors import HonuaError
from honua_sdk.geoprocessing import (
    CANONICAL_PROCESS_ID,
    RASTER_SCOPE_PROCESS_IDS,
    LayerReference,
    RasterReference,
    _data_uri_bytes,
    _feature_collection_from_output,
    _output_json_bytes,
    results_kind,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _status(job_id: str, status: str) -> dict[str, Any]:
    return {
        "jobID": job_id,
        "status": status,
        "processID": CANONICAL_PROCESS_ID,
        "type": "process",
    }


def _tiny_geotiff() -> bytes:
    pytest.importorskip("rasterio")
    import numpy as np
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin

    array = np.arange(12, dtype="float32").reshape(1, 3, 4)
    profile = {
        "driver": "GTiff",
        "height": 3,
        "width": 4,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_origin(0, 3, 1, 1),
    }
    with MemoryFile() as memfile:
        with memfile.open(**profile) as dataset:
            dataset.write(array)
        return bytes(memfile.read())


# ---------------------------------------------------------------------------
# RasterReference
# ---------------------------------------------------------------------------


def test_raster_scope_ids_are_the_nineteen_plus_zonal() -> None:
    assert "surface.slope" in RASTER_SCOPE_PROCESS_IDS
    assert "raster.zonal-statistics" in RASTER_SCOPE_PROCESS_IDS
    assert len(RASTER_SCOPE_PROCESS_IDS) == 20  # 8 surface + 12 raster ids
    # Raster ids are disjoint from the direct-execution vector allowlist.
    from honua_sdk.geoprocessing import LAYER_SCOPE_PROCESS_IDS

    assert RASTER_SCOPE_PROCESS_IDS.isdisjoint(LAYER_SCOPE_PROCESS_IDS)


def test_raster_reference_from_geotiff_bytes() -> None:
    ref = RasterReference.from_geotiff_bytes(b"II*\x00fake")
    assert ref.kind == "source"
    assert ref.to_inputs() == {"source": base64.b64encode(b"II*\x00fake").decode("ascii")}


def test_raster_reference_from_layer_id() -> None:
    assert RasterReference.from_layer_id("dem-1").to_inputs() == {"layerId": "dem-1"}


def test_raster_reference_from_raster_id() -> None:
    assert RasterReference.from_raster_id("r-42").to_inputs() == {"rasterId": "r-42"}


def test_raster_reference_requires_exactly_one_carrier() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        RasterReference(kind="source", source_base64="AA==", layer_id="dem-1")
    with pytest.raises(ValueError, match="exactly one"):
        RasterReference(kind="source")


def test_raster_reference_from_geotiff_bytes_type_checked() -> None:
    with pytest.raises(TypeError):
        RasterReference.from_geotiff_bytes("not-bytes")  # type: ignore[arg-type]


def test_raster_reference_to_inputs_guards_empty_carrier() -> None:
    # __post_init__ only checks "populated" (not None); an empty-string carrier
    # passes that check but must still be rejected by to_inputs()'s own guard.
    with pytest.raises(ValueError, match="source raster reference requires"):
        RasterReference(kind="source", source_base64="").to_inputs()
    with pytest.raises(ValueError, match="layerId raster reference requires"):
        RasterReference(kind="layerId", layer_id="").to_inputs()
    with pytest.raises(ValueError, match="rasterId raster reference requires"):
        RasterReference(kind="rasterId", raster_id="").to_inputs()


# ---------------------------------------------------------------------------
# Plan-wrapped submission body
# ---------------------------------------------------------------------------


def _capture_execution() -> tuple[list[dict[str, Any]], "httpx.MockTransport"]:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            assert path == f"/ogc/processes/processes/{CANONICAL_PROCESS_ID}/execution"
            captured.append(json.loads(request.content))
            return httpx.Response(201, json=_status("job-1", "accepted"))
        if path == "/ogc/processes/jobs/job-1":
            return httpx.Response(200, json=_status("job-1", "successful"))
        if path == "/ogc/processes/jobs/job-1/results":
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected {path}")

    return captured, httpx.MockTransport(handler)


def test_submit_raster_process_wraps_into_canonical_plan() -> None:
    captured, transport = _capture_execution()
    raster = RasterReference.from_layer_id("dem-1")

    with HonuaClient("http://example.test", transport=transport) as client:
        client.geoprocessing().submit_raster_process(
            "surface.slope",
            raster,
            parameters={"units": "degrees"},
            plan_id="plan-slope",
        )

    assert captured == [
        {
            "inputs": {
                "plan": {
                    "planId": "plan-slope",
                    "steps": [
                        {
                            "stepId": "s1",
                            "kind": "geoprocess",
                            "processId": "surface.slope",
                            "inputs": {"layerId": "dem-1", "units": "degrees"},
                        }
                    ],
                }
            },
            "response": "document",
        }
    ]


def test_execute_raster_process_wraps_source_bytes() -> None:
    captured, transport = _capture_execution()
    raster = RasterReference.from_geotiff_bytes(b"II*\x00dem")

    with HonuaClient("http://example.test", transport=transport) as client:
        result = client.geoprocessing().execute_raster_process(
            "surface.slope",
            raster,
            parameters={"units": "degrees", "zFactor": 2, "invert": False},
            plan_id="plan-x",
            poll_interval=0.0,
        )

    assert result == {}
    step = captured[0]["inputs"]["plan"]["steps"][0]
    assert step["processId"] == "surface.slope"
    assert step["inputs"]["source"] == base64.b64encode(b"II*\x00dem").decode("ascii")
    # Non-string parameters are canonicalized to strings, like the vector path
    # (including the boolean true/false spelling, not Python's True/False).
    assert step["inputs"]["units"] == "degrees"
    assert step["inputs"]["zFactor"] == "2"
    assert step["inputs"]["invert"] == "false"


def test_execute_raster_process_with_zones_base64_geojson() -> None:
    captured, transport = _capture_execution()
    raster = RasterReference.from_layer_id("dem-1")
    zones_fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"id": "z0"}, "geometry": {"type": "Polygon", "coordinates": []}}
        ],
    }
    zones = LayerReference.from_geojson(zones_fc)

    with HonuaClient("http://example.test", transport=transport) as client:
        client.geoprocessing().execute_raster_process(
            "raster.zonal-statistics",
            raster,
            zones=zones,
            parameters={"statistics": "mean,count", "band": 1},
            plan_id="plan-zonal",
            poll_interval=0.0,
        )

    inputs = captured[0]["inputs"]["plan"]["steps"][0]["inputs"]
    assert inputs["layerId"] == "dem-1"
    # zones ride as a *base64-encoded* GeoJSON FeatureCollection under ``zones``.
    decoded = json.loads(base64.b64decode(inputs["zones"]).decode("utf-8"))
    assert decoded == zones_fc
    assert inputs["statistics"] == "mean,count"
    assert inputs["band"] == "1"


def test_zones_must_be_inline_geojson() -> None:
    _, transport = _capture_execution()
    raster = RasterReference.from_layer_id("dem-1")
    zones = LayerReference.from_query_result("qr-1")

    with HonuaClient("http://example.test", transport=transport) as client:
        with pytest.raises(ValueError, match="inline-GeoJSON"):
            client.geoprocessing().execute_raster_process(
                "raster.zonal-statistics", raster, zones=zones, poll_interval=0.0
            )


def test_default_plan_id_is_generated_and_unique() -> None:
    captured, transport = _capture_execution()
    raster = RasterReference.from_layer_id("dem-1")

    with HonuaClient("http://example.test", transport=transport) as client:
        client.geoprocessing().submit_raster_process("surface.aspect", raster)

    plan_id = captured[0]["inputs"]["plan"]["planId"]
    assert plan_id.startswith("raster-surface.aspect-")


# ---------------------------------------------------------------------------
# results_kind + kind-routed consumption
# ---------------------------------------------------------------------------


def _raster_results() -> dict[str, Any]:
    encoded = base64.b64encode(_tiny_geotiff()).decode("ascii")
    return {
        "slope": {
            "id": "artifact-slope",
            "kind": "Raster",
            "title": "Slope",
            "href": f"data:image/tiff; application=geotiff;base64,{encoded}",
            "type": "image/tiff; application=geotiff",
        }
    }


_CONTOUR_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"elev": 100}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}
    ],
}


def _featurelayer_results() -> dict[str, Any]:
    encoded = base64.b64encode(json.dumps(_CONTOUR_FC).encode("utf-8")).decode("ascii")
    return {
        "contour": {
            "id": "artifact-contour",
            "kind": "FeatureLayer",
            "title": "Contour vector",
            "href": f"data:application/geo+json;base64,{encoded}",
            "type": "application/geo+json",
        }
    }


_ZONAL_TABLE = {
    "kind": "raster.zonal-statistics",
    "band": 1,
    "statistics": ["mean", "count"],
    "zones": [
        {"zoneIndex": 0, "zoneId": "0", "mean": 12.5, "count": 40},
        {"zoneIndex": 1, "zoneId": "1", "mean": 7.0, "count": 12},
    ],
}


def _table_results() -> dict[str, Any]:
    encoded = base64.b64encode(json.dumps(_ZONAL_TABLE).encode("utf-8")).decode("ascii")
    return {
        "zonalStatistics": {
            "id": "artifact-zonal",
            "kind": "Table",
            "title": "Zonal statistics",
            "href": f"data:application/json;base64,{encoded}",
            "type": "application/json",
        }
    }


_SCALAR = {"kind": "raster.statistics", "band": 1, "mean": 3.5, "min": 0.0, "max": 11.0}


def _scalar_results() -> dict[str, Any]:
    encoded = base64.b64encode(json.dumps(_SCALAR).encode("utf-8")).decode("ascii")
    return {
        "statistics": {
            "id": "artifact-stats",
            "kind": "Scalar",
            "title": "Statistics",
            "href": f"data:application/json;base64,{encoded}",
            "type": "application/json",
        }
    }


def test_results_kind_for_each_artifact_kind() -> None:
    assert results_kind(_raster_results()) == "Raster"
    assert results_kind(_featurelayer_results()) == "FeatureLayer"
    assert results_kind(_table_results()) == "Table"
    assert results_kind(_scalar_results()) == "Scalar"
    # A bare pass-through FeatureCollection declares no kind.
    assert results_kind({"type": "FeatureCollection", "features": []}) is None


def _client() -> HonuaClient:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - no fetch expected
        raise AssertionError(f"unexpected fetch {request.url}")

    return HonuaClient("http://example.test", transport=httpx.MockTransport(handler))


def test_consume_result_table_returns_json() -> None:
    with _client() as client:
        value = client.geoprocessing().consume_result(_table_results())
    assert value == _ZONAL_TABLE
    assert value["zones"][0]["mean"] == 12.5


def test_consume_result_scalar_returns_json() -> None:
    with _client() as client:
        value = client.geoprocessing().consume_result(_scalar_results())
    assert value == _SCALAR


def test_consume_result_featurelayer_returns_geodataframe() -> None:
    pytest.importorskip("geopandas")
    with _client() as client:
        gdf = client.geoprocessing().consume_result(_featurelayer_results())
    assert len(gdf) == 1
    assert list(gdf["elev"]) == [100]


def test_consume_result_raster_returns_xarray() -> None:
    pytest.importorskip("rioxarray")
    with _client() as client:
        array = client.geoprocessing().consume_result(_raster_results())
    assert array.shape == (1, 3, 4)
    assert float(array.sum()) == pytest.approx(66.0)


def test_result_raster_bytes_decodes_data_uri_href() -> None:
    pytest.importorskip("rasterio")
    with _client() as client:
        data = client.geoprocessing().result_raster_bytes(_raster_results())
    assert data == _tiny_geotiff()


def test_consume_result_unknown_kind_sniffs_json() -> None:
    # A member with a kind the SDK does not special-case, but a JSON payload.
    encoded = base64.b64encode(json.dumps({"answer": 42}).encode("utf-8")).decode("ascii")
    results = {"out": {"id": "x", "kind": "Table", "href": f"data:application/json;base64,{encoded}"}}
    with _client() as client:
        assert client.geoprocessing().consume_result(results) == {"answer": 42}


# ---------------------------------------------------------------------------
# Pure decode/selection helpers (no optional extra needed for any of these --
# these are the primitives consume_result's kind-routing is built on, and are
# exercised directly so their branches stay covered independent of whether
# geopandas/rasterio happen to be installed).
# ---------------------------------------------------------------------------


def test_data_uri_bytes_non_data_uri_is_none() -> None:
    assert _data_uri_bytes("https://example.test/x.tif") is None


def test_data_uri_bytes_base64() -> None:
    encoded = base64.b64encode(b"hello").decode("ascii")
    assert _data_uri_bytes(f"data:text/plain;base64,{encoded}") == b"hello"


def test_data_uri_bytes_plain_percent_encoded() -> None:
    assert _data_uri_bytes("data:text/plain,hello%20world") == b"hello world"


def test_data_uri_bytes_invalid_base64_raises() -> None:
    with pytest.raises(HonuaError, match="not valid base64"):
        _data_uri_bytes("data:text/plain;base64,not-base64!!!")


def test_output_json_bytes_data_uri_value() -> None:
    encoded = base64.b64encode(b'{"a": 1}').decode("ascii")
    member = {"value": f"data:application/json;base64,{encoded}"}
    assert _output_json_bytes(member) == b'{"a": 1}'


def test_output_json_bytes_raw_json_string_value() -> None:
    member = {"value": '{"a": 1}'}
    assert _output_json_bytes(member) == b'{"a": 1}'


def test_output_json_bytes_non_json_non_data_value_is_none() -> None:
    # A string value that is neither a ``data:`` URI nor JSON-looking.
    assert _output_json_bytes({"value": "not-json-and-not-a-data-uri"}) is None


def test_output_json_bytes_data_uri_href() -> None:
    encoded = base64.b64encode(b"[1, 2]").decode("ascii")
    member = {"href": f"data:application/json;base64,{encoded}"}
    assert _output_json_bytes(member) == b"[1, 2]"


def test_output_json_bytes_no_value_or_href_is_none() -> None:
    assert _output_json_bytes({"id": "x", "kind": "Scalar"}) is None


def test_results_kind_bare_document_is_the_member() -> None:
    # The results document itself (not an outputs map) carries ``kind``.
    assert results_kind({"id": "x", "kind": "Scalar", "value": {"mean": 1.0}}) == "Scalar"


def test_results_kind_value_wrapped_member() -> None:
    # OGC ``raw``/``value``-wrapped member: the kind-bearing payload sits under
    # the outer member's ``value`` key rather than at the top level.
    results = {"out": {"value": {"id": "x", "kind": "Table", "href": "data:application/json;base64,e30="}}}
    assert results_kind(results) == "Table"


def test_feature_collection_from_output_via_kind_based_decode() -> None:
    found = _feature_collection_from_output(_featurelayer_results())
    assert found == _CONTOUR_FC


def test_feature_collection_from_output_falls_back_to_inline_shape() -> None:
    # The plain inline-FeatureCollection vector-process shape (no ``kind``).
    inline = {"out": {"value": _CONTOUR_FC}}
    assert _feature_collection_from_output(inline) == _CONTOUR_FC


def test_feature_collection_from_output_bare_document_is_the_collection() -> None:
    # The whole results document IS the (pass-through) FeatureCollection.
    assert _feature_collection_from_output(_CONTOUR_FC) == _CONTOUR_FC


def test_feature_collection_from_output_member_is_the_collection_directly() -> None:
    # An outputs-map member that IS a FeatureCollection directly (not wrapped
    # under a ``value`` key).
    results = {"out": _CONTOUR_FC}
    assert _feature_collection_from_output(results) == _CONTOUR_FC


def test_feature_collection_from_output_none_when_absent() -> None:
    assert _feature_collection_from_output(_table_results()) is None


def test_consume_result_unsupported_kind_raises() -> None:
    results = {"out": {"id": "x", "kind": "SomethingElse", "value": {"a": 1}}}
    with _client() as client:
        with pytest.raises(HonuaError, match="Unsupported results kind"):
            client.geoprocessing().consume_result(results)


def test_consume_result_undeclared_kind_falls_back_to_json() -> None:
    # No ``kind`` anywhere, no raster, no FeatureCollection -- falls all the way
    # through to the plain-JSON-value path without needing any optional extra.
    # The document itself is the "member" here (no outputs-map nesting), same
    # bare-document shape ``_is_feature_collection``/``find_raster_output``
    # already tolerate.
    encoded = base64.b64encode(json.dumps({"answer": 42}).encode("utf-8")).decode("ascii")
    results = {"value": f"data:application/json;base64,{encoded}"}
    with _client() as client:
        assert client.geoprocessing().consume_result(results) == {"answer": 42}


def _fetch_client(payload: bytes, expected_path: str) -> HonuaClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == expected_path
        return httpx.Response(200, content=payload, headers={"content-type": "application/json"})

    return HonuaClient("http://example.test", transport=httpx.MockTransport(handler))


def test_result_json_value_fetches_live_href() -> None:
    # A Table/Scalar member with no inline value/data-uri href, only a live
    # fetchable href -- exercises the (extras-independent) fetch fallback.
    payload = json.dumps({"mean": 5.0}).encode("utf-8")
    results = {"stats": {"id": "x", "kind": "Scalar", "href": "https://example.test/artifacts/stats.json"}}
    with _fetch_client(payload, "/artifacts/stats.json") as client:
        assert client.geoprocessing()._result_json_value(results) == {"mean": 5.0}


def test_result_json_value_raw_dict_value() -> None:
    results = {"stats": {"id": "x", "kind": "Scalar", "value": {"mean": 5.0}}}
    with _client() as client:
        assert client.geoprocessing()._result_json_value(results) == {"mean": 5.0}


def test_result_json_value_raises_when_no_decodable_payload() -> None:
    results = {"stats": {"id": "x", "kind": "Scalar"}}
    with _client() as client:
        with pytest.raises(HonuaError, match="no decodable JSON payload"):
            client.geoprocessing()._result_json_value(results)


def test_result_feature_collection_resolves_via_pure_decode() -> None:
    # _result_feature_collection needs no client I/O (and no geopandas) when the
    # pure _feature_collection_from_output decode already finds the payload --
    # this is what lets _result_geodataframe stay a thin geopandas-only wrapper.
    with _client() as client:
        assert client.geoprocessing()._result_feature_collection(_featurelayer_results()) == _CONTOUR_FC


def test_result_feature_collection_fetches_live_href() -> None:
    payload = json.dumps(_CONTOUR_FC).encode("utf-8")
    results = {"contour": {"id": "x", "kind": "FeatureLayer", "href": "https://example.test/artifacts/c.geojson"}}
    with _fetch_client(payload, "/artifacts/c.geojson") as client:
        assert client.geoprocessing()._result_feature_collection(results) == _CONTOUR_FC


def test_result_feature_collection_raises_when_absent() -> None:
    with _client() as client:
        with pytest.raises(HonuaError, match="does not contain a FeatureCollection"):
            client.geoprocessing()._result_feature_collection(_table_results())


# ---------------------------------------------------------------------------
# Async parity
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_async_submit_raster_process_wraps_into_canonical_plan() -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        captured.append(json.loads(request.content))
        return httpx.Response(201, json=_status("job-1", "accepted"))

    raster = RasterReference.from_layer_id("dem-1")
    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        await client.geoprocessing().submit_raster_process(
            "surface.slope", raster, parameters={"units": "degrees"}, plan_id="plan-slope"
        )

    assert captured[0]["inputs"]["plan"] == {
        "planId": "plan-slope",
        "steps": [
            {
                "stepId": "s1",
                "kind": "geoprocess",
                "processId": "surface.slope",
                "inputs": {"layerId": "dem-1", "units": "degrees"},
            }
        ],
    }


@pytest.mark.anyio
async def test_async_execute_raster_process_wraps_plan() -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            captured.append(json.loads(request.content))
            return httpx.Response(201, json=_status("job-a", "accepted"))
        if path == "/ogc/processes/jobs/job-a":
            return httpx.Response(200, json=_status("job-a", "successful"))
        if path == "/ogc/processes/jobs/job-a/results":
            return httpx.Response(200, json=_scalar_results())
        raise AssertionError(f"unexpected {path}")

    raster = RasterReference.from_raster_id("r-1")
    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        gp = client.geoprocessing()
        result = await gp.execute_raster_process(
            "raster.statistics", raster, plan_id="plan-a", poll_interval=0.0
        )
        value = await gp.consume_result(result)

    step = captured[0]["inputs"]["plan"]["steps"][0]
    assert step == {
        "stepId": "s1",
        "kind": "geoprocess",
        "processId": "raster.statistics",
        "inputs": {"rasterId": "r-1"},
    }
    assert value == _SCALAR


@pytest.mark.anyio
async def test_async_consume_result_featurelayer() -> None:
    pytest.importorskip("geopandas")

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - no fetch expected
        raise AssertionError(f"unexpected fetch {request.url}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        gdf = await client.geoprocessing().consume_result(_featurelayer_results())

    assert len(gdf) == 1
    assert list(gdf["elev"]) == [100]


@pytest.mark.anyio
async def test_async_consume_result_unsupported_kind_raises() -> None:
    results = {"out": {"id": "x", "kind": "SomethingElse", "value": {"a": 1}}}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - no fetch expected
        raise AssertionError(f"unexpected fetch {request.url}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(HonuaError, match="Unsupported results kind"):
            await client.geoprocessing().consume_result(results)


@pytest.mark.anyio
async def test_async_consume_result_undeclared_kind_falls_back_to_json() -> None:
    encoded = base64.b64encode(json.dumps({"answer": 42}).encode("utf-8")).decode("ascii")
    results = {"value": f"data:application/json;base64,{encoded}"}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - no fetch expected
        raise AssertionError(f"unexpected fetch {request.url}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        assert await client.geoprocessing().consume_result(results) == {"answer": 42}


@pytest.mark.anyio
async def test_async_result_json_value_fetches_live_href() -> None:
    payload = json.dumps({"mean": 5.0}).encode("utf-8")
    results = {"stats": {"id": "x", "kind": "Scalar", "href": "https://example.test/artifacts/stats.json"}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/artifacts/stats.json"
        return httpx.Response(200, content=payload, headers={"content-type": "application/json"})

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        value = await client.geoprocessing()._result_json_value(results)
    assert value == {"mean": 5.0}


@pytest.mark.anyio
async def test_async_result_json_value_raw_dict_value() -> None:
    results = {"stats": {"id": "x", "kind": "Scalar", "value": {"mean": 5.0}}}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - no fetch expected
        raise AssertionError(f"unexpected fetch {request.url}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        value = await client.geoprocessing()._result_json_value(results)
    assert value == {"mean": 5.0}


@pytest.mark.anyio
async def test_async_result_json_value_raises_when_no_decodable_payload() -> None:
    results = {"stats": {"id": "x", "kind": "Scalar"}}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - no fetch expected
        raise AssertionError(f"unexpected fetch {request.url}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(HonuaError, match="no decodable JSON payload"):
            await client.geoprocessing()._result_json_value(results)


@pytest.mark.anyio
async def test_async_result_feature_collection_resolves_via_pure_decode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - no fetch expected
        raise AssertionError(f"unexpected fetch {request.url}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        found = await client.geoprocessing()._result_feature_collection(_featurelayer_results())
    assert found == _CONTOUR_FC


@pytest.mark.anyio
async def test_async_result_feature_collection_fetches_live_href() -> None:
    payload = json.dumps(_CONTOUR_FC).encode("utf-8")
    results = {"contour": {"id": "x", "kind": "FeatureLayer", "href": "https://example.test/artifacts/c.geojson"}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/artifacts/c.geojson"
        return httpx.Response(200, content=payload, headers={"content-type": "application/geo+json"})

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        found = await client.geoprocessing()._result_feature_collection(results)
    assert found == _CONTOUR_FC


@pytest.mark.anyio
async def test_async_result_feature_collection_raises_when_absent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - no fetch expected
        raise AssertionError(f"unexpected fetch {request.url}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(HonuaError, match="does not contain a FeatureCollection"):
            await client.geoprocessing()._result_feature_collection(_table_results())
