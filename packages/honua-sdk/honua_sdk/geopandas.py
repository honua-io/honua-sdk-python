"""GeoPandas integration for converting geospatial responses to GeoDataFrames.

This module requires the optional ``geopandas`` extra::

    pip install honua-sdk[geopandas]
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

try:
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import (
        LinearRing,
        MultiLineString,
        MultiPoint,
        Point,
        Polygon,
    )
    from shapely.geometry import (
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
_GEOJSON_DEFAULT_CRS = "EPSG:4326"


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


def _crs_from_geojson(feature_collection: Mapping[str, Any]) -> str | None:
    """Derive a CRS string from a GeoJSON feature collection."""
    raw_crs = feature_collection.get("crs") or feature_collection.get("coordRefSys")
    if raw_crs is None:
        return _GEOJSON_DEFAULT_CRS

    if isinstance(raw_crs, str):
        return _normalize_geojson_crs_identifier(raw_crs)

    if isinstance(raw_crs, Mapping):
        properties = raw_crs.get("properties")
        if isinstance(properties, Mapping):
            for key in ("name", "href", "code"):
                value = properties.get(key)
                if isinstance(value, str):
                    return _normalize_geojson_crs_identifier(value)

        for key in ("name", "href", "code"):
            value = raw_crs.get(key)
            if isinstance(value, str):
                return _normalize_geojson_crs_identifier(value)

    return None


def _normalize_geojson_crs_identifier(identifier: str) -> str | None:
    value = identifier.strip()
    if not value:
        return None

    upper_value = value.upper()
    if upper_value in {"CRS84", "OGC:CRS84"} or upper_value.endswith(("/CRS84", ":CRS84")):
        return _GEOJSON_DEFAULT_CRS

    parts = [part for part in re.split(r"[:/]+", value) if part]
    for idx, part in enumerate(parts):
        if part.upper() == "EPSG":
            epsg_codes = [candidate for candidate in parts[idx + 1 :] if candidate.isdigit()]
            if epsg_codes:
                return f"EPSG:{epsg_codes[-1]}"

    return value


# ---------------------------------------------------------------------------
# Esri JSON geometry -> Shapely
# ---------------------------------------------------------------------------


def _esri_geometry_to_shapely(geom: dict[str, Any] | None) -> Any:  # noqa: PLR0911, PLR0912 -- geometry type dispatch
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
            # Hole - attach to most recent exterior
            elif holes_for:
                holes_for[-1].append(coords)

        if not exteriors:
            return None

        if len(exteriors) == 1:
            return Polygon(exteriors[0], holes_for[0])

        from shapely.geometry import MultiPolygon

        return MultiPolygon(
            [
                (ext, holes)
                for ext, holes in zip(exteriors, holes_for, strict=True)
            ]
        )

    return None


# ---------------------------------------------------------------------------
# Shapely -> Esri JSON geometry
# ---------------------------------------------------------------------------


def _shapely_to_esri_geometry(geom: Any) -> dict[str, Any] | None:  # noqa: PLR0911 -- geometry type dispatch
    """Convert a Shapely geometry to an Esri JSON geometry dict.

    Returns ``None`` when *geom* is ``None``.
    """
    if geom is None:
        return None

    from shapely.geometry import (
        LineString,
    )
    from shapely.geometry import (
        MultiLineString as _MLS,
    )
    from shapely.geometry import (
        MultiPoint as _MP,
    )
    from shapely.geometry import (
        MultiPolygon as _MPoly,
    )
    from shapely.geometry import (
        Point as _Pt,
    )
    from shapely.geometry import (
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
) -> gpd.GeoDataFrame:
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


def ogc_features_to_geodataframe(
    response: dict[str, Any],
) -> gpd.GeoDataFrame:
    """Convert an OGC API Features GeoJSON response to a GeoDataFrame.

    Parameters
    ----------
    response:
        A GeoJSON ``FeatureCollection`` dict, such as the response from
        ``HonuaOgcFeatureCollection.items``.

    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame with feature ``properties`` as columns, a
        ``geometry`` column built from GeoJSON geometries, top-level
        feature ``id`` values preserved when they do not collide with
        property names, and CRS set from GeoJSON CRS metadata when
        present. GeoJSON responses without explicit CRS metadata default
        to ``EPSG:4326``.
    """
    return _geojson_feature_collection_to_geodataframe(
        response,
        feature_fields=("id",),
    )


def stac_items_to_geodataframe(
    response: dict[str, Any],
) -> gpd.GeoDataFrame:
    """Convert a STAC ItemCollection or search response to a GeoDataFrame.

    Parameters
    ----------
    response:
        A STAC ``ItemCollection`` or search result dict. STAC item
        collections and search results are GeoJSON ``FeatureCollection``
        objects whose features are STAC Items.

    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame with item ``properties`` as columns, a
        ``geometry`` column built from item geometries, and common STAC
        item fields such as ``id``, ``collection``, ``bbox``, ``assets``,
        and item ``links`` preserved when they do not collide with
        property names. STAC geometries are treated as ``EPSG:4326`` when
        no explicit CRS metadata is present.
    """
    return _geojson_feature_collection_to_geodataframe(
        response,
        feature_fields=(
            "id",
            "collection",
            "bbox",
            "assets",
            "links",
            "stac_version",
            "stac_extensions",
        ),
    )


def _geojson_feature_collection_to_geodataframe(
    feature_collection: Mapping[str, Any],
    *,
    feature_fields: tuple[str, ...],
) -> gpd.GeoDataFrame:
    _ensure_deps()

    rows: list[dict[str, Any]] = []
    geometries: list[Any] = []

    for feature in feature_collection.get("features", []):
        properties = feature.get("properties")
        row = dict(properties) if isinstance(properties, Mapping) else {}

        for field in feature_fields:
            if field in feature and field not in row:
                row[field] = feature[field]

        geometry = feature.get("geometry")
        rows.append(row)
        geometries.append(_shape(geometry) if geometry else None)

    frame = pd.DataFrame(rows, dtype=object)
    gdf = gpd.GeoDataFrame(frame, geometry=geometries)
    crs = _crs_from_geojson(feature_collection)
    if crs is not None:
        gdf = gdf.set_crs(crs)

    return gdf


def geodataframe_to_features(
    gdf: gpd.GeoDataFrame,
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
        attrs = {col: _json_safe_value(row[col]) for col in attr_columns}
        geom_obj = row[gdf.geometry.name]
        esri_geom = _shapely_to_esri_geometry(geom_obj)
        feat: dict[str, Any] = {"attributes": attrs}
        if esri_geom is not None:
            feat["geometry"] = esri_geom
        features.append(feat)

    return features


def geodataframe_to_geojson(
    gdf: gpd.GeoDataFrame,
) -> dict[str, Any]:
    """Convert a GeoDataFrame to a GeoJSON ``FeatureCollection`` dict.

    This is the inverse of :func:`ogc_features_to_geodataframe` and is used to
    feed a GeoDataFrame into an OGC API Processes execution as an inline
    ``FeatureCollection`` (see
    :pymeth:`honua_sdk.geoprocessing.HonuaGeoprocessing.execute_dataframe`).

    Parameters
    ----------
    gdf:
        A GeoDataFrame whose non-geometry columns become each feature's
        ``properties`` and whose geometry column becomes a GeoJSON
        ``geometry``.

    Returns
    -------
    dict
        A GeoJSON ``FeatureCollection`` mapping with a ``features`` list.
    """
    _ensure_deps()

    from shapely.geometry import mapping as _mapping

    attr_columns = [col for col in gdf.columns if col != gdf.geometry.name]

    features: list[dict[str, Any]] = []
    for idx in range(len(gdf)):
        row = gdf.iloc[idx]
        properties = {col: _json_safe_value(row[col]) for col in attr_columns}
        geom_obj = row[gdf.geometry.name]
        feature: dict[str, Any] = {
            "type": "Feature",
            "properties": properties,
            "geometry": None if geom_obj is None or geom_obj.is_empty else _mapping(geom_obj),
        }
        features.append(feature)

    return {"type": "FeatureCollection", "features": features}


def _json_safe_value(value: Any) -> Any:  # noqa: PLR0911 -- value type dispatch
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value
