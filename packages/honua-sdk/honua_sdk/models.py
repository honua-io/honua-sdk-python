"""Typed models for core Honua SDK responses."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

Protocol: TypeAlias = Literal[
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
] | str
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
] | str
QueryProtocol: TypeAlias = Protocol

PROTOCOLS = (
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
_CAPABILITY_BY_KEY = {"".join(ch for ch in capability.lower() if ch.isalnum()): capability for capability in CAPABILITIES}


def normalize_protocol(value: Protocol) -> str:
    """Return the canonical cross-SDK protocol id for a protocol name or alias."""
    normalized = str(value).strip().lower().replace("_", "-")
    protocol = _NORMALIZED_PROTOCOL_ALIASES.get(normalized, normalized)
    if protocol in PROTOCOLS:
        return protocol
    expected = ", ".join(sorted(PROTOCOLS))
    raise ValueError(f"Unsupported protocol {value!r}. Expected one of: {expected}.")


def normalize_capability(value: Capability) -> str:
    """Return the canonical cross-SDK capability id for a capability name."""
    key = "".join(ch for ch in str(value).strip().lower() if ch.isalnum())
    try:
        return _CAPABILITY_BY_KEY[key]
    except KeyError as exc:
        expected = ", ".join(sorted(CAPABILITIES))
        raise ValueError(f"Unsupported capability {value!r}. Expected one of: {expected}.") from exc


def capability_set(values: Iterable[Capability] | None) -> frozenset[str]:
    """Normalize a capability iterable into canonical capability ids."""
    if values is None:
        return frozenset()
    return frozenset(normalize_capability(value) for value in values)


def default_capabilities(protocol: Protocol) -> frozenset[str]:
    """Return the default capabilities advertised for a canonical protocol id."""
    return frozenset(DEFAULT_CAPABILITIES.get(normalize_protocol(protocol), ()))


@dataclass(frozen=True)
class ServiceSummary:
    """GeoServices catalog service summary."""

    name: str
    type: str | None = None
    url: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ServiceSummary":
        return cls(
            name=str(payload.get("name") or payload.get("serviceName") or ""),
            type=_optional_str(payload.get("type")),
            url=_optional_str(payload.get("url")),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class DataPlaneCapabilities:
    """Data-plane capability discovery result."""

    server_version: str | None = None
    release_channel: str | None = None
    protocols: frozenset[str] = frozenset()
    features: Mapping[str, bool] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DataPlaneCapabilities":
        features = _capability_flags(_first_present(payload, "features", "featureFlags"))
        compatibility = payload.get("compatibility")
        if isinstance(compatibility, Mapping):
            features = {**_capability_flags(compatibility.get("features")), **features}

        return cls(
            server_version=_optional_str(_first_present(payload, "serverVersion", "server_version", "version")),
            release_channel=_optional_str(_first_present(payload, "releaseChannel", "release_channel", "channel")),
            protocols=frozenset(_capability_names(_first_present(payload, "protocols", "dataProtocols", "surfaces"))),
            features=features,
            raw=dict(payload),
        )

    @classmethod
    def from_discovery(
        cls,
        *,
        readiness: Mapping[str, Any],
        catalog: Mapping[str, Any],
    ) -> "DataPlaneCapabilities":
        protocols: set[str] = set(_capability_names(readiness.get("protocols")))
        services = catalog.get("services")
        if isinstance(services, Sequence) and not isinstance(services, str):
            protocols.add("geoservices")
            for service in services:
                if not isinstance(service, Mapping):
                    continue
                service_type = _optional_str(service.get("type"))
                if service_type is not None:
                    protocols.add(_normalize_advertised_name(service_type))

        return cls(
            server_version=_optional_str(_first_present(readiness, "serverVersion", "server_version", "version")),
            release_channel=_optional_str(_first_present(readiness, "releaseChannel", "release_channel", "channel")),
            protocols=frozenset(protocols),
            features={
                "readiness": bool(readiness),
                "service-catalog": isinstance(services, Sequence) and not isinstance(services, str),
            },
            raw={"readiness": dict(readiness), "catalog": dict(catalog)},
        )

    def supports(self, capability: str) -> bool:
        """Return whether a named protocol or feature is advertised."""
        keys = _normalized_surface_keys(capability)
        return any(key in self.protocols or bool(self.features.get(key, False)) for key in keys)


@dataclass(frozen=True)
class SourceLocator:
    """Protocol-specific source address using Pythonic field names."""

    service_id: str | None = None
    layer_id: int | None = None
    collection_id: str | None = None
    entity_set: str | None = None
    type_name: str | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SourceLocator":
        return cls(
            service_id=_optional_str(_first_present(payload, "serviceId", "service_id")),
            layer_id=_optional_int(_first_present(payload, "layerId", "layer_id")),
            collection_id=_optional_str(_first_present(payload, "collectionId", "collection_id")),
            entity_set=_optional_str(_first_present(payload, "entitySet", "entity_set")),
            type_name=_optional_str(_first_present(payload, "typeName", "type_name")),
        )


@dataclass(frozen=True)
class SourceDescriptor:
    """Cross-SDK source description used by the source facade."""

    id: str
    protocol: Protocol
    locator: SourceLocator = field(default_factory=SourceLocator)
    capabilities: frozenset[str] = field(default_factory=frozenset)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        protocol = normalize_protocol(self.protocol)
        capabilities = capability_set(self.capabilities) or default_capabilities(protocol)
        object.__setattr__(self, "protocol", protocol)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "raw", dict(self.raw))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SourceDescriptor":
        locator = payload.get("locator")
        return cls(
            id=str(payload.get("id") or ""),
            protocol=_optional_str(payload.get("protocol")) or "geoservices-feature-service",
            locator=SourceLocator.from_dict(locator) if isinstance(locator, Mapping) else SourceLocator(),
            capabilities=capability_set(_sequence_value(payload.get("capabilities"))),
            raw=dict(payload),
        )

    def supports(self, capability: Capability) -> bool:
        """Return whether the source descriptor advertises a capability."""
        return normalize_capability(capability) in self.capabilities


@dataclass(frozen=True)
class Pagination:
    """Pagination options shared by queryable source protocols."""

    limit: int | None = None
    page_size: int | None = None
    max_pages: int | None = None
    offset: int | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Pagination":
        return cls(
            limit=_optional_int(payload.get("limit")),
            page_size=_optional_int(_first_present(payload, "pageSize", "page_size")),
            max_pages=_optional_int(_first_present(payload, "maxPages", "max_pages")),
            offset=_optional_int(payload.get("offset")),
        )


@dataclass(frozen=True)
class Query:
    """Cross-SDK query model with Pythonic field names."""

    where: str | None = None
    spatial_filter: Mapping[str, Any] | None = None
    bbox: str | Sequence[int | float] | None = None
    out_fields: str | Sequence[str] | None = None
    order_by: str | Sequence[str] | None = None
    pagination: Pagination = field(default_factory=Pagination)
    aggregation: Mapping[str, Any] | None = None
    return_geometry: bool = True
    out_sr: int | str | None = None
    extra_params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        pagination = self.pagination
        if isinstance(pagination, Mapping):
            pagination = Pagination.from_dict(pagination)
        object.__setattr__(self, "pagination", pagination)
        object.__setattr__(self, "spatial_filter", dict(self.spatial_filter) if self.spatial_filter else None)
        object.__setattr__(self, "aggregation", dict(self.aggregation) if self.aggregation else None)
        object.__setattr__(self, "extra_params", dict(self.extra_params))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Query":
        pagination = _first_present(payload, "pagination", "page")
        return cls(
            where=_optional_str(payload.get("where")),
            spatial_filter=_mapping_value(_first_present(payload, "spatialFilter", "spatial_filter")),
            bbox=_first_present(payload, "bbox", "boundingBox", "bounding_box"),
            out_fields=_first_present(payload, "outFields", "out_fields", "fields"),
            order_by=_first_present(payload, "orderBy", "order_by"),
            pagination=Pagination.from_dict(pagination) if isinstance(pagination, Mapping) else Pagination(),
            aggregation=_mapping_value(payload.get("aggregation")),
            return_geometry=bool(_first_present(payload, "returnGeometry", "return_geometry"))
            if _first_present(payload, "returnGeometry", "return_geometry") is not None
            else True,
            out_sr=_first_present(payload, "outSr", "out_sr"),
            extra_params=_mapping_value(_first_present(payload, "extraParams", "extra_params")) or {},
        )

    @property
    def limit(self) -> int | None:
        return self.pagination.limit

    @property
    def page_size(self) -> int | None:
        return self.pagination.page_size

    @property
    def max_pages(self) -> int | None:
        return self.pagination.max_pages

    @property
    def offset(self) -> int | None:
        return self.pagination.offset


@dataclass(frozen=True)
class DegradedReason:
    """Reason a result used a lower-fidelity path for a requested capability."""

    capability: Capability
    protocol: Protocol
    source_id: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability", normalize_capability(self.capability))
        object.__setattr__(self, "protocol", normalize_protocol(self.protocol))


@dataclass(frozen=True)
class Result:
    """Collected result returned by the canonical Source/Query API."""

    features: tuple["QueryFeature", ...] = ()
    exceeded_transfer_limit: bool = False
    total_count: int | None = None
    aggregate_rows: tuple[Mapping[str, Any], ...] = ()
    extent: Mapping[str, Any] | None = None
    fields: tuple[Mapping[str, Any], ...] = ()
    degraded: tuple[DegradedReason, ...] = ()
    protocol: str = ""
    source_id: str = ""
    query: Query | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", tuple(self.features))
        object.__setattr__(self, "aggregate_rows", tuple(dict(row) for row in self.aggregate_rows))
        object.__setattr__(self, "fields", tuple(dict(field) for field in self.fields))
        object.__setattr__(self, "extent", dict(self.extent) if self.extent is not None else None)
        object.__setattr__(self, "degraded", tuple(self.degraded))
        object.__setattr__(self, "raw", dict(self.raw))


@dataclass(frozen=True)
class Feature:
    """FeatureServer feature with attributes and optional geometry."""

    attributes: Mapping[str, Any]
    geometry: Mapping[str, Any] | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Feature":
        attributes = payload.get("attributes")
        geometry = payload.get("geometry")
        return cls(
            attributes=dict(attributes) if isinstance(attributes, Mapping) else {},
            geometry=dict(geometry) if isinstance(geometry, Mapping) else None,
            raw=dict(payload),
        )

    @property
    def object_id(self) -> int | None:
        for key in ("objectid", "objectId", "OBJECTID"):
            value = self.attributes.get(key)
            if value is not None:
                return int(value)
        return None


@dataclass(frozen=True)
class FeatureSet:
    """Typed FeatureServer query response."""

    features: tuple[Feature, ...]
    fields: tuple[Mapping[str, Any], ...] = ()
    geometry_type: str | None = None
    spatial_reference: Mapping[str, Any] | None = None
    exceeded_transfer_limit: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FeatureSet":
        raw_features = payload.get("features")
        raw_fields = payload.get("fields")
        spatial_reference = payload.get("spatialReference")
        return cls(
            features=tuple(
                Feature.from_dict(feature)
                for feature in raw_features or []
                if isinstance(feature, Mapping)
            ),
            fields=tuple(dict(field) for field in raw_fields or [] if isinstance(field, Mapping)),
            geometry_type=_optional_str(payload.get("geometryType")),
            spatial_reference=dict(spatial_reference) if isinstance(spatial_reference, Mapping) else None,
            exceeded_transfer_limit=bool(payload.get("exceededTransferLimit", False)),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class FeatureQuery:
    """Protocol-neutral feature query request."""

    source: str
    protocol: QueryProtocol = "feature-server"
    layer_id: int | None = None
    where: str | None = None
    filter: str | None = None
    bbox: str | Sequence[int | float] | None = None
    fields: str | Sequence[str] | None = None
    return_geometry: bool = True
    page_size: int | None = None
    limit: int | None = None
    max_pages: int | None = None
    extra_params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryFeature:
    """Protocol-neutral feature returned by the shared query API."""

    id: str | int | None
    properties: Mapping[str, Any]
    geometry: Mapping[str, Any] | None = None
    protocol: str = ""
    source: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureQueryResult:
    """Collected result returned by the shared query API."""

    features: tuple[QueryFeature, ...]
    protocol: str
    source: str
    query: FeatureQuery


@dataclass(frozen=True)
class EditOperationResult:
    """One add, update, or delete result from applyEdits."""

    success: bool
    object_id: int | None = None
    global_id: str | None = None
    error: Mapping[str, Any] | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EditOperationResult":
        return cls(
            success=bool(payload.get("success", False)),
            object_id=_optional_int(_first_present(payload, "objectId", "objectid")),
            global_id=_optional_str(_first_present(payload, "globalId", "globalid")),
            error=dict(payload["error"]) if isinstance(payload.get("error"), Mapping) else None,
            raw=dict(payload),
        )


@dataclass(frozen=True)
class ApplyEditsResult:
    """Typed applyEdits response grouped by operation."""

    add_results: tuple[EditOperationResult, ...] = ()
    update_results: tuple[EditOperationResult, ...] = ()
    delete_results: tuple[EditOperationResult, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ApplyEditsResult":
        return cls(
            add_results=_edit_results(payload.get("addResults")),
            update_results=_edit_results(payload.get("updateResults")),
            delete_results=_edit_results(payload.get("deleteResults")),
            raw=dict(payload),
        )

    @property
    def all_succeeded(self) -> bool:
        results = [*self.add_results, *self.update_results, *self.delete_results]
        return bool(results) and all(result.success for result in results)


def _edit_results(value: Any) -> tuple[EditOperationResult, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    return tuple(EditOperationResult.from_dict(item) for item in value if isinstance(item, Mapping))


def _sequence_value(value: Any) -> Sequence[Any] | None:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return value
    return None


def _mapping_value(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


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
    try:
        keys.add(normalize_protocol(value))
    except ValueError:
        pass
    try:
        keys.add(normalize_capability(value))
    except ValueError:
        pass
    return keys
