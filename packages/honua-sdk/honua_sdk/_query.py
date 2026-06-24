"""Shared feature query helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from .models import Feature, FeatureQuery, QueryFeature, QueryProtocol, normalize_protocol


def resolve_feature_query(
    source: str | FeatureQuery,
    *,
    protocol: QueryProtocol | None = None,
    layer_id: int | None = None,
    where: str | None = None,
    filter: str | None = None,
    bbox: str | Sequence[int | float] | None = None,
    fields: str | Sequence[str] | None = None,
    return_geometry: bool | None = None,
    page_size: int | None = None,
    limit: int | None = None,
    max_pages: int | None = None,
    extra_params: Mapping[str, Any] | None = None,
) -> FeatureQuery:
    if isinstance(source, FeatureQuery):
        merged_extra_params = dict(source.extra_params)
        if extra_params:
            merged_extra_params.update(extra_params)
        return replace(
            source,
            protocol=protocol if protocol is not None else source.protocol,
            layer_id=layer_id if layer_id is not None else source.layer_id,
            where=where if where is not None else source.where,
            filter=filter if filter is not None else source.filter,
            bbox=bbox if bbox is not None else source.bbox,
            fields=fields if fields is not None else source.fields,
            return_geometry=return_geometry if return_geometry is not None else source.return_geometry,
            page_size=page_size if page_size is not None else source.page_size,
            limit=limit if limit is not None else source.limit,
            max_pages=max_pages if max_pages is not None else source.max_pages,
            extra_params=merged_extra_params,
        )

    effective_protocol = protocol or "feature-server"
    effective_layer_id = layer_id
    if effective_layer_id is None and normalize_query_protocol(effective_protocol) == "feature-server":  # type: ignore[arg-type]
        effective_layer_id = 0

    return FeatureQuery(
        source=str(source),
        protocol=effective_protocol,
        layer_id=effective_layer_id,
        where=where,
        filter=filter,
        bbox=bbox,
        fields=fields,
        return_geometry=True if return_geometry is None else return_geometry,
        page_size=page_size,
        limit=limit,
        max_pages=max_pages,
        extra_params=dict(extra_params or {}),
    )


def normalize_query_protocol(value: QueryProtocol) -> str:
    normalized = normalize_protocol(value)
    aliases = {
        "geoservices-feature-service": "feature-server",
        "ogc-features": "ogc-features",
        "stac": "stac",
        "odata": "odata",
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError(
            "Unsupported query protocol. Expected one of: geoservices-feature-service, ogc-features, stac, odata."
        ) from exc


def field_list(value: str | Sequence[str] | None, *, wildcard: str | None = None) -> str | list[str] | None:
    if value is None:
        return wildcard
    if isinstance(value, str):
        if value == "*" and wildcard is None:
            return None
        return value
    values = [str(item) for item in value]
    if values == ["*"] and wildcard is None:
        return None
    return values


def field_text(value: str | Sequence[str] | None, *, wildcard: str | None = None) -> str | None:
    fields = field_list(value, wildcard=wildcard)
    if fields is None:
        return None
    if isinstance(fields, str):
        return fields
    return ",".join(fields)


def bbox_text(value: str | Sequence[int | float] | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return ",".join(str(item) for item in value)


def feature_server_extra_params(query: FeatureQuery) -> dict[str, Any]:
    params = dict(query.extra_params)
    if query.bbox is not None:
        bbox = _bbox_values(query.bbox)
        params.setdefault(
            "geometry",
            json.dumps(
                {
                    "xmin": bbox[0],
                    "ymin": bbox[1],
                    "xmax": bbox[2],
                    "ymax": bbox[3],
                    "spatialReference": {"wkid": 4326},
                },
                separators=(",", ":"),
            ),
        )
        params.setdefault("geometryType", "esriGeometryEnvelope")
        params.setdefault("spatialRel", "esriSpatialRelIntersects")
        params.setdefault("inSR", 4326)
    return params


def odata_layer_id(query: FeatureQuery) -> int | None:
    if query.layer_id is not None:
        return query.layer_id
    try:
        return int(query.source)
    except ValueError:
        return None


def query_filter(query: FeatureQuery) -> str | None:
    return query.filter if query.filter is not None else query.where


def query_page_size(query: FeatureQuery, default: int) -> int:
    return default if query.page_size is None else query.page_size


def query_max_pages(query: FeatureQuery, default: int) -> int:
    return default if query.max_pages is None else query.max_pages


def query_feature_from_feature_server(feature: Feature, *, source: str, protocol: str) -> QueryFeature:
    return QueryFeature(
        id=feature.object_id,
        properties=dict(feature.attributes),
        geometry=dict(feature.geometry) if feature.geometry is not None else None,
        protocol=protocol,
        source=source,
        raw=dict(feature.raw),
    )


def query_feature_from_geojson(feature: Mapping[str, Any], *, source: str, protocol: str) -> QueryFeature:
    properties = feature.get("properties")
    geometry = feature.get("geometry")
    return QueryFeature(
        id=_first_present(feature, "id", "ID", "objectid", "objectId", "ObjectId"),
        properties=dict(properties) if isinstance(properties, Mapping) else {},
        geometry=dict(geometry) if isinstance(geometry, Mapping) else None,
        protocol=protocol,
        source=source,
        raw=dict(feature),
    )


def query_feature_from_mapping(feature: Mapping[str, Any], *, source: str, protocol: str) -> QueryFeature:
    properties = dict(feature)
    geometry = _first_present(feature, "geometry", "Geometry", "shape", "Shape")
    for key in ("geometry", "Geometry", "shape", "Shape"):
        properties.pop(key, None)
    return QueryFeature(
        id=_first_present(feature, "id", "ID", "objectid", "objectId", "ObjectId"),
        properties=properties,
        geometry=dict(geometry) if isinstance(geometry, Mapping) else None,
        protocol=protocol,
        source=source,
        raw=dict(feature),
    )


def _bbox_values(value: str | Sequence[int | float]) -> tuple[float, float, float, float]:
    parts = value.split(",") if isinstance(value, str) else list(value)
    if len(parts) != 4:
        raise ValueError("bbox must contain exactly four values: minx, miny, maxx, maxy.")
    minx, miny, maxx, maxy = (float(part) for part in parts)
    return minx, miny, maxx, maxy


def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _coerce_total_count(raw_total: Any) -> int | None:
    """Coerce a server-reported total (``numberMatched``/``@odata.count``).

    Accepts a JSON integer, a whole-valued JSON float (e.g. ``1000.0`` — some
    servers emit totals as floats), or a digit string. ``bool`` is rejected
    (``True``/``False`` are not meaningful counts even though ``bool`` is an
    ``int`` subclass). Anything else yields ``None``.
    """
    if isinstance(raw_total, bool):
        return None
    if isinstance(raw_total, int):
        return raw_total
    if isinstance(raw_total, float):
        if raw_total.is_integer():
            return int(raw_total)
        return None
    if isinstance(raw_total, str) and raw_total.isdigit():
        return int(raw_total)
    return None


def ogc_pagination_signals(page: Mapping[str, Any] | None) -> tuple[int | None, bool]:
    """Extract ``(total_count, exceeded_transfer_limit)`` from an OGC/STAC page.

    OGC API - Features and STAC both expose ``numberMatched`` (the server's
    estimated total) and a ``links`` array. When a ``rel="next"`` link is
    present on the last page walked the caller is paginating against an
    incomplete result — that's our ``exceeded_transfer_limit`` signal for
    these protocols.
    """
    if page is None:
        return None, False
    raw_total = page.get("numberMatched") if isinstance(page, Mapping) else None
    total_count = _coerce_total_count(raw_total)
    exceeded = _has_next_link(page)
    return total_count, exceeded


def odata_pagination_signals(page: Mapping[str, Any] | None) -> tuple[int | None, bool]:
    """Extract ``(total_count, exceeded_transfer_limit)`` from an OData page.

    OData surfaces totals via ``@odata.count`` and pagination via
    ``@odata.nextLink``.
    """
    if page is None:
        return None, False
    raw_total = page.get("@odata.count") if isinstance(page, Mapping) else None
    total_count = _coerce_total_count(raw_total)
    exceeded = bool(page.get("@odata.nextLink")) if isinstance(page, Mapping) else False
    return total_count, exceeded


def odata_features_from_page(page: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Extract the ``value`` array from an OData page payload."""
    value = page.get("value") if isinstance(page, Mapping) else None
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def features_from_geojson_page(page: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Extract a list of GeoJSON-shaped features from a FeatureCollection page."""
    features = page.get("features") if isinstance(page, Mapping) else None
    if isinstance(features, list):
        return [item for item in features if isinstance(item, Mapping)]
    return []


def _has_next_link(payload: Mapping[str, Any]) -> bool:
    links = payload.get("links") if isinstance(payload, Mapping) else None
    if not isinstance(links, list):
        return False
    return any(
        isinstance(link, Mapping) and str(link.get("rel", "")).lower() == "next"
        for link in links
    )
