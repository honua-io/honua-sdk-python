"""GeoPandas integration for converting between Esri JSON and GeoDataFrames.

This module requires the optional ``geopandas`` extra::

    pip install honua-sdk[geopandas]
"""

from __future__ import annotations

from typing import Any

try:
    import geopandas as gpd
    from shapely.geometry import (
        LinearRing,
        MultiLineString,
        MultiPoint,
        Point,
        Polygon,
        shape as _shape,
    )

    _HAS_DEPS = True
except ImportError:
    _HAS_DEPS = False


def _ensure_deps() -> None:
    if not _HAS_DEPS:
        raise ImportError(
            "geopandas and shapely are required for GeoPandas integration. "
            "Install them with:  pip install honua-sdk[geopandas]"
        )


# ---------------------------------------------------------------------------
# Well-known Esri WKID -> EPSG mappings for spatial references that do not
# map 1:1 to an EPSG code.
# ---------------------------------------------------------------------------
_WKID_TO_EPSG: dict[int, str] = {
    102100: "EPSG:3857",
    102113: "EPSG:3857",
    3857: "EPSG:3857",
    4326: "EPSG:4326",
}


def _crs_from_spatial_reference(
    spatial_ref: dict[str, Any] | None,
) -> str | None:
    """Derive a CRS string from an Esri ``spatialReference`` dict.

    Returns ``None`` when the spatial reference is absent or cannot be mapped.
    """
    if not spatial_ref:
        return None

    for key in ("latestWkid", "wkid"):
        wkid = spatial_ref.get(key)
        if wkid is not None:
            if wkid in _WKID_TO_EPSG:
                return _WKID_TO_EPSG[wkid]
            return f"EPSG:{wkid}"

    return None


# ---------------------------------------------------------------------------
# Esri JSON geometry -> Shapely
# ---------------------------------------------------------------------------


def _esri_geometry_to_shapely(geom: dict[str, Any] | None) -> Any:
    """Convert a single Esri JSON geometry dict to a Shapely geometry.

    Returns ``None`` when *geom* is ``None`` or empty.
    """
    if geom is None:
        return None

    # --- Point ---
    if "x" in geom and "y" in geom:
        x = geom["x"]
        y = geom["y"]
        # Esri represents null-island-style "no geometry" as NaN coords.
        if x is None or y is None:
            return None
        return Point(x, y)

    # --- Multipoint ---
    if "points" in geom:
        pts = geom["points"]
        if not pts:
            return None
        return MultiPoint([Point(*p) for p in pts])

    # --- Polyline ---
    if "paths" in geom:
        paths = geom["paths"]
        if not paths:
            return None
        lines = [list(map(tuple, path)) for path in paths]
        if len(lines) == 1:
            from shapely.geometry import LineString

            return LineString(lines[0])
        return MultiLineString(lines)

    # --- Polygon ---
    if "rings" in geom:
        rings = geom["rings"]
        if not rings:
            return None
        # Esri JSON encodes polygons as a flat list of rings.  By spec,
        # exterior rings are clockwise (not CCW) and holes are CCW, but
        # many real-world services emit rings with inconsistent winding.
        # We use a robust heuristic: a ring whose absolute area is large
        # is exterior; a ring that is CCW (opposite of Esri's exterior
        # convention) AND follows an exterior ring is a hole.  The first
        # ring is always treated as an exterior.
        exteriors: list[list[tuple[float, ...]]] = []
        holes_for: list[list[list[tuple[float, ...]]]] = []

        for idx, ring_coords in enumerate(rings):
            coords = [tuple(c) for c in ring_coords]
            lr = LinearRing(coords)
            # First ring is always exterior.  Subsequent rings:
            # if CCW it's a hole (Esri convention), otherwise exterior.
            if idx == 0 or not lr.is_ccw:
                exteriors.append(coords)
                holes_for.append([])
            else:
                # Hole - attach to most recent exterior
                if holes_for:
                    holes_for[-1].append(coords)

        if not exteriors:
            return None

        if len(exteriors) == 1:
            return Polygon(exteriors[0], holes_for[0])

        from shapely.geometry import MultiPolygon

        return MultiPolygon(
            [
                (ext, holes)
                for ext, holes in zip(exteriors, holes_for)
            ]
        )

    return None


