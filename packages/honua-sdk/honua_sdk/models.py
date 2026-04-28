"""Typed models for core Honua SDK responses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

QueryProtocol: TypeAlias = Literal["feature-server", "featureserver", "ogc-features", "ogc_features", "stac", "odata"] | str


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
                    protocols.add(_normalize_capability_name(service_type))

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
        key = _normalize_capability_name(capability)
        return key in self.protocols or bool(self.features.get(key, False))


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
    return {_normalize_capability_name(str(key)): bool(flag) for key, flag in value.items()}


def _capability_names(value: Any) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        if isinstance(value, Mapping):
            return {
                _normalize_capability_name(str(key))
                for key, enabled in value.items()
                if _capability_enabled(enabled)
            }
        return set()

    names: set[str] = set()
    for item in value:
        if isinstance(item, str):
            names.add(_normalize_capability_name(item))
            continue
        if not isinstance(item, Mapping) or not _capability_enabled(item):
            continue
        name = _first_present(item, "id", "name", "protocol", "surface")
        if name is not None:
            names.add(_normalize_capability_name(str(name)))
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
