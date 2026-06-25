"""Server discovery / capability-advertisement model dataclasses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ._helpers import _first_present, _optional_str
from ._protocols import (
    _capability_flags,
    _capability_names,
    _normalize_advertised_name,
    _normalized_surface_keys,
)


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
