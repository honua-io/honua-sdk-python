"""Tests for the additional GeoServices ImageServer operations.

Covers ``compute_histograms``, ``compute_statistics_histograms``,
``get_samples``, ``multidimensional_info``, ``measure``, ``find``, and
``project`` on both :class:`GeoServicesImageServerClient` and its async
counterpart. Each test mocks the transport and asserts the constructed URL
path and query parameters against the wire format confirmed by honua-server's
own ImageServer handlers (see
``src/Honua.Protocols.GeoServices/ImageServer/Handlers/*.cs`` and
``ImageServerEndpoints.cs`` in the honua-server repo) and the
honua-esri-compat certification harness.

Two corrections were made after an initial round of live-Docker
verification against a real seeded server surfaced them:

- ``measure_operation`` is a required parameter on :meth:`measure` (no
  default) -- ``ImageServerMeasureHandler.TryParseRequest`` 400s
  ("measureOperation parameter is required.") without it.
- Several previously-exposed parameters were removed because no
  honua-server handler reads them at all (silently ignored, not just
  "not yet implemented"): ``measure``'s ``mosaic_rule``/``pixel_size``;
  ``get_samples``'s ``geometry_type``/``sample_distance``/
  ``return_first_value_only``/``interpolation``/``out_fields``; and
  ``compute_histograms``/``compute_statistics_histograms``'s ``pixel_size``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from honua_sdk import AsyncHonuaClient, HonuaClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _json_handler(seen: list[dict[str, Any]], payload: dict[str, Any]):
    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append(
            {
                "method": request.method,
                "raw_path": raw_path,
                "query": dict(request.url.params.multi_items()),
            }
        )
        return httpx.Response(200, json=payload)

    return handler


_ENVELOPE = {"xmin": -122.5, "ymin": 37.7, "xmax": -122.35, "ymax": 37.84, "spatialReference": {"wkid": 4326}}
_POINT = {"x": -122.45, "y": 37.75, "spatialReference": {"wkid": 4326}}


# --------------------------------------------------------------------------
# compute_histograms / compute_statistics_histograms — sync
# --------------------------------------------------------------------------


def test_compute_histograms_builds_params() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_json_handler(seen, {"histograms": [{"size": 1, "min": 200, "max": 200, "counts": [4096]}]}))
    with HonuaClient("http://example.test", transport=transport) as client:
        client.image_server("imagery").compute_histograms(
            _ENVELOPE,
            mosaic_rule={"mosaicMethod": "esriMosaicNorthwest"},
            rendering_rule={"rasterFunction": "Stretch"},
            raster_ids=[1, 2],
            band_ids=[0, 1],
            histogram_parameters={"size": 64},
            time="2024-01-15T18:00:00Z",
        )
    assert seen[0]["raw_path"] == "/rest/services/imagery/ImageServer/computeHistograms"
    query = seen[0]["query"]
    assert query["f"] == "json"
    assert query["geometryType"] == "esriGeometryEnvelope"
    assert query["geometry"] == '{"xmin":-122.5,"ymin":37.7,"xmax":-122.35,"ymax":37.84,"spatialReference":{"wkid":4326}}'
    assert query["mosaicRule"] == '{"mosaicMethod":"esriMosaicNorthwest"}'
    assert query["renderingRule"] == '{"rasterFunction":"Stretch"}'
    assert query["rasterIds"] == "1,2"
    assert query["bandIds"] == "0,1"
    assert query["histogramParameters"] == '{"size":64}'
    assert query["time"] == "2024-01-15T18:00:00Z"
    assert "pixelSize" not in query


def test_compute_statistics_histograms_builds_params() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_json_handler(seen, {"statistics": [], "histograms": []}))
    with HonuaClient("http://example.test", transport=transport) as client:
        client.image_server("imagery").compute_statistics_histograms(_ENVELOPE)
    assert seen[0]["raw_path"] == "/rest/services/imagery/ImageServer/computeStatisticsHistograms"
    query = seen[0]["query"]
    assert query["f"] == "json"
    assert query["geometryType"] == "esriGeometryEnvelope"
    assert query["geometry"] == '{"xmin":-122.5,"ymin":37.7,"xmax":-122.35,"ymax":37.84,"spatialReference":{"wkid":4326}}'
    assert "mosaicRule" not in query
    assert "rasterIds" not in query
    assert "pixelSize" not in query


def test_compute_histograms_has_no_pixel_size_parameter() -> None:
    """``pixelSize`` is not read by ``ImageServerStatisticsHistogramsHandler``

    (unlike ``mosaicRule``/``renderingRule``/``rasterIds``/``bandIds``/
    ``histogramParameters``, which are genuinely wired) -- so it must not be
    a keyword this wrapper accepts, to avoid misleading callers into thinking
    it has an effect.
    """
    import inspect

    from honua_sdk.protocols import GeoServicesImageServerClient

    sig = inspect.signature(GeoServicesImageServerClient.compute_histograms)
    assert "pixel_size" not in sig.parameters


# --------------------------------------------------------------------------
# get_samples — sync
# --------------------------------------------------------------------------


def test_get_samples_builds_params() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_json_handler(seen, {"samples": [{"location": _POINT, "value": "200"}]}))
    with HonuaClient("http://example.test", transport=transport) as client:
        client.image_server("imagery").get_samples(
            _POINT,
            sample_count=4,
            mosaic_rule={"mosaicMethod": "esriMosaicNorthwest"},
            sr=4326,
            time="2024-01-15T18:00:00Z",
            multidimensional_definition=[{"variableName": "temp", "dimensionName": "StdTime", "values": [0], "isSlice": True}],
        )
    assert seen[0]["raw_path"] == "/rest/services/imagery/ImageServer/getSamples"
    query = seen[0]["query"]
    assert query["geometry"] == '{"x":-122.45,"y":37.75,"spatialReference":{"wkid":4326}}'
    assert query["sampleCount"] == "4"
    assert query["mosaicRule"] == '{"mosaicMethod":"esriMosaicNorthwest"}'
    assert query["sr"] == "4326"
    assert query["time"] == "2024-01-15T18:00:00Z"
    assert query["multidimensionalDefinition"] == '[{"variableName":"temp","dimensionName":"StdTime","values":[0],"isSlice":true}]'
    assert "geometryType" not in query


def test_get_samples_has_no_dead_parameters() -> None:
    """geometryType/sampleDistance/returnFirstValueOnly/interpolation/outFields

    are read by neither ``ImageServerSamplesHandler`` nor its endpoint-level
    validator -- honua-server silently ignores them -- so this wrapper must
    not expose them as first-class parameters.
    """
    import inspect

    from honua_sdk.protocols import GeoServicesImageServerClient

    sig = inspect.signature(GeoServicesImageServerClient.get_samples)
    dead = {"geometry_type", "sample_distance", "return_first_value_only", "interpolation", "out_fields", "pixel_size"}
    assert not (dead & sig.parameters.keys())


# --------------------------------------------------------------------------
# multidimensional_info — sync
# --------------------------------------------------------------------------


def test_multidimensional_info_hits_canonical_path() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_json_handler(seen, {"multidimensionalInfo": {"variables": []}}))
    with HonuaClient("http://example.test", transport=transport) as client:
        client.image_server("imagery").multidimensional_info()
    assert seen[0]["raw_path"] == "/rest/services/imagery/ImageServer/multidimensionalInfo"
    assert seen[0]["query"] == {"f": "json"}


# --------------------------------------------------------------------------
# measure — sync
# --------------------------------------------------------------------------


def test_measure_builds_params() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_json_handler(seen, {"name": "raster", "value": {"distance": 100.0}}))
    to_point = {"x": -122.3, "y": 37.8, "spatialReference": {"wkid": 4326}}
    with HonuaClient("http://example.test", transport=transport) as client:
        client.image_server("imagery").measure(
            _POINT,
            "esriMensurationDistanceAndAngle",
            to_geometry=to_point,
            linear_unit="esriMeters",
            angular_unit="esriDUDecimalDegrees",
            area_unit="esriSquareMeters",
        )
    assert seen[0]["raw_path"] == "/rest/services/imagery/ImageServer/measure"
    query = seen[0]["query"]
    assert query["fromGeometry"] == '{"x":-122.45,"y":37.75,"spatialReference":{"wkid":4326}}'
    assert query["geometryType"] == "esriGeometryPoint"
    assert query["toGeometry"] == '{"x":-122.3,"y":37.8,"spatialReference":{"wkid":4326}}'
    assert query["measureOperation"] == "esriMensurationDistanceAndAngle"
    assert query["linearUnit"] == "esriMeters"
    assert query["angularUnit"] == "esriDUDecimalDegrees"
    assert query["areaUnit"] == "esriSquareMeters"
    assert "mosaicRule" not in query
    assert "pixelSize" not in query


def test_measure_requires_measure_operation() -> None:
    """``measure_operation`` has no default: honua-server 400s without it

    (``ImageServerMeasureHandler.TryParseRequest``: "measureOperation
    parameter is required."). Calling without it must be a Python-level
    TypeError, not a silently-malformed request.
    """
    from honua_sdk.protocols import GeoServicesImageServerClient

    with pytest.raises(TypeError):
        GeoServicesImageServerClient.measure(None, _POINT)  # type: ignore[arg-type]


def test_measure_has_no_dead_parameters() -> None:
    import inspect

    from honua_sdk.protocols import GeoServicesImageServerClient

    sig = inspect.signature(GeoServicesImageServerClient.measure)
    assert not ({"mosaic_rule", "pixel_size"} & sig.parameters.keys())
    # measure_operation must be a required parameter (no default value).
    assert sig.parameters["measure_operation"].default is inspect.Parameter.empty


# --------------------------------------------------------------------------
# find — sync
# --------------------------------------------------------------------------


def test_find_requires_to_geometry_and_builds_params() -> None:
    """``to_geometry`` is the operation's one required parameter on honua-server

    (``ImageServerFindHandler.TryParseFind`` 400s without it); ``searchText``/
    ``contains`` are not read by the handler at all, so this wrapper does not
    expose them as first-class parameters.
    """
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_json_handler(seen, {"images": []}))
    from_point = {"x": -122.5, "y": 37.6, "spatialReference": {"wkid": 4326}}
    with HonuaClient("http://example.test", transport=transport) as client:
        client.image_server("imagery").find(
            _POINT,
            from_geometry=from_point,
            in_sr=4326,
            where="OBJECTID>0",
            object_ids=[1, 2, 3],
            max_count=10,
        )
    assert seen[0]["raw_path"] == "/rest/services/imagery/ImageServer/find"
    query = seen[0]["query"]
    assert query["toGeometry"] == '{"x":-122.45,"y":37.75,"spatialReference":{"wkid":4326}}'
    assert query["fromGeometry"] == '{"x":-122.5,"y":37.6,"spatialReference":{"wkid":4326}}'
    assert query["inSR"] == "4326"
    assert query["where"] == "OBJECTID>0"
    assert query["objectIds"] == "1,2,3"
    assert query["maxCount"] == "10"


def test_find_minimal_call_sends_only_required_params() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_json_handler(seen, {"images": []}))
    with HonuaClient("http://example.test", transport=transport) as client:
        client.image_server("imagery").find(_POINT)
    assert seen[0]["query"] == {
        "f": "json",
        "toGeometry": '{"x":-122.45,"y":37.75,"spatialReference":{"wkid":4326}}',
    }


# --------------------------------------------------------------------------
# project — sync
# --------------------------------------------------------------------------


def test_project_builds_params_distinct_from_export_image_sr() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_json_handler(seen, {"geometries": [{"x": 0, "y": 0}]}))
    with HonuaClient("http://example.test", transport=transport) as client:
        client.image_server("imagery").project(
            [{"x": -122.4, "y": 37.7}],
            in_sr=4326,
            out_sr=3857,
            datum_transformation=1188,
        )
    assert seen[0]["raw_path"] == "/rest/services/imagery/ImageServer/project"
    query = seen[0]["query"]
    assert query["geometries"] == '[{"x":-122.4,"y":37.7}]'
    assert query["inSR"] == "4326"
    assert query["outSR"] == "3857"
    assert query["datumTransformation"] == "1188"


# --------------------------------------------------------------------------
# async parity
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_async_compute_histograms_and_get_samples_and_find() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append({"raw_path": raw_path, "query": dict(request.url.params.multi_items())})
        if raw_path.endswith("/computeHistograms"):
            return httpx.Response(200, json={"histograms": []})
        if raw_path.endswith("/getSamples"):
            return httpx.Response(200, json={"samples": []})
        if raw_path.endswith("/find"):
            return httpx.Response(200, json={"images": []})
        if raw_path.endswith("/multidimensionalInfo"):
            return httpx.Response(200, json={"multidimensionalInfo": {"variables": []}})
        if raw_path.endswith("/measure"):
            return httpx.Response(200, json={"name": "raster"})
        if raw_path.endswith("/project"):
            return httpx.Response(200, json={"geometries": []})
        if raw_path.endswith("/computeStatisticsHistograms"):
            return httpx.Response(200, json={"statistics": [], "histograms": []})
        raise AssertionError(f"unexpected path {raw_path}")

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        img = client.image_server("imagery")
        await img.compute_histograms(_ENVELOPE)
        await img.compute_statistics_histograms(_ENVELOPE)
        await img.get_samples(_POINT, sample_count=4)
        await img.multidimensional_info()
        await img.measure(_POINT, "esriMensurationPoint")
        await img.find(_POINT)
        await img.project([{"x": 0, "y": 0}], in_sr=4326, out_sr=3857)

    raw_paths = [e["raw_path"] for e in seen]
    assert raw_paths == [
        "/rest/services/imagery/ImageServer/computeHistograms",
        "/rest/services/imagery/ImageServer/computeStatisticsHistograms",
        "/rest/services/imagery/ImageServer/getSamples",
        "/rest/services/imagery/ImageServer/multidimensionalInfo",
        "/rest/services/imagery/ImageServer/measure",
        "/rest/services/imagery/ImageServer/find",
        "/rest/services/imagery/ImageServer/project",
    ]
    assert seen[2]["query"]["sampleCount"] == "4"
    assert seen[4]["query"]["measureOperation"] == "esriMensurationPoint"
    assert seen[5]["query"]["toGeometry"] == '{"x":-122.45,"y":37.75,"spatialReference":{"wkid":4326}}'


@pytest.mark.anyio
async def test_async_measure_requires_measure_operation() -> None:
    from honua_sdk.protocols import AsyncGeoServicesImageServerClient

    with pytest.raises(TypeError):
        AsyncGeoServicesImageServerClient.measure(None, _POINT)  # type: ignore[arg-type]
