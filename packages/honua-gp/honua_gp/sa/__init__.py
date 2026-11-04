"""``arcpy.sa`` (Spatial Analyst) shim -- 16 raster/surface tools + 2 stubs.

Customers replace ``from arcpy.sa import *`` (and the raster-oriented Data
Management tools) with ``from honua_gp import sa``. Each tool projects its arcpy
signature onto one of honua-server's raster/surface GDAL-worker processes and
runs it as an asynchronous OGC API Processes job, auto-wrapped as a single
``geoprocess`` step inside the canonical ``honua-geoprocessing`` plan (raster
process ids 404 on direct execution). See :mod:`honua_gp._raster_tools` for the
dispatch lifecycle and :mod:`honua_gp._compat` for the per-tool status.

Raster inputs are honua-native: pass a :class:`honua_gp.RasterReference`
(``RasterReference.from_layer_id`` / ``.from_raster_id`` / ``.from_geotiff_bytes``)
or raw GeoTIFF ``bytes``. Raster-output tools return a
:class:`honua_gp.RasterResult` handle (lazy ``.to_xarray()`` / ``.raster_bytes``
/ ``.to_geodataframe()`` / ``.consume()``); ``ZonalStatisticsAsTable`` returns
the Table-kind JSON (a list of per-zone aggregate dicts) directly.

Named kwargs cover each tool's common, catalog-confirmed parameters; a generic
``parameters=`` mapping (keyed by honua-server input name) passes the rest
through untranslated. Esri tool names mirror honua-server's GPServer
``GPServerEsriTaskAliases`` where a mapping exists (ProjectRaster, Resample,
ZonalStatisticsAsTable, ...).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .._compat import entry_for
from .._dispatch import raise_unsupported
from .._raster_tools import (
    RasterResult,
    as_raster_reference,
    encode_feature_collection,
    encode_source_list,
    merge_parameters,
    named_parameters,
    raster_inputs,
    run_raster_process,
)


def _server_params(qualified: str, named: Mapping[str, Any], parameters: Mapping[str, Any] | None) -> dict[str, Any]:
    """Map named arcpy kwargs (via the manifest ``param_map``) + generic passthrough.

    ``named`` is keyed by arcpy keyword and translated through the entry's
    ``param_map`` into honua-server input names; ``parameters`` (already keyed by
    server input name) is layered on top so a caller can reach any input the
    named kwargs do not surface.
    """
    entry = entry_for(qualified)
    param_map = entry.param_map if entry is not None else {}
    server = named_parameters(param_map, **dict(named))
    if parameters:
        server.update(parameters)
    return server


def _run_single_source(
    qualified: str,
    in_raster: Any,
    *,
    zones: Any | None = None,
    named: Mapping[str, Any] | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> Any:
    reference = as_raster_reference(in_raster)
    server = _server_params(qualified, named or {}, parameters)
    inputs = raster_inputs(reference, zones=zones, parameters=server)
    return run_raster_process(qualified, inputs)


# ---------------------------------------------------------------------------
# Surface (DEM-derived) tools -- single 'source' raster in, raster out
# ---------------------------------------------------------------------------


def Slope(in_raster: Any, *, units: Any = None, z_factor: Any = None, parameters: Mapping[str, Any] | None = None) -> RasterResult:
    """arcpy.sa.Slope -> honua-server ``surface.slope`` (units: degrees/percent)."""
    return _run_single_source(
        "sa.Slope", in_raster, named={"units": units, "z_factor": z_factor}, parameters=parameters
    )


def Aspect(in_raster: Any, *, parameters: Mapping[str, Any] | None = None) -> RasterResult:
    """arcpy.sa.Aspect -> honua-server ``surface.aspect`` (compass-bearing aspect)."""
    return _run_single_source("sa.Aspect", in_raster, parameters=parameters)


def Hillshade(
    in_raster: Any,
    *,
    azimuth: Any = None,
    altitude: Any = None,
    z_factor: Any = None,
    parameters: Mapping[str, Any] | None = None,
) -> RasterResult:
    """arcpy.sa.Hillshade -> honua-server ``surface.hillshade``."""
    return _run_single_source(
        "sa.Hillshade",
        in_raster,
        named={"azimuth": azimuth, "altitude": altitude, "z_factor": z_factor},
        parameters=parameters,
    )


def Contour(
    in_raster: Any,
    interval: Any,
    *,
    base: Any = None,
    parameters: Mapping[str, Any] | None = None,
) -> RasterResult:
    """arcpy.sa.Contour -> honua-server ``surface.contour`` (FeatureLayer output).

    Returns a :class:`honua_gp.RasterResult`; the contour lines are a GeoJSON
    FeatureLayer reachable via ``.to_geodataframe()`` / ``.consume()``.
    """
    return _run_single_source(
        "sa.Contour", in_raster, named={"interval": interval, "base": base}, parameters=parameters
    )


def Viewshed(
    in_raster: Any,
    *,
    observer_x: Any,
    observer_y: Any,
    observer_height: Any = None,
    target_height: Any = None,
    max_distance: Any = None,
    parameters: Mapping[str, Any] | None = None,
) -> RasterResult:
    """arcpy.sa.Viewshed -> honua-server ``surface.viewshed`` (binary visibility)."""
    return _run_single_source(
        "sa.Viewshed",
        in_raster,
        named={
            "observer_x": observer_x,
            "observer_y": observer_y,
            "observer_height": observer_height,
            "target_height": target_height,
            "max_distance": max_distance,
        },
        parameters=parameters,
    )


def Roughness(in_raster: Any, *, window_radius: Any = None, parameters: Mapping[str, Any] | None = None) -> RasterResult:
    """Roughness -> honua-server ``surface.roughness`` (server supports windowRadius=1)."""
    return _run_single_source(
        "sa.Roughness", in_raster, named={"window_radius": window_radius}, parameters=parameters
    )


def TPI(in_raster: Any, *, window_radius: Any = None, parameters: Mapping[str, Any] | None = None) -> RasterResult:
    """TPI (topographic position index) -> honua-server ``surface.rugosity-tpi``."""
    return _run_single_source(
        "sa.TPI", in_raster, named={"window_radius": window_radius}, parameters=parameters
    )


def TRI(in_raster: Any, *, window_radius: Any = None, parameters: Mapping[str, Any] | None = None) -> RasterResult:
    """TRI (terrain ruggedness index) -> honua-server ``surface.rugosity-tri``."""
    return _run_single_source(
        "sa.TRI", in_raster, named={"window_radius": window_radius}, parameters=parameters
    )


# ---------------------------------------------------------------------------
# Raster tools -- single 'source' raster in, raster out
# ---------------------------------------------------------------------------


def Clip(
    in_raster: Any,
    *,
    boundary: Any,
    boundary_srid: Any = None,
    parameters: Mapping[str, Any] | None = None,
) -> RasterResult:
    """Raster Clip -> honua-server ``raster.clip`` (gdalwarp -cutline; boundary is WKB)."""
    return _run_single_source(
        "sa.Clip", in_raster, named={"boundary": boundary, "boundary_srid": boundary_srid}, parameters=parameters
    )


def Reclassify(
    in_raster: Any,
    *,
    remap: Any,
    default_value: Any = None,
    data_type: Any = None,
    no_data: Any = None,
    parameters: Mapping[str, Any] | None = None,
) -> RasterResult:
    """arcpy.sa.Reclassify -> honua-server ``raster.reclassify`` (';'-separated remap)."""
    return _run_single_source(
        "sa.Reclassify",
        in_raster,
        named={"remap": remap, "default_value": default_value, "data_type": data_type, "no_data": no_data},
        parameters=parameters,
    )


def ProjectRaster(
    in_raster: Any,
    *,
    target_srid: Any,
    resampling: Any = None,
    parameters: Mapping[str, Any] | None = None,
) -> RasterResult:
    """ProjectRaster -> honua-server ``raster.reproject`` (gdalwarp -t_srs)."""
    return _run_single_source(
        "sa.ProjectRaster",
        in_raster,
        named={"target_srid": target_srid, "resampling": resampling},
        parameters=parameters,
    )


def Resample(
    in_raster: Any,
    *,
    cell_size: Any,
    cell_size_y: Any = None,
    resampling: Any = None,
    parameters: Mapping[str, Any] | None = None,
) -> RasterResult:
    """Resample -> honua-server ``raster.resample`` (gdalwarp -tr)."""
    return _run_single_source(
        "sa.Resample",
        in_raster,
        named={"cell_size": cell_size, "cell_size_y": cell_size_y, "resampling": resampling},
        parameters=parameters,
    )


def ZonalStatisticsAsTable(
    in_raster: Any,
    zones: Any,
    *,
    band: Any = None,
    statistics: Any = None,
    parameters: Mapping[str, Any] | None = None,
) -> Any:
    """arcpy.sa.ZonalStatisticsAsTable -> honua-server ``raster.zonal-statistics``.

    ``zones`` is an inline GeoJSON ``FeatureCollection`` (or an inline-GeoJSON
    :class:`honua_sdk.geoprocessing.LayerReference`) of zone polygons. Returns
    the Table-kind JSON directly -- a list of per-zone aggregate dicts -- not a
    raster.
    """
    return _run_single_source(
        "sa.ZonalStatisticsAsTable",
        in_raster,
        zones=zones,
        named={"band": band, "statistics": statistics},
        parameters=parameters,
    )


# ---------------------------------------------------------------------------
# Multi-source / point-input tools (custom input assembly)
# ---------------------------------------------------------------------------


def Mosaic(
    in_rasters: Any,
    *,
    operator: Any = None,
    resampling: Any = None,
    parameters: Mapping[str, Any] | None = None,
) -> RasterResult:
    """Mosaic -> honua-server ``raster.mosaic``.

    ``in_rasters`` is a list of two or more input rasters (raw GeoTIFF bytes or
    ``RasterReference.from_geotiff_bytes``); layerId/rasterId references are not
    accepted for the '|'-joined ``sources`` list.
    """
    inputs: dict[str, Any] = {"sources": encode_source_list(in_rasters)}
    merge_parameters(inputs, _server_params("sa.Mosaic", {"operator": operator, "resampling": resampling}, parameters))
    return run_raster_process("sa.Mosaic", inputs)


def RasterCalculator(
    expression: Any,
    in_rasters: Any,
    *,
    data_type: Any = None,
    no_data: Any = None,
    parameters: Mapping[str, Any] | None = None,
) -> RasterResult:
    """arcpy.sa.RasterCalculator -> honua-server ``raster.map-algebra`` (gdal_calc.py).

    ``in_rasters`` is a list of input rasters bound to band variables A, B, C,
    ... (raw GeoTIFF bytes or ``RasterReference.from_geotiff_bytes``);
    ``expression`` is an allow-listed band-math expression (e.g. ``"(A-B)/(A+B)"``).
    """
    inputs: dict[str, Any] = {"sources": encode_source_list(in_rasters)}
    server = _server_params("sa.RasterCalculator", {"data_type": data_type, "no_data": no_data}, parameters)
    server["expression"] = expression
    merge_parameters(inputs, server)
    return run_raster_process("sa.RasterCalculator", inputs)


def Idw(
    in_point_features: Any,
    *,
    z_field: Any = None,
    power: Any = None,
    radius: Any = None,
    smoothing: Any = None,
    parameters: Mapping[str, Any] | None = None,
) -> RasterResult:
    """arcpy.sa.Idw -> honua-server ``raster.interpolate-idw`` (gdal_grid -a invdist).

    ``in_point_features`` is an inline GeoJSON point ``FeatureCollection`` (or an
    inline-GeoJSON ``LayerReference``). The output raster size is controlled via
    the server's ``width``/``height`` inputs (pass through ``parameters=``); the
    server has no arcpy ``cell_size`` input.
    """
    inputs: dict[str, Any] = {"points": encode_feature_collection(in_point_features)}
    merge_parameters(
        inputs,
        _server_params(
            "sa.Idw",
            {"z_field": z_field, "power": power, "radius": radius, "smoothing": smoothing},
            parameters,
        ),
    )
    return run_raster_process("sa.Idw", inputs)


# ---------------------------------------------------------------------------
# Honest stubs
# ---------------------------------------------------------------------------


def Kriging(*args: Any, **kwargs: Any) -> Any:
    """arcpy.sa.Kriging -> honua-server ``raster.interpolate-kriging`` (stub).

    honua-server NEVER produces output for kriging: the job executor fails before
    any raster work because stock GDAL bundles no kriging backend. Rather than
    overclaim a guaranteed-failing tool as supported, the shim refuses it
    client-side (raising :class:`~honua_gp.HonuaGpUnsupportedError` before any
    server call). Use :func:`Idw` for a working interpolation.
    """
    raise_unsupported("sa.Kriging", args=args, kwargs=kwargs)


def Histogram(*args: Any, **kwargs: Any) -> Any:
    """honua-server ``raster.histogram`` -- no faithful single arcpy tool name (stub)."""
    raise_unsupported("sa.Histogram", args=args, kwargs=kwargs)


def SpectralIndex(*args: Any, **kwargs: Any) -> Any:
    """honua-server ``raster.spectral-index`` -- no faithful single arcpy tool name (stub)."""
    raise_unsupported("sa.SpectralIndex", args=args, kwargs=kwargs)


__all__ = [
    "Aspect",
    "Clip",
    "Contour",
    "Hillshade",
    "Histogram",
    "Idw",
    "Kriging",
    "Mosaic",
    "ProjectRaster",
    "RasterCalculator",
    "RasterResult",
    "Reclassify",
    "Resample",
    "Roughness",
    "Slope",
    "SpectralIndex",
    "TPI",
    "TRI",
    "Viewshed",
    "ZonalStatisticsAsTable",
]
