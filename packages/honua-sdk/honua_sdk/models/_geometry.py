"""First-class geometry bridge from typed feature models to Shapely.

The typed feature models (:class:`~honua_sdk.models.Feature`,
:class:`~honua_sdk.models.QueryFeature`) carry geometry as a raw mapping in
either the Esri-JSON shape (GeoServices FeatureServer) or the GeoJSON shape
(OGC API Features / STAC). This module converts either shape to a Shapely
geometry and to a GeoJSON-mapping ``__geo_interface__``, giving GP tooling the
``feature.SHAPE`` / ArcGIS-API geometry-object ergonomic without forcing the
caller down to ``result.raw`` and the standalone ``geopandas`` bridge.

Shapely stays an **optional** dependency: importing this module never requires
it, and only :func:`geometry_to_shapely` raises a clear :class:`ImportError`
when Shapely is absent. The pure-dict ``__geo_interface__`` path
(:func:`geometry_to_geo_interface`) has no third-party dependency at all.

Both encodings preserve Z (and, for Esri, drop the trailing M ordinate so the
coordinate tuples stay 2-D/3-D rather than leaking an M value into the Z slot).
Esri polygon ring orientation follows the Esri convention — clockwise exterior
rings, counter-clockwise holes — and is mapped onto Shapely's exterior/interior
ring model robustly even when a service emits inconsistent winding.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from shapely.geometry.base import BaseGeometry

_SHAPELY_IMPORT_ERROR = (
    "shapely is required for geometry conversion. Install it with:  "
    "pip install honua-sdk[geopandas]"
)

#: A vertex carries a Z ordinate only when it has at least three components.
_MIN_3D_LEN = 3


def _require_shapely() -> Any:
    try:
        from shapely import geometry as shapely_geometry
    except ImportError as exc:  # pragma: no cover - exercised via importorskip
        raise ImportError(_SHAPELY_IMPORT_ERROR) from exc
    return shapely_geometry


def _is_esri_geometry(geom: Mapping[str, Any]) -> bool:
    """Heuristic: Esri-JSON geometries key on x/y, points, paths, or rings."""
    return any(key in geom for key in ("x", "rings", "paths", "points")) or (
        "y" in geom and "type" not in geom
    )


# ---------------------------------------------------------------------------
# Esri-JSON -> GeoJSON-mapping (``__geo_interface__``)
# ---------------------------------------------------------------------------


def _coords(point: Sequence[Any], *, has_z: bool) -> tuple[float, ...]:
    """Project an Esri vertex onto a 2-D or 3-D coordinate tuple.

    Esri vertices are ``[x, y]``, ``[x, y, z]``, ``[x, y, z, m]``, or
    ``[x, y, m]`` (with ``hasM`` but not ``hasZ``). The M ordinate is always
    dropped — GeoJSON has no M — and Z is kept only when the geometry header
    advertises ``hasZ``.
    """
    x = float(point[0])
    y = float(point[1])
    if has_z and len(point) >= _MIN_3D_LEN and point[2] is not None:
        return (x, y, float(point[2]))
    return (x, y)


def _esri_to_geo_interface(geom: Mapping[str, Any]) -> dict[str, Any] | None:  # noqa: PLR0911 - geometry dispatch
    has_z = bool(geom.get("hasZ"))

    if "x" in geom and "y" in geom:
        x = geom.get("x")
        y = geom.get("y")
        if x is None or y is None:
            return None
        coords = _coords([x, y, geom.get("z")] if has_z else [x, y], has_z=has_z)
        return {"type": "Point", "coordinates": list(coords)}

    if "points" in geom:
        points = geom.get("points") or []
        if not points:
            return None
        return {
            "type": "MultiPoint",
            "coordinates": [list(_coords(p, has_z=has_z)) for p in points],
        }

    if "paths" in geom:
        paths = geom.get("paths") or []
        if not paths:
            return None
        lines = [[list(_coords(v, has_z=has_z)) for v in path] for path in paths]
        if len(lines) == 1:
            return {"type": "LineString", "coordinates": lines[0]}
        return {"type": "MultiLineString", "coordinates": lines}

    if "rings" in geom:
        rings = geom.get("rings") or []
        if not rings:
            return None
        return _esri_rings_to_geo_interface(rings, has_z=has_z)

    return None


def _ring_signed_area(ring: Sequence[Sequence[Any]]) -> float:
    """Shoelace signed area in the X/Y plane (positive == counter-clockwise)."""
    area = 0.0
    count = len(ring)
    for idx in range(count):
        x1, y1 = float(ring[idx][0]), float(ring[idx][1])
        x2, y2 = float(ring[(idx + 1) % count][0]), float(ring[(idx + 1) % count][1])
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _esri_rings_to_geo_interface(
    rings: Sequence[Sequence[Sequence[Any]]],
    *,
    has_z: bool,
) -> dict[str, Any]:
    """Group flat Esri rings into Polygon/MultiPolygon GeoJSON coordinates.

    Esri encodes every ring of every polygon part in one flat list. By
    convention an exterior ring is clockwise (signed area < 0) and a hole is
    counter-clockwise (signed area > 0). The first ring is always treated as an
    exterior; each subsequent clockwise ring opens a new polygon part, and each
    counter-clockwise ring is attached as a hole of the most recent exterior.
    """
    polygons: list[list[list[list[float]]]] = []
    for idx, ring in enumerate(rings):
        coords = [list(_coords(v, has_z=has_z)) for v in ring]
        is_hole = idx != 0 and _ring_signed_area(ring) > 0
        if is_hole and polygons:
            polygons[-1].append(coords)
        else:
            polygons.append([coords])

    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


# ---------------------------------------------------------------------------
# GeoJSON normalization (drop M-only ordinates, keep Z)
# ---------------------------------------------------------------------------


def _geojson_geo_interface(geom: Mapping[str, Any]) -> dict[str, Any] | None:
    geom_type = geom.get("type")
    if not isinstance(geom_type, str):
        return None
    if geom_type == "GeometryCollection":
        members = geom.get("geometries") or []
        normalized = [_geojson_geo_interface(member) for member in members if isinstance(member, Mapping)]
        return {"type": "GeometryCollection", "geometries": [m for m in normalized if m is not None]}
    coordinates = geom.get("coordinates")
    if coordinates is None:
        return None
    return {"type": geom_type, "coordinates": coordinates}


# ---------------------------------------------------------------------------
# Public conversion entry points
# ---------------------------------------------------------------------------


def geometry_to_geo_interface(geom: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Normalize an Esri-JSON or GeoJSON geometry mapping to a GeoJSON mapping.

    Returns ``None`` for an absent or empty geometry. This is the pure-dict
    path behind ``Feature.__geo_interface__`` / ``QueryFeature.__geo_interface__``
    and requires no third-party dependency.
    """
    if not geom:
        return None
    if ("type" in geom and "coordinates" in geom) or geom.get("type") == "GeometryCollection":
        return _geojson_geo_interface(geom)
    if _is_esri_geometry(geom):
        return _esri_to_geo_interface(geom)
    # Fall back to GeoJSON interpretation when a ``type`` is present.
    if "type" in geom:
        return _geojson_geo_interface(geom)
    return None


def geometry_to_shapely(geom: Mapping[str, Any] | None) -> BaseGeometry | None:
    """Convert an Esri-JSON or GeoJSON geometry mapping to a Shapely geometry.

    Returns ``None`` for an absent or empty geometry. Raises :class:`ImportError`
    with an install hint when Shapely is not available.
    """
    geo = geometry_to_geo_interface(geom)
    if geo is None:
        return None
    shapely_geometry = _require_shapely()
    return shapely_geometry.shape(geo)
