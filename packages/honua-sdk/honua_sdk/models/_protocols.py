"""Canonical protocol and capability literals plus normalization helpers."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, TypeAlias

from ._helpers import _first_present

#: Canonical cross-SDK protocol identifier. Pass aliases through
#: :func:`normalize_protocol` to coerce them before storing in typed code paths.
Protocol: TypeAlias = Literal[
    "grpc",
    "geoservices-feature-service",
    "geoservices-map-service",
    "geoservices-image-service",
    "geoservices-geometry-service",
    "geoservices-gp-service",
    "ogc-features",
    "ogc-tiles",
    "ogc-maps",
    "stac",
    "wfs",
    "wms",
    "wmts",
    "odata",
    "maplibre-vector",
    "maplibre-raster",
    "maplibre-geojson",
]
#: Canonical cross-SDK capability identifier. Use :func:`normalize_capability`
#: to coerce snake_case or alias forms before passing into typed APIs.
Capability: TypeAlias = Literal[
    "query",
    "queryAggregate",
    "queryExtent",
    "queryObjectIds",
    "queryRelated",
    "applyEdits",
    "attachments",
    "render",
    "tiles",
    "sql",
    "stream",
    "pbf",
    "connect",
    "image",
    "geometry",
    "geoprocess",
    "processes",
]
QueryProtocol: TypeAlias = Protocol

PROTOCOLS = (
    "grpc",
    "geoservices-feature-service",
    "geoservices-map-service",
    "geoservices-image-service",
    "geoservices-geometry-service",
    "geoservices-gp-service",
    "ogc-features",
    "ogc-tiles",
    "ogc-maps",
    "stac",
    "wfs",
    "wms",
    "wmts",
    "odata",
    "maplibre-vector",
    "maplibre-raster",
    "maplibre-geojson",
)

PROTOCOL_ALIASES: Mapping[str, str] = {
    "feature-server": "geoservices-feature-service",
    "featureserver": "geoservices-feature-service",
    "feature-service": "geoservices-feature-service",
    "geoservices-featureserver": "geoservices-feature-service",
    "map-server": "geoservices-map-service",
    "mapserver": "geoservices-map-service",
    "image-server": "geoservices-image-service",
    "imageserver": "geoservices-image-service",
    "geometry-server": "geoservices-geometry-service",
    "geometryserver": "geoservices-geometry-service",
    "gp-server": "geoservices-gp-service",
    "gpserver": "geoservices-gp-service",
    "ogc-api-features": "ogc-features",
    "ogc_features": "ogc-features",
    "odata-v4": "odata",
    "wfs-2.0": "wfs",
    "wms-1.3.0": "wms",
    "wmts-1.0.0": "wmts",
}

CAPABILITIES = (
    "query",
    "queryAggregate",
    "queryExtent",
    "queryObjectIds",
    "queryRelated",
    "applyEdits",
    "attachments",
    "render",
    "tiles",
    "sql",
    "stream",
    "pbf",
    "connect",
    "image",
    "geometry",
    "geoprocess",
    "processes",
)

DEFAULT_CAPABILITIES: Mapping[str, tuple[str, ...]] = {
    "grpc": (
        "query",
        "queryAggregate",
        "queryExtent",
        "queryObjectIds",
        "applyEdits",
        "stream",
    ),
    "geoservices-feature-service": (
        "query",
        "queryAggregate",
        "queryExtent",
        "queryObjectIds",
        "queryRelated",
        "applyEdits",
        "attachments",
        "sql",
        "stream",
        "pbf",
        "connect",
    ),
    "geoservices-map-service": (
        "query",
        "queryAggregate",
        "queryExtent",
        "queryObjectIds",
        "queryRelated",
        "render",
        "tiles",
        "sql",
        "stream",
    ),
    "geoservices-image-service": (
        "query",
        "queryExtent",
        "queryObjectIds",
        "image",
        "render",
        "tiles",
        "connect",
    ),
    "geoservices-geometry-service": ("geometry", "connect"),
    "geoservices-gp-service": ("geoprocess", "connect"),
    "ogc-features": ("query", "queryObjectIds", "applyEdits", "stream"),
    "ogc-tiles": ("render", "tiles"),
    "ogc-maps": ("render",),
    "stac": ("query", "queryObjectIds", "stream"),
    "wfs": ("query", "queryExtent", "queryObjectIds", "applyEdits", "stream"),
    "wms": ("render", "tiles", "query"),
    "wmts": ("render", "tiles"),
    "odata": ("query", "queryObjectIds", "stream", "applyEdits"),
    "maplibre-vector": ("render", "tiles"),
    "maplibre-raster": ("render", "tiles"),
    "maplibre-geojson": ("render",),
}

_NORMALIZED_PROTOCOL_ALIASES = {key.lower().replace("_", "-"): value for key, value in PROTOCOL_ALIASES.items()}
_CAPABILITY_BY_KEY = {
    "".join(ch for ch in capability.lower() if ch.isalnum()): capability for capability in CAPABILITIES
}


def normalize_protocol(value: Protocol | str) -> str:
    """Return the canonical cross-SDK protocol id for a protocol name or alias.

    Accepts any string at runtime — the :data:`Protocol` ``Literal`` is the
    strict static type, and this helper is the explicit validate/coerce
    boundary for arbitrary input (alias resolution, snake_case, case
    folding). Raises :class:`ValueError` for unknown protocols.
    """
    normalized = str(value).strip().lower().replace("_", "-")
    protocol = _NORMALIZED_PROTOCOL_ALIASES.get(normalized, normalized)
    if protocol in PROTOCOLS:
        return protocol
    expected = ", ".join(sorted(PROTOCOLS))
    raise ValueError(f"Unsupported protocol {value!r}. Expected one of: {expected}.")


def normalize_capability(value: Capability | str) -> str:
    """Return the canonical cross-SDK capability id for a capability name.

    Accepts any string at runtime — :data:`Capability` is a strict
    ``Literal``; this helper is the explicit validate/coerce boundary
    that resolves snake_case and case variants. Raises :class:`ValueError`
    for unknown capabilities.
    """
    key = "".join(ch for ch in str(value).strip().lower() if ch.isalnum())
    try:
        return _CAPABILITY_BY_KEY[key]
    except KeyError as exc:
        expected = ", ".join(sorted(CAPABILITIES))
        raise ValueError(f"Unsupported capability {value!r}. Expected one of: {expected}.") from exc


def capability_set(values: Iterable[Capability | str] | None) -> frozenset[str]:
    """Normalize a capability iterable into canonical capability ids."""
    if values is None:
        return frozenset()
    return frozenset(normalize_capability(value) for value in values)


def default_capabilities(protocol: Protocol | str) -> frozenset[str]:
    """Return the default capabilities advertised for a canonical protocol id."""
    return frozenset(DEFAULT_CAPABILITIES.get(normalize_protocol(protocol), ()))


def _capability_flags(value: Any) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        return {}
    return {_normalize_advertised_name(str(key)): bool(flag) for key, flag in value.items()}


def _capability_names(value: Any) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        if isinstance(value, Mapping):
            return {
                _normalize_advertised_name(str(key))
                for key, enabled in value.items()
                if _capability_enabled(enabled)
            }
        return set()

    names: set[str] = set()
    for item in value:
        if isinstance(item, str):
            names.add(_normalize_advertised_name(item))
            continue
        if not isinstance(item, Mapping) or not _capability_enabled(item):
            continue
        name = _first_present(item, "id", "name", "protocol", "surface")
        if name is not None:
            names.add(_normalize_advertised_name(str(name)))
    return names


def _capability_enabled(value: Any) -> bool:
    if isinstance(value, Mapping):
        enabled = value.get("enabled", True)
        return bool(enabled)
    return bool(value)


def _normalize_capability_name(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-").replace("/", "-").replace(" ", "-")
    aliases = {
        "feature-server": "featureserver",
        "feature-service": "featureserver",
        "geo-services": "geoservices",
        "geocode-server": "geocodeserver",
        "geocoding": "geocodeserver",
        "geometry-server": "geometryserver",
        "image-server": "imageserver",
        "map-server": "mapserver",
        "ogc-features": "ogc-features",
        "ogc-api-features": "ogc-features",
        "ogc-maps": "ogc-maps",
        "ogc-api-maps": "ogc-maps",
        "ogc-tiles": "ogc-tiles",
        "ogc-api-tiles": "ogc-tiles",
        "ogc-coverages": "ogc-coverages",
        "ogc-api-coverages": "ogc-coverages",
        "ogc-processes": "ogc-processes",
        "ogc-api-processes": "ogc-processes",
    }
    return aliases.get(normalized, normalized)


def _normalize_advertised_name(value: str) -> str:
    try:
        return normalize_protocol(value)
    except ValueError:
        pass
    try:
        return normalize_capability(value)
    except ValueError:
        return _normalize_capability_name(value)


def _normalized_surface_keys(value: str) -> set[str]:
    keys = {_normalize_capability_name(value)}
    with contextlib.suppress(ValueError):
        keys.add(normalize_protocol(value))
    with contextlib.suppress(ValueError):
        keys.add(normalize_capability(value))
    return keys
