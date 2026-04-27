"""Typed models for core Honua SDK responses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


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
