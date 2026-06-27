"""Feature-shaped model dataclasses (GeoServices and protocol-neutral)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ._geometry import geometry_to_geo_interface, geometry_to_shapely
from ._helpers import _optional_str
from ._protocols import QueryProtocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    from shapely.geometry.base import BaseGeometry

# Sentinel distinguishing "not yet computed" from a cached ``None`` geometry.
_UNSET: Any = object()


@dataclass(frozen=True)
class Feature:
    """FeatureServer feature with attributes and optional geometry.

    Returned by GeoServices FeatureServer endpoints (``FeatureServerClient``
    and its async sibling) via :meth:`FeatureSet.features`. Uses the
    GeoServices ``attributes``/``geometry`` shape verbatim. For the
    protocol-neutral feature shape used by :meth:`Source.query`, see
    :class:`QueryFeature` instead.
    """

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

    @property
    def __geo_interface__(self) -> dict[str, Any] | None:
        """GeoJSON-mapping view of this feature's geometry (``None`` if absent).

        Implements the de-facto ``__geo_interface__`` protocol so the feature
        plugs directly into Shapely (``shapely.geometry.shape(feature)``) and
        the wider Python geospatial ecosystem. Handles both the Esri-JSON
        (FeatureServer) and GeoJSON (OGC/STAC) geometry encodings.
        """
        return geometry_to_geo_interface(self.geometry)

    def to_shapely(self) -> "BaseGeometry | None":
        """Return this feature's geometry as a Shapely geometry.

        The typed analogue of ``arcpy`` ``feature.SHAPE`` / the ArcGIS-API
        geometry object: a GP tool gets Shapely geometry directly from the
        feature without dropping to ``result.raw``. Returns ``None`` when the
        feature has no geometry. Raises :class:`ImportError` with an install
        hint when the optional ``shapely`` dependency is absent.
        """
        return geometry_to_shapely(self.geometry)

    @property
    def geometry_shape(self) -> "BaseGeometry | None":
        """Cached Shapely geometry for this feature (see :meth:`to_shapely`)."""
        cached = self.__dict__.get("_geometry_shape", _UNSET)
        if cached is _UNSET:
            cached = self.to_shapely()
            object.__setattr__(self, "_geometry_shape", cached)
        return cached


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
    protocol: QueryProtocol | str = "feature-server"
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
    """Protocol-neutral feature returned by the shared query API.

    Returned by :meth:`Source.query`, :meth:`Source.stream`, and the
    underlying :meth:`HonuaClient.query` / :meth:`AsyncHonuaClient.query`
    facade across every protocol (FeatureServer, OGC Features, STAC,
    OData). Uses GeoJSON-shaped ``properties`` + ``geometry``. For the
    raw GeoServices ``attributes``/``geometry`` shape, see :class:`Feature`.

    Attributes:
        id: Stable feature identifier from the underlying protocol.
        properties: GeoJSON-shaped attribute mapping.
        geometry: Optional GeoJSON-shaped geometry mapping.
        protocol: Canonical protocol literal the feature was served from.
        source: Identifier of the source that produced the feature.
        raw: Free-form mapping preserving the underlying protocol payload.
    """

    id: str | int | None
    properties: Mapping[str, Any]
    geometry: Mapping[str, Any] | None = None
    protocol: str = ""
    source: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def __geo_interface__(self) -> dict[str, Any] | None:
        """GeoJSON-mapping view of this feature's geometry (``None`` if absent).

        Implements the de-facto ``__geo_interface__`` protocol so the feature
        plugs directly into Shapely and the wider Python geospatial ecosystem.
        Handles both Esri-JSON (FeatureServer) and GeoJSON (OGC/STAC) sources.
        """
        return geometry_to_geo_interface(self.geometry)

    def to_shapely(self) -> "BaseGeometry | None":
        """Return this feature's geometry as a Shapely geometry.

        The typed analogue of ``arcpy`` ``feature.SHAPE`` / the ArcGIS-API
        geometry object. Returns ``None`` when the feature carries no geometry.
        Raises :class:`ImportError` with an install hint when the optional
        ``shapely`` dependency is absent.
        """
        return geometry_to_shapely(self.geometry)

    @property
    def geometry_shape(self) -> "BaseGeometry | None":
        """Cached Shapely geometry for this feature (see :meth:`to_shapely`)."""
        cached = self.__dict__.get("_geometry_shape", _UNSET)
        if cached is _UNSET:
            cached = self.to_shapely()
            object.__setattr__(self, "_geometry_shape", cached)
        return cached


@dataclass(frozen=True)
class FeatureQueryResult:
    """Collected result returned by the shared query API.

    Pagination signals (``exceeded_transfer_limit``, ``total_count``,
    ``pages_seen``) are populated from the underlying protocol response
    when available:

    * GeoServices FeatureServer surfaces ``exceededTransferLimit`` on each
      page; ``total_count`` defaults to ``len(features)``.
    * OGC Features / STAC surface ``numberMatched`` (total) and
      ``numberReturned``; ``exceeded_transfer_limit`` is derived from a
      ``next`` link being present on the last page walked.
    * OData surfaces ``@odata.count`` (total) and ``@odata.nextLink``
      (drives ``exceeded_transfer_limit``).

    When the protocol does not expose a signal the field defaults to a
    safe value (``False`` / ``None``) — never silently fabricated.
    """

    features: tuple[QueryFeature, ...]
    protocol: str
    source: str
    query: FeatureQuery
    exceeded_transfer_limit: bool = False
    total_count: int | None = None
    pages_seen: int = 0
