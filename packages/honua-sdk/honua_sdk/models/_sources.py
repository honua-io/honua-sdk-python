"""Source addressing model dataclasses for the canonical source facade."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ._helpers import _first_present, _optional_int, _optional_str, _sequence_value
from ._protocols import (
    Capability,
    Protocol,
    capability_set,
    default_capabilities,
    normalize_capability,
    normalize_protocol,
)


@dataclass(frozen=True)
class SourceLocator:
    """Protocol-specific source address using Pythonic field names.

    Attributes:
        service_id: GeoServices service identifier (FeatureServer/MapServer/ImageServer).
        layer_id: Numeric layer index within a GeoServices service.
        collection_id: OGC API / STAC collection identifier.
        entity_set: OData entity-set name (e.g. ``"Features"``).
        type_name: WFS ``typeName`` value.
    """

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
    """Cross-SDK source description used by the source facade.

    ``protocol`` accepts any string (including alias forms) at construction
    time; ``__post_init__`` normalizes it through :func:`normalize_protocol`
    so the stored value is always a canonical :data:`Protocol` literal.

    Attributes:
        id: Stable source identifier used by the canonical facade.
        protocol: Canonical protocol literal after normalization.
        locator: Protocol-specific addressing fields.
        capabilities: Frozen set of canonical capability names advertised.
        raw: Free-form mapping preserving the source's underlying payload.
    """

    id: str
    protocol: Protocol | str
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

    def supports(self, capability: Capability | str) -> bool:
        """Return whether the source descriptor advertises a capability."""
        return normalize_capability(capability) in self.capabilities