# ---------------------------------------------------------------------------
# Shapely -> Esri JSON geometry
# ---------------------------------------------------------------------------


def _shapely_to_esri_geometry(geom: Any) -> dict[str, Any] | None:
    """Convert a Shapely geometry to an Esri JSON geometry dict.

    Returns ``None`` when *geom* is ``None``.
    """
    if geom is None:
        return None

    from shapely.geometry import (
        LineString,
        MultiLineString as _MLS,
        MultiPoint as _MP,
        MultiPolygon as _MPoly,
        Point as _Pt,
        Polygon as _Poly,
    )

    if isinstance(geom, _Pt):
        return {"x": geom.x, "y": geom.y}

    if isinstance(geom, _MP):
        return {"points": [list(p.coords[0]) for p in geom.geoms]}

    if isinstance(geom, LineString):
        return {"paths": [[list(c) for c in geom.coords]]}

    if isinstance(geom, _MLS):
        return {"paths": [[list(c) for c in line.coords] for line in geom.geoms]}

    if isinstance(geom, _Poly):
        rings: list[list[list[float]]] = []
        # Exterior ring
        rings.append([list(c) for c in geom.exterior.coords])
        for interior in geom.interiors:
            rings.append([list(c) for c in interior.coords])
        return {"rings": rings}

    if isinstance(geom, _MPoly):
        rings_all: list[list[list[float]]] = []
        for poly in geom.geoms:
            rings_all.append([list(c) for c in poly.exterior.coords])
            for interior in poly.interiors:
                rings_all.append([list(c) for c in interior.coords])
        return {"rings": rings_all}

    raise TypeError(f"Unsupported geometry type: {type(geom).__name__}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def features_to_geodataframe(
    response: dict[str, Any],
) -> "gpd.GeoDataFrame":
    """Convert an Esri JSON feature-query response to a GeoDataFrame.

    Parameters
    ----------
    response:
        The raw dict returned by :pymeth:`HonuaClient.query_features`.
        Expected keys: ``features`` (list) and optionally
        ``spatialReference``.

    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame with attributes as columns, a ``geometry`` column
        built from the Esri JSON geometries, and the CRS set when a
        spatial reference is present.
    """
    _ensure_deps()

    features = response.get("features", [])
    spatial_ref = response.get("spatialReference")
    crs = _crs_from_spatial_reference(spatial_ref)

    rows: list[dict[str, Any]] = []
    geometries: list[Any] = []

    for feat in features:
        attrs = dict(feat.get("attributes", {}))
        geom = _esri_geometry_to_shapely(feat.get("geometry"))
        rows.append(attrs)
        geometries.append(geom)

    gdf = gpd.GeoDataFrame(rows, geometry=geometries)

    if crs is not None:
        gdf = gdf.set_crs(crs)

    return gdf


def geodataframe_to_features(
    gdf: "gpd.GeoDataFrame",
) -> list[dict[str, Any]]:
    """Convert a GeoDataFrame to a list of Esri JSON feature dicts.

    This is useful for preparing data for
    :pymeth:`HonuaClient.apply_edits`.

    Parameters
    ----------
    gdf:
        A GeoDataFrame whose non-geometry columns become ``attributes``
        and whose geometry column becomes an Esri JSON ``geometry``.

    Returns
    -------
    list[dict]
        A list of ``{"attributes": {...}, "geometry": {...}}`` dicts
        ready for the ``adds`` or ``updates`` parameter of
        ``apply_edits``.
    """
    _ensure_deps()

    attr_columns = [col for col in gdf.columns if col != gdf.geometry.name]

    features: list[dict[str, Any]] = []
    for idx in range(len(gdf)):
        row = gdf.iloc[idx]
        attrs = {col: row[col] for col in attr_columns}
        geom_obj = row[gdf.geometry.name]
        esri_geom = _shapely_to_esri_geometry(geom_obj)
        feat: dict[str, Any] = {"attributes": attrs}
        if esri_geom is not None:
            feat["geometry"] = esri_geom
        features.append(feat)

    return features
