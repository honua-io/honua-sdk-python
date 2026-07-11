"""Spatial-Analyst (``honua_gp.sa``) raster/surface tool dispatch.

Each tool is exercised through a faked OGC API Processes transport that models
honua-server's async job lifecycle: ``execute`` returns a ``201`` StatusInfo
with a ``jobID`` + ``accepted`` status, ``job(jobID)`` resolves to
``successful``, and ``job_results(jobID)`` returns the terminal outputs map. The
tests assert that:

* the raster call is auto-wrapped as a single ``geoprocess`` step inside the
  canonical ``honua-geoprocessing`` plan (raster ids 404 on direct execution),
* the flat process ``inputs`` bag carries the right raster/zone/point carriers
  and the translated + passthrough parameters,
* raster-output tools return a lazy :class:`honua_gp.RasterResult` and
  ``ZonalStatisticsAsTable`` returns the per-zone Table JSON, and
* the two honest stubs raise ``HonuaGpUnsupportedError``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

import honua_gp
from honua_gp import RasterReference
from honua_gp._raster_tools import RasterResult

_POINTS_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {"z": 1.0}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"z": 2.0}},
    ],
}
_ZONES_FC = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]},
            "properties": {"zone": "A"},
        }
    ],
}


class _FakeRasterClient:
    """Doubles as the data client (``session.client()``) and its OGC processes client.

    ``ogc_processes()`` returns ``self`` so ``session.processes_client()`` drives
    the same object; ``execute`` records the submitted ``(process_id, payload)``
    so tests can assert the auto-wrapped plan.
    """

    def __init__(self, *, results: dict | None = None, terminal: str = "successful") -> None:
        self.calls: list[tuple[str, dict]] = []
        self.job_polls: list[str] = []
        self.results_fetches: list[str] = []
        self._results = results
        self._terminal = terminal

    def ogc_processes(self) -> "_FakeRasterClient":
        return self

    def execute(self, process_id: str, payload: dict) -> dict:
        self.calls.append((process_id, payload))
        return {"processID": process_id, "jobID": "job-1", "status": "accepted"}

    def job(self, job_id: str) -> dict:
        self.job_polls.append(job_id)
        return {
            "jobID": job_id,
            "status": self._terminal,
            "message": "kriging unsupported" if self._terminal == "failed" else None,
        }

    def job_results(self, job_id: str) -> dict:
        self.results_fetches.append(job_id)
        if self._results is not None:
            return self._results
        # Default: a Raster-kind output (inline data URI; never decoded here).
        return {"out": {"kind": "Raster", "value": "data:image/tiff;base64,AAAA"}}

    def dismiss_job(self, job_id: str) -> None:
        return None


def _configure(client: _FakeRasterClient) -> None:
    honua_gp.configure(client=client)


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    import honua_gp._process_jobs as jobs

    monkeypatch.setattr(jobs.time, "sleep", lambda _s: None)


def _plan_step(client: _FakeRasterClient) -> dict:
    """Return the single geoprocess step of the submitted canonical plan."""
    process_id, payload = client.calls[0]
    assert process_id == "honua-geoprocessing"
    plan = payload["inputs"]["plan"]
    assert isinstance(plan["planId"], str) and plan["planId"]
    steps = plan["steps"]
    assert len(steps) == 1
    step = steps[0]
    assert step["stepId"] == "s1"
    assert step["kind"] == "geoprocess"
    return step


def _audit_lines(audit_root: Path) -> list[dict]:
    out: list[dict] = []
    for path in sorted(audit_root.glob("audit-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# Surface tools -- single 'source' raster
# ---------------------------------------------------------------------------


def test_slope_wraps_single_step_plan_with_layer_ref(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    result = honua_gp.sa.Slope(RasterReference.from_layer_id("dem-1"), units="degrees", z_factor=2)

    step = _plan_step(client)
    assert step["processId"] == "surface.slope"
    assert step["inputs"] == {"layerId": "dem-1", "units": "degrees", "zFactor": "2"}

    assert isinstance(result, RasterResult)
    assert result.process_id == "surface.slope"
    assert result.job_id == "job-1"
    assert result.kind == "Raster"
    assert client.job_polls == ["job-1"]
    assert client.results_fetches == ["job-1"]


def test_slope_from_geotiff_bytes_emits_base64_source(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.Slope(b"II*\x00fake-geotiff-bytes")

    step = _plan_step(client)
    assert set(step["inputs"]) == {"source"}
    assert base64.b64decode(step["inputs"]["source"]) == b"II*\x00fake-geotiff-bytes"


def test_aspect_has_no_extra_params(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.Aspect(RasterReference.from_raster_id("r-9"))

    step = _plan_step(client)
    assert step["processId"] == "surface.aspect"
    assert step["inputs"] == {"rasterId": "r-9"}


def test_hillshade_named_params(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.Hillshade(RasterReference.from_layer_id("dem"), azimuth=315, altitude=45, z_factor=1.5)

    step = _plan_step(client)
    assert step["processId"] == "surface.hillshade"
    assert step["inputs"] == {"layerId": "dem", "azimuth": "315", "altitude": "45", "zFactor": "1.5"}


def test_contour_interval_and_returns_handle(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient(results={"contours": {"kind": "FeatureLayer", "value": "data:application/json;base64,e30="}})
    _configure(client)

    result = honua_gp.sa.Contour(RasterReference.from_layer_id("dem"), 10.0, base=5.0)

    step = _plan_step(client)
    assert step["processId"] == "surface.contour"
    assert step["inputs"] == {"layerId": "dem", "interval": "10.0", "base": "5.0"}
    assert isinstance(result, RasterResult)
    assert result.kind == "FeatureLayer"


def test_viewshed_observer_and_optional_params(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.Viewshed(
        RasterReference.from_layer_id("dem"), observer_x=100.0, observer_y=200.0, max_distance=500.0
    )

    step = _plan_step(client)
    assert step["processId"] == "surface.viewshed"
    assert step["inputs"] == {
        "layerId": "dem",
        "observerX": "100.0",
        "observerY": "200.0",
        "maxDistance": "500.0",
    }


@pytest.mark.parametrize(
    "func,process_id",
    [
        (honua_gp.sa.Roughness, "surface.roughness"),
        (honua_gp.sa.TPI, "surface.rugosity-tpi"),
        (honua_gp.sa.TRI, "surface.rugosity-tri"),
    ],
)
def test_rugosity_window_radius(func, process_id, _isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    func(RasterReference.from_layer_id("dem"), window_radius=1)

    step = _plan_step(client)
    assert step["processId"] == process_id
    assert step["inputs"] == {"layerId": "dem", "windowRadius": "1"}


# ---------------------------------------------------------------------------
# Raster tools -- single 'source'
# ---------------------------------------------------------------------------


def test_clip_boundary_wkb(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.Clip(RasterReference.from_layer_id("img"), boundary="0101000000...", boundary_srid=4326)

    step = _plan_step(client)
    assert step["processId"] == "raster.clip"
    assert step["inputs"] == {"layerId": "img", "boundary": "0101000000...", "boundarySrid": "4326"}


def test_reclassify_remap(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.Reclassify(RasterReference.from_layer_id("lc"), remap="0..10:1;10..20:2", no_data=-9999)

    step = _plan_step(client)
    assert step["processId"] == "raster.reclassify"
    assert step["inputs"] == {"layerId": "lc", "remap": "0..10:1;10..20:2", "noData": "-9999"}


def test_project_raster_target_srid(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.ProjectRaster(RasterReference.from_layer_id("img"), target_srid=3857, resampling="bilinear")

    step = _plan_step(client)
    assert step["processId"] == "raster.reproject"
    assert step["inputs"] == {"layerId": "img", "targetSrid": "3857", "resampling": "bilinear"}


def test_resample_cell_size(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.Resample(RasterReference.from_layer_id("img"), cell_size=30.0, cell_size_y=30.0)

    step = _plan_step(client)
    assert step["processId"] == "raster.resample"
    assert step["inputs"] == {"layerId": "img", "cellSize": "30.0", "cellSizeY": "30.0"}


# ---------------------------------------------------------------------------
# ZonalStatisticsAsTable -- secondary vector input + Table-kind JSON output
# ---------------------------------------------------------------------------


def test_zonal_statistics_encodes_zones_and_returns_table_json(_isolated_audit_dir: Path) -> None:
    table = [{"zone": "A", "mean": 5.0, "count": 42}]
    client = _FakeRasterClient(
        results={"stats": {"kind": "Table", "value": json.dumps(table)}}
    )
    _configure(client)

    result = honua_gp.sa.ZonalStatisticsAsTable(
        RasterReference.from_layer_id("elev"), _ZONES_FC, statistics="mean,count", band=1
    )

    step = _plan_step(client)
    assert step["processId"] == "raster.zonal-statistics"
    assert step["inputs"]["layerId"] == "elev"
    assert step["inputs"]["statistics"] == "mean,count"
    assert step["inputs"]["band"] == "1"
    # zones ride as a base64-encoded compact GeoJSON FeatureCollection.
    decoded = json.loads(base64.b64decode(step["inputs"]["zones"]))
    assert decoded == _ZONES_FC

    # Table-kind output is returned as parsed JSON, not a RasterResult.
    assert result == table


def test_zonal_statistics_accepts_layer_reference_zones(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient(results={"stats": {"kind": "Table", "value": "[]"}})
    _configure(client)

    honua_gp.sa.ZonalStatisticsAsTable(
        RasterReference.from_layer_id("elev"), honua_gp.LayerReference.from_geojson(_ZONES_FC)
    )

    step = _plan_step(client)
    assert json.loads(base64.b64decode(step["inputs"]["zones"])) == _ZONES_FC


# ---------------------------------------------------------------------------
# Multi-source / point-input tools
# ---------------------------------------------------------------------------


def test_mosaic_joins_base64_sources(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.Mosaic([b"raster-a", b"raster-b"], operator="last")

    step = _plan_step(client)
    assert step["processId"] == "raster.mosaic"
    assert step["inputs"]["operator"] == "last"
    parts = step["inputs"]["sources"].split("|")
    assert [base64.b64decode(p) for p in parts] == [b"raster-a", b"raster-b"]


def test_mosaic_rejects_layer_reference_inputs(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.sa.Mosaic([RasterReference.from_layer_id("a"), b"raster-b"])
    assert client.calls == []


def test_raster_calculator_expression_and_sources(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.RasterCalculator("(A-B)/(A+B)", [b"nir", b"red"], data_type="Float32")

    step = _plan_step(client)
    assert step["processId"] == "raster.map-algebra"
    assert step["inputs"]["expression"] == "(A-B)/(A+B)"
    assert step["inputs"]["dataType"] == "Float32"
    assert step["inputs"]["sources"].split("|") == [
        base64.b64encode(b"nir").decode(),
        base64.b64encode(b"red").decode(),
    ]


def test_idw_encodes_points_and_power(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.Idw(_POINTS_FC, z_field="z", power=2.5)

    step = _plan_step(client)
    assert step["processId"] == "raster.interpolate-idw"
    assert step["inputs"]["zField"] == "z"
    assert step["inputs"]["power"] == "2.5"
    assert json.loads(base64.b64decode(step["inputs"]["points"])) == _POINTS_FC


def test_kriging_encodes_points(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.Kriging(_POINTS_FC, z_field="z")

    step = _plan_step(client)
    assert step["processId"] == "raster.interpolate-kriging"
    assert step["inputs"]["zField"] == "z"
    assert json.loads(base64.b64decode(step["inputs"]["points"])) == _POINTS_FC


# ---------------------------------------------------------------------------
# Generic passthrough, errors, stubs, audit
# ---------------------------------------------------------------------------


def test_generic_parameters_passthrough_uses_server_names(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    # width/height are real idw inputs the wrapper does not surface as named kwargs.
    honua_gp.sa.Idw(_POINTS_FC, power=2, parameters={"width": 256, "height": 256})

    step = _plan_step(client)
    assert step["inputs"]["width"] == "256"
    assert step["inputs"]["height"] == "256"
    assert step["inputs"]["power"] == "2"


def test_unset_optional_params_are_dropped(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.Slope(RasterReference.from_layer_id("dem"))

    step = _plan_step(client)
    # units / zFactor omitted entirely rather than sent as None.
    assert step["inputs"] == {"layerId": "dem"}


def test_bad_raster_input_raises_before_submit(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.sa.Slope("dem-1")  # bare strings are ambiguous; use RasterReference
    assert client.calls == []


def test_failed_job_raises_execute_error(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient(terminal="failed")
    _configure(client)

    with pytest.raises(honua_gp.ExecuteError) as info:
        honua_gp.sa.Kriging(_POINTS_FC, z_field="z")
    assert info.value.error_kind == "failed"

    lines = [r for r in _audit_lines(_isolated_audit_dir) if r["function"] == "sa.Kriging"]
    assert lines[-1]["status"] == "error"
    assert lines[-1]["error_kind"] == "failed"


@pytest.mark.parametrize("func", [honua_gp.sa.Histogram, honua_gp.sa.SpectralIndex])
def test_stubs_raise_unsupported(func, _isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    with pytest.raises(honua_gp.HonuaGpUnsupportedError):
        func(RasterReference.from_layer_id("x"))
    assert client.calls == []


def test_writes_single_audit_line_with_process_metadata(_isolated_audit_dir: Path) -> None:
    client = _FakeRasterClient()
    _configure(client)

    honua_gp.sa.Slope(RasterReference.from_layer_id("dem"), units="percent")

    lines = [r for r in _audit_lines(_isolated_audit_dir) if r["function"] == "sa.Slope"]
    assert len(lines) == 1
    line = lines[0]
    assert line["status"] == "ok"
    assert line["process_id"] == "surface.slope"
    assert line["job_id"] == "job-1"
    assert line["job_status"] == "successful"
    assert line["result_kind"] == "Raster"
    # The raster payload is never audited -- only the (secret-free) input keys.
    assert set(line["process_input_keys"]) == {"layerId", "units"}


def test_raster_result_to_xarray_roundtrip(_isolated_audit_dir: Path) -> None:
    """Lazy raster conversion is honua_sdk's job; verify the handle wires it up.

    Guarded by the optional ``raster`` extra so the no-extras CI leg skips it.
    """
    rasterio = pytest.importorskip("rasterio")
    pytest.importorskip("xarray")
    import io

    import numpy as np
    from rasterio.transform import from_origin

    # Build a tiny in-memory GeoTIFF so the SDK's geotiff_to_xarray has real bytes.
    buffer = io.BytesIO()
    data = np.arange(9, dtype="float32").reshape(1, 3, 3)
    with rasterio.open(
        buffer,
        "w",
        driver="GTiff",
        height=3,
        width=3,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(0, 3, 1, 1),
    ) as dst:
        dst.write(data)
    geotiff = buffer.getvalue()
    encoded = base64.b64encode(geotiff).decode("ascii")

    client = _FakeRasterClient(
        results={"out": {"kind": "Raster", "mediaType": "image/tiff", "value": encoded}}
    )
    _configure(client)

    result = honua_gp.sa.Slope(RasterReference.from_layer_id("dem"))
    array = result.to_xarray()
    assert array.shape[-2:] == (3, 3)
