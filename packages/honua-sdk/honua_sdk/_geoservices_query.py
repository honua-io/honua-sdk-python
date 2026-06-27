"""GeoServices REST request-construction helpers for spatial filters and statistics.

The Honua FeatureServer (GeoServices REST) ``query`` endpoint already supports
arbitrary-geometry spatial filters (``geometry`` + ``geometryType`` +
``spatialRel`` + ``inSR`` + ``distance``/``units``) and server-side
statistics/aggregation (``outStatistics`` + ``groupByFieldsForStatistics`` +
``returnDistinctValues`` + ``returnCountOnly``). The SDK previously only
emitted the bbox-envelope form of a spatial filter and exposed
statistics/aggregation solely on the gRPC surface.

This module is the SDK-side translation layer that turns a Pythonic
spatial-filter mapping (accepting Esri JSON, GeoJSON, or any object exposing
``__geo_interface__`` such as a ``shapely`` geometry) plus a chosen spatial
relationship into the GeoServices query parameters, and turns a list of
statistic definitions / group-by fields into their GeoServices equivalents.
It is pure request construction — no server change is required.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

# ---------------------------------------------------------------------------
# Spatial relationships
# ---------------------------------------------------------------------------

#: Canonical spatial-relationship tokens accepted on a spatial filter, mapped to
#: their GeoServices ``spatialRel`` values. Accepts the bare relationship name
#: (``"intersects"``), the gRPC-style ``SCREAMING_SNAKE`` form
#: (``"WITHIN_DISTANCE"``), and the raw Esri token (``"esriSpatialRelWithin"``).
_SPATIAL_REL: dict[str, str] = {
    "intersects": "esriSpatialRelIntersects",
    "envelope-intersects": "esriSpatialRelEnvelopeIntersects",
    "envelopeintersects": "esriSpatialRelEnvelopeIntersects",
    "contains": "esriSpatialRelContains",
    "within": "esriSpatialRelWithin",
    "crosses": "esriSpatialRelCrosses",
    "touches": "esriSpatialRelTouches",
    "overlaps": "esriSpatialRelOverlaps",
    "relation": "esriSpatialRelRelation",
    # Distance-based relationships have no dedicated ``spatialRel`` token in
    # GeoServices; they are expressed as ``geometry`` + ``distance`` + ``units``
    # against an intersects relation. Mapped here so callers can name the intent.
    "within-distance": "esriSpatialRelIntersects",
    "withindistance": "esriSpatialRelIntersects",
}

#: Relationship tokens that imply a distance-based query (``distance`` + ``units``).
_DISTANCE_RELATIONSHIPS = frozenset({"within-distance", "withindistance"})


def normalize_spatial_relationship(value: str) -> str:
    """Map a relationship name to its GeoServices ``spatialRel`` token.

    Accepts the canonical lower-case names (``"intersects"``, ``"within"``,
    ``"within-distance"``, ...), the gRPC ``SpatialRelationship`` enum member
    name (``"WITHIN_DISTANCE"``), or a raw ``esriSpatialRel*`` token (returned
    unchanged). Raises :class:`ValueError` on an unrecognised relationship.
    """
    text = str(value).strip()
    if text.startswith("esriSpatialRel"):
        return text
    key = text.lower().replace("_", "-")
    try:
        return _SPATIAL_REL[key]
    except KeyError as exc:
        supported = ", ".join(sorted(_SPATIAL_REL))
        raise ValueError(
            f"Unsupported spatial relationship {value!r}. Expected one of: {supported}."
        ) from exc


def _is_distance_relationship(value: str) -> bool:
    return str(value).strip().lower().replace("_", "-") in _DISTANCE_RELATIONSHIPS


# ---------------------------------------------------------------------------
# Geometry coercion (Esri JSON / GeoJSON / __geo_interface__) → Esri JSON
# ---------------------------------------------------------------------------

#: Index of the first non-planar ordinate (z) in an ``[x, y, z]`` coordinate.
_XY_LEN = 2

_GEOJSON_TO_ESRI_TYPE = {
    "Point": "esriGeometryPoint",
    "MultiPoint": "esriGeometryMultipoint",
    "LineString": "esriGeometryPolyline",
    "MultiLineString": "esriGeometryPolyline",
    "Polygon": "esriGeometryPolygon",
    "MultiPolygon": "esriGeometryPolygon",
}


def coerce_geometry(geometry: Any, *, default_type: str | None = None) -> tuple[dict[str, Any], str]:
    """Coerce a geometry to ``(esri_json, esriGeometryType)``.

    Accepts:

    * Esri JSON mappings (``{"x", "y"}``, ``{"rings": ...}``, ``{"paths": ...}``,
      ``{"points": ...}``, or an envelope ``{"xmin", "ymin", "xmax", "ymax"}``) —
      passed through with the geometry type inferred from its keys.
    * GeoJSON geometry mappings (``{"type", "coordinates"}``).
    * Any object exposing ``__geo_interface__`` (e.g. a ``shapely`` geometry),
      which yields a GeoJSON geometry.

    ``default_type`` is an explicit ``esriGeometryType`` override; when provided
    it is used verbatim for an Esri-JSON mapping whose shape can't be inferred,
    instead of raising.

    Returns the Esri JSON geometry dict and its ``geometryType`` token.
    """
    if geometry is None:
        raise ValueError("spatial_filter requires a geometry.")
    # shapely / GeoJSON-like objects expose __geo_interface__.
    if not isinstance(geometry, Mapping) and hasattr(geometry, "__geo_interface__"):
        geometry = geometry.__geo_interface__
    if not isinstance(geometry, Mapping):
        raise TypeError(
            "spatial_filter geometry must be an Esri JSON mapping, a GeoJSON "
            "geometry, or an object exposing __geo_interface__ (e.g. shapely)."
        )

    # GeoJSON geometry: has a "type" + "coordinates".
    if "type" in geometry and "coordinates" in geometry:
        return _geojson_geometry_to_esri(geometry), _GEOJSON_TO_ESRI_TYPE.get(
            str(geometry.get("type")), "esriGeometryPolygon"
        )

    if default_type is not None:
        return dict(geometry), default_type
    return dict(geometry), _esri_geometry_type(geometry)


def _esri_geometry_type(geometry: Mapping[str, Any]) -> str:
    if "x" in geometry and "y" in geometry:
        return "esriGeometryPoint"
    if "rings" in geometry:
        return "esriGeometryPolygon"
    if "paths" in geometry:
        return "esriGeometryPolyline"
    if "points" in geometry:
        return "esriGeometryMultipoint"
    if {"xmin", "ymin", "xmax", "ymax"} <= set(geometry):
        return "esriGeometryEnvelope"
    raise ValueError(
        "Could not infer the Esri geometry type from the spatial_filter geometry; "
        "provide an explicit 'geometryType' in the spatial_filter mapping."
    )


def _geojson_geometry_to_esri(geometry: Mapping[str, Any]) -> dict[str, Any]:
    gtype = str(geometry.get("type"))
    coords = geometry.get("coordinates")
    if gtype == "Point":
        point = list(coords or [])
        result: dict[str, Any] = {"x": point[0], "y": point[1]}
        if len(point) > _XY_LEN:
            result["z"] = point[_XY_LEN]
        return result
    if gtype == "MultiPoint":
        return {"points": [list(c) for c in coords or []]}
    if gtype == "LineString":
        return {"paths": [[list(c) for c in coords or []]]}
    if gtype == "MultiLineString":
        return {"paths": [[list(c) for c in line] for line in coords or []]}
    if gtype == "Polygon":
        return {"rings": [[list(c) for c in ring] for ring in coords or []]}
    if gtype == "MultiPolygon":
        rings: list[list[list[float]]] = []
        for polygon in coords or []:
            for ring in polygon:
                rings.append([list(c) for c in ring])
        return {"rings": rings}
    raise ValueError(f"Unsupported GeoJSON geometry type: {gtype!r}.")


# ---------------------------------------------------------------------------
# Spatial-filter mapping → GeoServices params
# ---------------------------------------------------------------------------


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _sr_wkid(value: Any) -> int | str | None:
    """Extract a wkid (or wkt string) from an SR mapping / int / string."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        wkid = _first(value, "wkid", "latestWkid", "latest_wkid")
        if wkid is not None:
            return int(wkid) if not isinstance(wkid, bool) else None
        wkt = value.get("wkt")
        return str(wkt) if wkt else None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | str):
        return value
    return str(value)


