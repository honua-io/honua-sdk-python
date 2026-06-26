"""Feature-shaped model dataclasses (GeoServices and protocol-neutral)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ._helpers import _optional_str
from ._protocols import QueryProtocol


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
    """Protocol-neutral feature query request.

    Attributes:
        source: Source identifier (service id / collection id / entity set).
        protocol: Canonical query protocol literal.
        layer_id: FeatureServer / OData layer index when required.
        where: SQL-style ``WHERE`` clause (FeatureServer / OData).
        filter: CQL2-text filter (OGC Features / STAC).
        bbox: ``(minx, miny, maxx, maxy)`` envelope spatial filter.
        spatial_filter: Free-form spatial-filter mapping (arbitrary geometry +
            relationship + SR + optional distance) translated to GeoServices
            ``geometry``/``geometryType``/``spatialRel``/``inSR`` params on the
            FeatureServer path. See :mod:`honua_sdk._geoservices_query`.
        fields: Attribute selection.
        return_geometry: Whether to include geometry in the response.
        out_statistics: Server-side statistic definitions (FeatureServer
            ``outStatistics``).
        group_by: Group-by fields for statistics (FeatureServer
            ``groupByFieldsForStatistics``).
        return_distinct_values: Request distinct rows (``returnDistinctValues``).
        return_count_only: Request only the matching count (``returnCountOnly``).
        page_size: Per-request page size for paginated protocols.
        limit: Maximum features collected across all pages.
        max_pages: Cap on the number of pages walked. ``None`` is unbounded.
        extra_params: Free-form per-protocol query parameter overrides.
    """

    source: str
    protocol: QueryProtocol | str = "feature-server"
    layer_id: int | None = None
    where: str | None = None
    filter: str | None = None
    bbox: str | Sequence[int | float] | None = None
    spatial_filter: Mapping[str, Any] | None = None
    fields: str | Sequence[str] | None = None
    return_geometry: bool = True
    out_statistics: Sequence[Mapping[str, Any]] | None = None
    group_by: str | Sequence[str] | None = None
    return_distinct_values: bool = False
    return_count_only: bool = False
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
