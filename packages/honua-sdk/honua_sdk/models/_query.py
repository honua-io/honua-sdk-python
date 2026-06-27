"""Canonical query-input and query-result model dataclasses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from ._helpers import _first_present, _mapping_value, _optional_int, _optional_str
from ._protocols import (
    Capability,
    Protocol,
    normalize_capability,
    normalize_protocol,
)

if TYPE_CHECKING:
    from ._features import FeatureQueryResult

T = TypeVar("T")


@dataclass(frozen=True)
class Pagination:
    """Pagination options shared by queryable source protocols.

    Attributes:
        limit: Maximum features to return across all pages.
        page_size: Per-request page size for paginated protocols.
        max_pages: Cap on the number of pages walked.
        offset: Starting offset for the first page (when supported).
    """

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
    """Cross-SDK query model with Pythonic field names.

    Filter routing
    --------------

    Pick exactly one of three forms, matched to the target protocol:

    * ``where`` — SQL-style ``WHERE`` clause for SQL protocols
      (GeoServices FeatureServer, OData). On CQL-based protocols (OGC
      Features, STAC) this raises :class:`ValueError` at routing time,
      because silently forwarding SQL syntax to a CQL endpoint is a
      footgun that masks bugs.
    * ``cql_filter`` — CQL2-text filter for CQL protocols (OGC Features,
      STAC). On SQL-style protocols this raises :class:`ValueError` —
      CQL2-text is not valid for FeatureServer / OData.
    * ``where_as_cql=True`` — escape hatch for protocol-agnostic callers
      that have already verified the ``where`` string is valid CQL2-text.
      With the flag set, ``where`` is forwarded to the CQL ``filter``
      field on OGC/STAC without raising. The flag is a no-op on SQL-style
      protocols (``where`` still routes to SQL ``where``).

    When both ``where`` and ``cql_filter`` are set on a CQL-based
    protocol, ``cql_filter`` wins.

    Attributes:
        where: SQL-style filter for FeatureServer/OData endpoints.
        cql_filter: CQL2-text filter for OGC Features / STAC.
        where_as_cql: When True, forwards ``where`` to CQL endpoints without raising.
        spatial_filter: Free-form spatial-filter mapping (geometry, relation, SR).
        bbox: ``(minx, miny, maxx, maxy)`` spatial filter; comma-string also accepted.
        out_fields: Field selector; ``["*"]`` or ``"*"`` selects all.
        order_by: Sort specification forwarded to the protocol.
        pagination: :class:`Pagination` options (``limit``, ``page_size``, ...).
        aggregation: Protocol-neutral aggregation request mapping.
        return_geometry: Whether to include geometry in the response.
        out_sr: Output spatial reference (EPSG code or WKID).
        extra_params: Free-form per-protocol query parameter overrides.
    """

    where: str | None = None
    cql_filter: str | None = None
    where_as_cql: bool = False
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
            cql_filter=_optional_str(_first_present(payload, "cqlFilter", "cql_filter")),
            where_as_cql=bool(_first_present(payload, "whereAsCql", "where_as_cql") or False),
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
    """Reason a result used a lower-fidelity path for a requested capability.

    ``capability`` and ``protocol`` are normalized to their canonical
    Literal form in ``__post_init__`` via :func:`normalize_capability` /
    :func:`normalize_protocol`, so aliases passed at construction time are
    accepted but stored values always match the strict types.
    """

    capability: Capability | str
    protocol: Protocol | str
    source_id: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability", normalize_capability(self.capability))
        object.__setattr__(self, "protocol", normalize_protocol(self.protocol))


@dataclass(frozen=True)
class Result(Generic[T]):
    """Collected result returned by the canonical Source/Query API.

    Generic over the feature element type ``T`` (defaults to
    :class:`QueryFeature` at call sites). ``raw_legacy`` exposes the
    underlying :class:`FeatureQueryResult` (the protocol-neutral query
    result the canonical facade is built on) for callers that need the
    unprocessed protocol response — e.g. inspecting ``pages_seen`` or the
    original ``query`` envelope. ``raw`` remains a free-form mapping
    reserved for protocol-specific extension fields.

    Attributes:
        features: Tuple of result features (type parameter ``T``).
        exceeded_transfer_limit: True when the server signalled more pages remain.
        total_count: Server-reported total count when available.
        aggregate_rows: Aggregate result rows when an aggregation was requested.
        extent: Result extent mapping (``xmin``/``ymin``/``xmax``/``ymax``).
        fields: Field schema entries returned by the protocol.
        degraded: Reasons this result fell back to a lower-fidelity path.
        protocol: Canonical protocol literal the result was served from.
        source_id: Identifier of the source that produced the result.
        query: The :class:`Query` instance that produced this result.
        raw: Free-form mapping for protocol-specific extension fields.
        raw_legacy: Underlying :class:`FeatureQueryResult` envelope, when available.
    """

    features: tuple[T, ...] = ()
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
    raw_legacy: "FeatureQueryResult | None" = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", tuple(self.features))
        object.__setattr__(self, "aggregate_rows", tuple(dict(row) for row in self.aggregate_rows))
        object.__setattr__(self, "fields", tuple(dict(field) for field in self.fields))
        object.__setattr__(self, "extent", dict(self.extent) if self.extent is not None else None)
        object.__setattr__(self, "degraded", tuple(self.degraded))
        object.__setattr__(self, "raw", dict(self.raw))

    def to_geodataframe(self) -> Any:
        """Convert this result's features to a GeoPandas ``GeoDataFrame``.

        The first-class, one-call equivalent of the Esri Spatially-Enabled
        DataFrame: feature attributes become columns and each feature's geometry
        (via its ``__geo_interface__`` bridge) becomes the geometry column. The
        CRS is resolved from the result's ``query.out_sr`` / ``extent`` spatial
        reference, defaulting to ``EPSG:4326`` for GeoJSON sources.

        Requires the optional ``geopandas`` extra
        (``pip install honua-sdk[geopandas]``); raises :class:`ImportError` with
        an install hint when it is absent.
        """
        from honua_sdk.geopandas import result_to_geodataframe

        return result_to_geodataframe(self)
