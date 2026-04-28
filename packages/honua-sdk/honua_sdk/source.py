"""Canonical Source/Query/Result facade shared across SDKs."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import fields as dataclass_fields
from dataclasses import replace
from typing import Any

from .errors import HonuaCapabilityNotSupportedError
from .models import (
    ApplyEditsResult,
    Capability,
    FeatureQuery,
    Pagination,
    Protocol,
    Query,
    QueryFeature,
    Result,
    SourceDescriptor,
    SourceLocator,
    normalize_capability,
    normalize_protocol,
)

_NORMALIZED_QUERY_PROTOCOLS = frozenset(("geoservices-feature-service", "ogc-features", "stac", "odata"))
_FACADE_CAPABILITY_PROTOCOLS = {
    "query": _NORMALIZED_QUERY_PROTOCOLS,
    "stream": _NORMALIZED_QUERY_PROTOCOLS,
    "applyEdits": frozenset(("geoservices-feature-service",)),
}
_QUERY_FIELD_NAMES = frozenset(field.name for field in dataclass_fields(Query))


class Source:
    """Source-bound facade over the shared query API and protocol escape hatches."""

    def __init__(self, client: Any, descriptor: SourceDescriptor | Mapping[str, Any]) -> None:
        self._client = client
        self.descriptor = _coerce_descriptor(descriptor)

    @property
    def id(self) -> str:
        return self.descriptor.id

    @property
    def protocol_id(self) -> str:
        return self.descriptor.protocol

    def supports(self, capability: Capability) -> bool:
        return _source_facade_supports(self.descriptor, capability)

    def query(self, query: Query | Mapping[str, Any] | None = None, **kwargs: Any) -> Result:
        """Run a canonical source query and collect normalized features."""
        query_model = _coerce_query(query, kwargs)
        self._require("query")
        feature_query = _feature_query_for_source(self.descriptor, query_model)
        legacy_result = self._client.query(feature_query)
        return _result_from_legacy(legacy_result.features, self.descriptor, query_model, raw={"legacy": legacy_result})

    def query_all(self, query: Query | Mapping[str, Any] | None = None, **kwargs: Any) -> tuple[QueryFeature, ...]:
        """Return all normalized features for a canonical source query."""
        return self.query(query, **kwargs).features

    def stream(self, query: Query | Mapping[str, Any] | None = None, **kwargs: Any) -> Iterator[QueryFeature]:
        """Stream normalized features for a canonical source query."""
        query_model = _coerce_query(query, kwargs)
        self._require("stream")
        feature_query = _feature_query_for_source(self.descriptor, query_model)
        for feature in self._client.iter_query(feature_query):
            yield replace(feature, protocol=self.descriptor.protocol, source=self.descriptor.id)

    def iter_features(self, query: Query | Mapping[str, Any] | None = None, **kwargs: Any) -> Iterator[QueryFeature]:
        """Alias for ``stream()`` using a Python iterator name."""
        yield from self.stream(query, **kwargs)

    def apply_edits(self, **kwargs: Any) -> ApplyEditsResult:
        """Apply edits for source protocols that expose a normalized edit helper."""
        self._require("applyEdits")
        return self._client.apply_edits_result(_service_id(self.descriptor), _layer_id(self.descriptor), **kwargs)

    def protocol(self, kind: Protocol | None = None) -> Any:
        """Return the native protocol client for source-specific operations."""
        return _protocol_client(self._client, self.descriptor, kind)

    def _require(self, capability: Capability) -> None:
        normalized = normalize_capability(capability)
        if not self.supports(normalized):
            raise HonuaCapabilityNotSupportedError(
                normalized,
                self.descriptor.protocol,
                source_id=self.descriptor.id,
                reason=_unsupported_facade_reason(self.descriptor, normalized),
            )


class AsyncSource:
    """Async source-bound facade over the shared query API and protocol escape hatches."""

    def __init__(self, client: Any, descriptor: SourceDescriptor | Mapping[str, Any]) -> None:
        self._client = client
        self.descriptor = _coerce_descriptor(descriptor)

    @property
    def id(self) -> str:
        return self.descriptor.id

    @property
    def protocol_id(self) -> str:
        return self.descriptor.protocol

    def supports(self, capability: Capability) -> bool:
        return _source_facade_supports(self.descriptor, capability)

    async def query(self, query: Query | Mapping[str, Any] | None = None, **kwargs: Any) -> Result:
        """Run a canonical source query and collect normalized features."""
        query_model = _coerce_query(query, kwargs)
        self._require("query")
        feature_query = _feature_query_for_source(self.descriptor, query_model)
        legacy_result = await self._client.query(feature_query)
        return _result_from_legacy(legacy_result.features, self.descriptor, query_model, raw={"legacy": legacy_result})

    async def query_all(self, query: Query | Mapping[str, Any] | None = None, **kwargs: Any) -> tuple[QueryFeature, ...]:
        """Return all normalized features for a canonical source query."""
        return (await self.query(query, **kwargs)).features

    async def stream(self, query: Query | Mapping[str, Any] | None = None, **kwargs: Any) -> AsyncIterator[QueryFeature]:
        """Stream normalized features for a canonical source query."""
        query_model = _coerce_query(query, kwargs)
        self._require("stream")
        feature_query = _feature_query_for_source(self.descriptor, query_model)
        async for feature in self._client.iter_query(feature_query):
            yield replace(feature, protocol=self.descriptor.protocol, source=self.descriptor.id)

    async def iter_features(
        self,
        query: Query | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[QueryFeature]:
        """Alias for ``stream()`` using a Python iterator name."""
        async for feature in self.stream(query, **kwargs):
            yield feature

    async def apply_edits(self, **kwargs: Any) -> ApplyEditsResult:
        """Apply edits for source protocols that expose a normalized edit helper."""
        self._require("applyEdits")
        return await self._client.apply_edits_result(
            _service_id(self.descriptor),
            _layer_id(self.descriptor),
            **kwargs,
        )

    def protocol(self, kind: Protocol | None = None) -> Any:
        """Return the native protocol client for source-specific operations."""
        return _protocol_client(self._client, self.descriptor, kind)

    def _require(self, capability: Capability) -> None:
        normalized = normalize_capability(capability)
        if not self.supports(normalized):
            raise HonuaCapabilityNotSupportedError(
                normalized,
                self.descriptor.protocol,
                source_id=self.descriptor.id,
                reason=_unsupported_facade_reason(self.descriptor, normalized),
            )


def _source_facade_supports(descriptor: SourceDescriptor, capability: Capability) -> bool:
    normalized = normalize_capability(capability)
    if not descriptor.supports(normalized):
        return False
    protocols = _FACADE_CAPABILITY_PROTOCOLS.get(normalized)
    if protocols is None:
        return True
    return descriptor.protocol in protocols


def _unsupported_facade_reason(descriptor: SourceDescriptor, capability: str) -> str | None:
    if not descriptor.supports(capability):
        return None
    return (
        f"The Python source facade does not expose normalized {capability} "
        f"for protocol {descriptor.protocol!r}; use source.protocol(...) for native operations."
    )


def _coerce_descriptor(value: SourceDescriptor | Mapping[str, Any]) -> SourceDescriptor:
    if isinstance(value, SourceDescriptor):
        return value
    if isinstance(value, Mapping):
        return SourceDescriptor.from_dict(value)
    raise TypeError("descriptor must be a SourceDescriptor or mapping.")


def _coerce_query(value: Query | Mapping[str, Any] | None, overrides: Mapping[str, Any]) -> Query:
    if value is None:
        query = Query()
    elif isinstance(value, Query):
        query = value
    elif isinstance(value, Mapping):
        query = Query.from_dict(value)
    else:
        raise TypeError("query must be a Query, mapping, or None.")

    if not overrides:
        return query

    data = {field_name: getattr(query, field_name) for field_name in _QUERY_FIELD_NAMES}
    updates = dict(overrides)
    if "fields" in updates and "out_fields" not in updates:
        updates["out_fields"] = updates.pop("fields")
    if "filter" in updates and "where" not in updates:
        updates["where"] = updates.pop("filter")

    pagination_updates = {}
    for key in ("limit", "page_size", "max_pages", "offset"):
        if key in updates:
            pagination_updates[key] = updates.pop(key)

    pagination = updates.pop("pagination", query.pagination)
    if isinstance(pagination, Mapping):
        pagination = Pagination.from_dict(pagination)
    if pagination_updates:
        pagination = replace(pagination, **pagination_updates)
    data["pagination"] = pagination

    unknown = sorted(set(updates) - _QUERY_FIELD_NAMES)
    if unknown:
        raise TypeError(f"Unexpected query option(s): {', '.join(unknown)}.")
    data.update(updates)
    return Query(**data)


def _feature_query_for_source(descriptor: SourceDescriptor, query: Query) -> FeatureQuery:
    protocol = descriptor.protocol
    if protocol not in _NORMALIZED_QUERY_PROTOCOLS:
        raise HonuaCapabilityNotSupportedError(
            "query",
            protocol,
            source_id=descriptor.id,
            reason="Normalized Source.query is currently implemented for FeatureServer, OGC Features, STAC, and OData.",
        )

    return FeatureQuery(
        source=_query_source(descriptor),
        protocol=protocol,
        layer_id=_query_layer_id(descriptor),
        where=query.where,
        filter=query.where,
        bbox=query.bbox,
        fields=query.out_fields,
        return_geometry=query.return_geometry,
        page_size=query.page_size,
        limit=query.limit,
        max_pages=query.max_pages,
        extra_params=_extra_params_for_query(protocol, query),
    )


def _result_from_legacy(
    features: Sequence[QueryFeature],
    descriptor: SourceDescriptor,
    query: Query,
    *,
    raw: Mapping[str, Any],
) -> Result:
    normalized_features = tuple(
        replace(feature, protocol=descriptor.protocol, source=descriptor.id)
        for feature in features
    )
    return Result(
        features=normalized_features,
        exceeded_transfer_limit=False,
        total_count=len(normalized_features),
        protocol=descriptor.protocol,
        source_id=descriptor.id,
        query=query,
        raw=raw,
    )


def _query_source(descriptor: SourceDescriptor) -> str:
    locator = descriptor.locator
    if descriptor.protocol == "geoservices-feature-service":
        return locator.service_id or descriptor.id
    if descriptor.protocol in {"ogc-features", "stac"}:
        return locator.collection_id or descriptor.id
    if descriptor.protocol == "odata":
        if locator.layer_id is not None:
            return str(locator.layer_id)
        return locator.entity_set or descriptor.id
    return descriptor.id


def _query_layer_id(descriptor: SourceDescriptor) -> int | None:
    if descriptor.protocol in {"geoservices-feature-service", "odata"}:
        return descriptor.locator.layer_id
    return None


def _extra_params_for_query(protocol: str, query: Query) -> dict[str, Any]:
    params = dict(query.extra_params)
    if query.offset is not None:
        if protocol == "geoservices-feature-service":
            params.setdefault("resultOffset", query.offset)
        elif protocol == "odata":
            params.setdefault("$skip", query.offset)
        else:
            params.setdefault("offset", query.offset)
    if query.out_sr is not None and protocol == "geoservices-feature-service":
        params.setdefault("outSR", query.out_sr)
    if query.order_by is not None:
        value = _csv(query.order_by)
        if protocol == "geoservices-feature-service":
            params.setdefault("orderByFields", value)
        elif protocol == "odata":
            params.setdefault("$orderby", value)
        else:
            params.setdefault("sortby", value)
    return params


def _protocol_client(client: Any, descriptor: SourceDescriptor, kind: Protocol | None) -> Any:
    protocol = normalize_protocol(kind or descriptor.protocol)
    locator = descriptor.locator
    if protocol == "geoservices-feature-service":
        return client.feature_server(locator.service_id or descriptor.id)
    if protocol == "geoservices-map-service":
        return client.map_server(locator.service_id or descriptor.id)
    if protocol == "geoservices-image-service":
        return client.image_server(locator.service_id or descriptor.id)
    if protocol == "geoservices-geometry-service":
        return client.geometry_server()
    if protocol == "ogc-features":
        ogc = client.ogc_features()
        return ogc.collection(locator.collection_id) if locator.collection_id is not None else ogc
    if protocol == "ogc-tiles":
        return client.ogc_tiles()
    if protocol == "ogc-maps":
        return client.ogc_maps()
    if protocol == "stac":
        return client.stac()
    if protocol == "wfs":
        return client.wfs()
    if protocol == "wms":
        return client.wms(locator.service_id or descriptor.id)
    if protocol == "wmts":
        return client.wmts(locator.service_id or descriptor.id)
    if protocol == "odata":
        return client.odata()
    raise HonuaCapabilityNotSupportedError(
        "connect",
        protocol,
        source_id=descriptor.id,
        reason="No native protocol client is available for this source protocol.",
    )


def _service_id(descriptor: SourceDescriptor) -> str:
    return descriptor.locator.service_id or descriptor.id


def _layer_id(descriptor: SourceDescriptor) -> int:
    return 0 if descriptor.locator.layer_id is None else descriptor.locator.layer_id


def _csv(value: str | Sequence[str]) -> str:
    if isinstance(value, str):
        return value
    return ",".join(str(item) for item in value)
