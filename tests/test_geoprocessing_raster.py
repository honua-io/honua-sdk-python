"""Tests for raster result interop on the geoprocessing clients.

The pure output-selection helpers (``find_raster_output`` / ``inline_raster_bytes``
/ ``raster_href``) carry no optional dependency and are tested directly. The
conversion helpers and the client integration paths require the optional
``raster`` extra (rasterio/rioxarray/xarray) and are skipped via
:func:`pytest.importorskip` when it is absent.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest

from honua_sdk import AsyncHonuaClient, HonuaClient
from honua_sdk.errors import HonuaError
from honua_sdk.geoprocessing import LayerReference
from honua_sdk.raster import (
    find_raster_output,
    inline_raster_bytes,
    raster_href,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _status(job_id: str, status: str) -> dict[str, Any]:
    return {"jobID": job_id, "status": status, "processID": "raster.kernel-density", "type": "process"}


# ---------------------------------------------------------------------------
# Pure output selection (no optional deps)
# ---------------------------------------------------------------------------


def test_find_raster_output_by_href_suffix() -> None:
    results = {"out": {"href": "https://api.honua.test/artifacts/r.tif", "type": "image/tiff"}}
    member = find_raster_output(results)
    assert member["href"].endswith("r.tif")


def test_find_raster_output_by_media_type() -> None:
    results = {"out": {"href": "https://api.honua.test/d/123", "type": "image/tiff; application=geotiff"}}
    assert find_raster_output(results)["href"].endswith("/123")


def test_find_raster_output_inline_value() -> None:
    results = {"coverage": {"value": "Zm9v", "mediaType": "image/tiff; application=geotiff"}}
    assert find_raster_output(results)["value"] == "Zm9v"


def test_find_raster_output_value_wrapped() -> None:
    results = {"out": {"value": {"href": "x.tiff", "mediaType": "image/geotiff"}}}
    assert find_raster_output(results)["href"] == "x.tiff"


def test_find_raster_output_document_is_member() -> None:
    results = {"href": "cog.tif", "type": "image/tiff"}
    assert find_raster_output(results)["href"] == "cog.tif"


def test_find_raster_output_missing_raises() -> None:
    results = {"out": {"value": {"type": "FeatureCollection", "features": []}}}
    with pytest.raises(HonuaError, match="does not contain a raster"):
        find_raster_output(results)


def test_inline_raster_bytes_plain_and_data_uri() -> None:
    raw = b"\x49\x49\x2a\x00fake-tiff"
    encoded = base64.b64encode(raw).decode("ascii")
    assert inline_raster_bytes({"value": encoded}) == raw
    assert inline_raster_bytes({"value": f"data:image/tiff;base64,{encoded}"}) == raw


def test_inline_raster_bytes_none_for_href_only() -> None:
    assert inline_raster_bytes({"href": "x.tif"}) is None


def test_inline_raster_bytes_invalid_base64_raises() -> None:
    with pytest.raises(HonuaError, match="not valid base64"):
        inline_raster_bytes({"value": "not!base64!!"})


def test_raster_href() -> None:
    assert raster_href({"href": "x.tif"}) == "x.tif"
    assert raster_href({"value": "Zm9v"}) is None


# ---------------------------------------------------------------------------
# Conversions + client integration (require the ``raster`` extra)
# ---------------------------------------------------------------------------


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


def test_geotiff_to_xarray_roundtrip() -> None:
    pytest.importorskip("rioxarray")
    from honua_sdk.raster import geotiff_to_xarray

    data = _tiny_geotiff()
    array = geotiff_to_xarray(data)
    assert array.shape == (1, 3, 4)
    assert float(array.sum()) == pytest.approx(66.0)
    assert array.rio.crs is not None


def test_open_geotiff_dataset() -> None:
    pytest.importorskip("rasterio")
    from honua_sdk.raster import open_geotiff

    with open_geotiff(_tiny_geotiff()) as dataset:
        assert dataset.count == 1
        assert dataset.width == 4
        assert dataset.height == 3


def test_xarray_to_geotiff_roundtrip() -> None:
    pytest.importorskip("rioxarray")
    from honua_sdk.raster import geotiff_to_xarray, xarray_to_geotiff

    array = geotiff_to_xarray(_tiny_geotiff())
    data = xarray_to_geotiff(array)
    reloaded = geotiff_to_xarray(data)
    assert float(reloaded.sum()) == pytest.approx(66.0)


def test_ensure_deps_raises_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    import honua_sdk.raster as raster_mod

    monkeypatch.setattr(raster_mod, "_HAS_DEPS", False)
    with pytest.raises(ImportError, match=r"honua-sdk\[raster\]"):
        raster_mod.open_geotiff(b"")


def test_result_to_xarray_inline_value() -> None:
    pytest.importorskip("rioxarray")
    encoded = base64.b64encode(_tiny_geotiff()).decode("ascii")
    results = {"coverage": {"value": encoded, "mediaType": "image/tiff; application=geotiff"}}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - inline needs no fetch
        raise AssertionError(f"unexpected fetch {request.url}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        array = client.geoprocessing().result_to_xarray(results)

    assert float(array.sum()) == pytest.approx(66.0)


def test_result_raster_bytes_fetches_href() -> None:
    pytest.importorskip("rasterio")
    data = _tiny_geotiff()
    results = {"out": {"href": "https://example.test/artifacts/r.tif", "type": "image/tiff"}}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, content=data, headers={"content-type": "image/tiff"})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        fetched = client.geoprocessing().result_raster_bytes(results)

    assert fetched == data
    assert seen == ["/artifacts/r.tif"]


def test_result_raster_bytes_without_value_or_href_raises() -> None:
    # A raster member identified by mediaType whose ``href`` is empty, so there
    # is neither a usable inline ``value`` nor a fetchable ``href``.
    results = {"out": {"href": "", "mediaType": "image/tiff; application=geotiff"}}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - no fetch expected
        raise AssertionError("no fetch expected")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(HonuaError, match="neither an inline value nor an href"):
            client.geoprocessing().result_raster_bytes(results)


def test_execute_raster_end_to_end() -> None:
    pytest.importorskip("rioxarray")
    encoded = base64.b64encode(_tiny_geotiff()).decode("ascii")
    results_outputs_map = {"coverage": {"value": encoded, "mediaType": "image/tiff; application=geotiff"}}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(201, json=_status("job-r", "accepted"))
        if path == "/ogc/processes/jobs/job-r":
            return httpx.Response(200, json=_status("job-r", "successful"))
        if path == "/ogc/processes/jobs/job-r/results":
            return httpx.Response(200, json=results_outputs_map)
        raise AssertionError(f"unexpected {path}")

    layer = LayerReference.from_geojson({"type": "FeatureCollection", "features": []})
    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        array = client.geoprocessing().execute_raster("raster.kernel-density", layer, poll_interval=0.0)

    assert float(array.sum()) == pytest.approx(66.0)


@pytest.mark.anyio
async def test_async_result_to_xarray_and_href() -> None:
    pytest.importorskip("rioxarray")
    data = _tiny_geotiff()
    results = {"out": {"href": "https://example.test/artifacts/r.tif", "type": "image/tiff"}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=data, headers={"content-type": "image/tiff"})

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        array = await client.geoprocessing().result_to_xarray(results)

    assert float(array.sum()) == pytest.approx(66.0)


@pytest.mark.anyio
async def test_async_result_to_rasterio_inline() -> None:
    pytest.importorskip("rasterio")
    encoded = base64.b64encode(_tiny_geotiff()).decode("ascii")
    results = {"coverage": {"value": encoded, "mediaType": "image/tiff; application=geotiff"}}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - inline needs no fetch
        raise AssertionError(f"unexpected fetch {request.url}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with await client.geoprocessing().result_to_rasterio(results) as dataset:
            assert dataset.count == 1
            assert dataset.width == 4


@pytest.mark.anyio
async def test_async_execute_raster_end_to_end() -> None:
    pytest.importorskip("rioxarray")
    encoded = base64.b64encode(_tiny_geotiff()).decode("ascii")
    results_outputs_map = {"coverage": {"value": encoded, "mediaType": "image/tiff; application=geotiff"}}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(201, json=_status("job-ar", "accepted"))
        if path == "/ogc/processes/jobs/job-ar":
            return httpx.Response(200, json=_status("job-ar", "successful"))
        if path == "/ogc/processes/jobs/job-ar/results":
            return httpx.Response(200, json=results_outputs_map)
        raise AssertionError(f"unexpected {path}")

    layer = LayerReference.from_geojson({"type": "FeatureCollection", "features": []})
    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        array = await client.geoprocessing().execute_raster("raster.kernel-density", layer, poll_interval=0.0)

    assert float(array.sum()) == pytest.approx(66.0)