def spatial_filter_params(spatial_filter: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a spatial-filter mapping into GeoServices ``query`` params.

    Recognised keys (case-insensitive aliases accepted):

    * ``geometry`` — Esri JSON / GeoJSON / ``__geo_interface__`` geometry (required).
    * ``relationship`` / ``spatial_relationship`` / ``relation`` — relationship
      token (default ``"intersects"``). See :data:`_SPATIAL_REL`.
    * ``geometry_type`` / ``geometryType`` — explicit Esri geometry type
      override (otherwise inferred from the geometry).
    * ``in_sr`` / ``sr`` / ``spatial_reference`` — input spatial reference
      (EPSG/wkid; defaults to the geometry's embedded ``spatialReference`` or 4326).
    * ``distance`` and ``units`` / ``distance_unit`` — distance-based filter
      (required when the relationship is ``within-distance``).
    """
    geometry_value = _first(spatial_filter, "geometry", "geom", "shape")
    explicit_type = _first(spatial_filter, "geometry_type", "geometryType")
    esri_geometry, inferred_type = coerce_geometry(geometry_value, default_type=explicit_type)
    geometry_type = explicit_type or inferred_type

    relationship = (
        _first(spatial_filter, "relationship", "spatial_relationship", "spatialRelationship", "relation")
        or "intersects"
    )
    spatial_rel = normalize_spatial_relationship(str(relationship))

    params: dict[str, Any] = {
        "geometry": json.dumps(esri_geometry, separators=(",", ":")),
        "geometryType": geometry_type,
        "spatialRel": spatial_rel,
    }

    in_sr = _sr_wkid(
        _first(spatial_filter, "in_sr", "inSR", "sr", "spatial_reference", "spatialReference")
    )
    if in_sr is None:
        in_sr = _sr_wkid(esri_geometry.get("spatialReference")) if isinstance(esri_geometry, Mapping) else None
    if in_sr is None:
        in_sr = 4326
    params["inSR"] = in_sr

    distance = _first(spatial_filter, "distance")
    units = _first(spatial_filter, "units", "distance_unit", "distanceUnit")
    if _is_distance_relationship(str(relationship)) and distance is None:
        raise ValueError("A 'within-distance' spatial filter requires a 'distance' value.")
    if distance is not None:
        params["distance"] = distance
        if units is not None:
            params["units"] = _distance_units(units)

    return params


_DISTANCE_UNITS = {
    "meters": "esriSRUnit_Meter",
    "meter": "esriSRUnit_Meter",
    "m": "esriSRUnit_Meter",
    "kilometers": "esriSRUnit_Kilometer",
    "kilometer": "esriSRUnit_Kilometer",
    "km": "esriSRUnit_Kilometer",
    "feet": "esriSRUnit_Foot",
    "foot": "esriSRUnit_Foot",
    "ft": "esriSRUnit_Foot",
    "miles": "esriSRUnit_StatuteMile",
    "mile": "esriSRUnit_StatuteMile",
    "mi": "esriSRUnit_StatuteMile",
}


def _distance_units(value: Any) -> str:
    text = str(value).strip()
    if text.startswith("esriSRUnit"):
        return text
    try:
        return _DISTANCE_UNITS[text.lower()]
    except KeyError as exc:
        supported = ", ".join(sorted(_DISTANCE_UNITS))
        raise ValueError(
            f"Unsupported distance unit {value!r}. Expected one of: {supported}."
        ) from exc


# ---------------------------------------------------------------------------
# Statistics / aggregation → GeoServices params
# ---------------------------------------------------------------------------

_STATISTIC_TYPES = frozenset({"count", "sum", "min", "max", "avg", "stddev", "var"})


def _statistic_definition(stat: Mapping[str, Any]) -> dict[str, Any]:
    stat_type = _first(stat, "statisticType", "statistic_type", "type")
    on_field = _first(stat, "onStatisticField", "on_statistic_field", "field", "on")
    out_name = _first(stat, "outStatisticFieldName", "out_statistic_field_name", "out", "as", "alias")
    if stat_type is None or on_field is None:
        raise ValueError(
            "Each out_statistics entry requires a 'statistic_type' and an 'on_statistic_field'."
        )
    normalized_type = str(stat_type).strip().lower()
    if normalized_type not in _STATISTIC_TYPES:
        supported = ", ".join(sorted(_STATISTIC_TYPES))
        raise ValueError(
            f"Unsupported statistic type {stat_type!r}. Expected one of: {supported}."
        )
    definition: dict[str, Any] = {
        "statisticType": normalized_type,
        "onStatisticField": str(on_field),
    }
    definition["outStatisticFieldName"] = str(out_name) if out_name else f"{normalized_type}_{on_field}"
    return definition


def statistics_params(
    *,
    out_statistics: Sequence[Mapping[str, Any]] | None = None,
    group_by: str | Sequence[str] | None = None,
    return_distinct_values: bool | None = None,
    return_count_only: bool | None = None,
) -> dict[str, Any]:
    """Translate statistics/aggregation inputs into GeoServices ``query`` params.

    Mirrors the arcpy / ArcGIS-API summary-statistics surface:

    * ``out_statistics`` → ``outStatistics`` (a JSON array of statistic defs).
    * ``group_by`` → ``groupByFieldsForStatistics`` (comma-joined).
    * ``return_distinct_values`` → ``returnDistinctValues``.
    * ``return_count_only`` → ``returnCountOnly``.
    """
    params: dict[str, Any] = {}
    if out_statistics:
        definitions = [_statistic_definition(stat) for stat in out_statistics]
        params["outStatistics"] = json.dumps(definitions, separators=(",", ":"))
    if group_by is not None:
        params["groupByFieldsForStatistics"] = (
            group_by if isinstance(group_by, str) else ",".join(str(field) for field in group_by)
        )
    if return_distinct_values:
        params["returnDistinctValues"] = "true"
    if return_count_only:
        params["returnCountOnly"] = "true"
    return params
