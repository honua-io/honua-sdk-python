"""Canonical Source/Query/Result facade shared across SDKs."""

from __future__ import annotations

import warnings
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import fields as dataclass_fields
from dataclasses import replace
from typing import TYPE_CHECKING, Any, runtime_checkable
from typing import Protocol as TypingProtocol

if TYPE_CHECKING:
    import httpx

from .errors import HonuaCapabilityNotSupportedError
from .models import (
    ApplyEditsResult,
    Capability,
    FeatureQuery,
    FeatureQueryResult,
    Protocol,
    Query,
    QueryFeature,
    Result,
    SourceDescriptor,
    normalize_capability,
    normalize_protocol,
)


@runtime_checkable
class SourceClientProtocol(TypingProtocol):
    """Structural type for the sync client surface used by :class:`Source`.

    Defines exactly the methods that :class:`Source` invokes on its bound
    client, so IDE completions and ``mypy`` retain signal on the canonical
    facade. :class:`~honua_sdk.HonuaClient` satisfies this Protocol
    structurally — no nominal inheritance or registration is required.

    The ``query`` / ``iter_query`` signatures intentionally accept
    ``FeatureQuery`` as the only positional argument — :class:`Source`
    pre-builds the :class:`FeatureQuery` and passes it through, so the
    Protocol does not need to enumerate filter/pagination keyword
    options. This keeps the structural type minimal and avoids drift
    against the wider client API surface.
    """

    def query(
        self,
        source: str | FeatureQuery,
        /,
        *,
        timeout: float | httpx.Timeout | None = ...,
        extra_headers: Mapping[str, str] | None = ...,
        idempotency_key: str | None = ...,
    ) -> FeatureQueryResult: ...
    def iter_query(
        self,
        source: str | FeatureQuery,
        /,
        *,
        timeout: float | httpx.Timeout | None = ...,
        extra_headers: Mapping[str, str] | None = ...,
        idempotency_key: str | None = ...,
    ) -> Iterator[QueryFeature]: ...
    def apply_edits_result(  # noqa: PLR0913 -- mirrors the public client signature
        self,
        service_id: str,
        layer_id: int,
        *,
        adds: Sequence[Mapping[str, Any]] | None = ...,
        updates: Sequence[Mapping[str, Any]] | None = ...,
        deletes: Sequence[int] | str | None = ...,
        rollback_on_failure: bool = ...,
        idempotency_key: str | None = ...,
        timeout: float | httpx.Timeout | None = ...,
        extra_headers: Mapping[str, str] | None = ...,
    ) -> ApplyEditsResult: ...
    def feature_server(self, service_id: str) -> Any: ...
    def map_server(self, service_id: str) -> Any: ...
    def image_server(self, service_id: str | None = ...) -> Any: ...
    def geometry_server(self) -> Any: ...
    def ogc_features(self) -> Any: ...
    def ogc_tiles(self) -> Any: ...
    def ogc_maps(self) -> Any: ...
    def stac(self) -> Any: ...
    def wfs(self) -> Any: ...
    def wms(self, service_id: str) -> Any: ...
    def wmts(self, service_id: str) -> Any: ...
    def odata(self) -> Any: ...


@runtime_checkable
class AsyncSourceClientProtocol(TypingProtocol):
    """Structural type for the async client surface used by :class:`AsyncSource`.

    Mirrors :class:`SourceClientProtocol` with awaitable query / iteration
    methods. :class:`~honua_sdk.AsyncHonuaClient` satisfies this Protocol
    structurally.
    """

    async def query(
        self,
        source: str | FeatureQuery,
        /,
        *,
        timeout: float | httpx.Timeout | None = ...,
        extra_headers: Mapping[str, str] | None = ...,
        idempotency_key: str | None = ...,
    ) -> FeatureQueryResult: ...
    def iter_query(
        self,
        source: str | FeatureQuery,
        /,
        *,
        timeout: float | httpx.Timeout | None = ...,
        extra_headers: Mapping[str, str] | None = ...,
        idempotency_key: str | None = ...,
    ) -> AsyncIterator[QueryFeature]: ...
    async def apply_edits_result(  # noqa: PLR0913 -- mirrors the public client signature
        self,
        service_id: str,
        layer_id: int,
        *,
        adds: Sequence[Mapping[str, Any]] | None = ...,
        updates: Sequence[Mapping[str, Any]] | None = ...,
        deletes: Sequence[int] | str | None = ...,
        rollback_on_failure: bool = ...,
        idempotency_key: str | None = ...,
        timeout: float | httpx.Timeout | None = ...,
        extra_headers: Mapping[str, str] | None = ...,
    ) -> ApplyEditsResult: ...
    def feature_server(self, service_id: str) -> Any: ...
    def map_server(self, service_id: str) -> Any: ...
    def image_server(self, service_id: str | None = ...) -> Any: ...
    def geometry_server(self) -> Any: ...
    def ogc_features(self) -> Any: ...
    def ogc_tiles(self) -> Any: ...
    def ogc_maps(self) -> Any: ...
    def stac(self) -> Any: ...
    def wfs(self) -> Any: ...
    def wms(self, service_id: str) -> Any: ...
    def wmts(self, service_id: str) -> Any: ...
    def odata(self) -> Any: ...


_NORMALIZED_QUERY_PROTOCOLS = frozenset(("geoservices-feature-service", "ogc-features", "stac", "odata"))
_FACADE_CAPABILITY_PROTOCOLS = {
    "query": _NORMALIZED_QUERY_PROTOCOLS,
    "stream": _NORMALIZED_QUERY_PROTOCOLS,
    "applyEdits": frozenset(("geoservices-feature-service",)),
}
_QUERY_FIELD_NAMES = frozenset(field.name for field in dataclass_fields(Query))

#: Names of the per-call ``Query`` override kwargs accepted by every
#: source-facade query method. Listed once here so each public method
#: signature stays explicit (for IDE/type signal) while bodies fan out
#: through a single helper instead of repeating the 13-kwarg call list.
_QUERY_OVERRIDE_KWARGS: tuple[str, ...] = (
    "where",
    "out_fields",
    "return_geometry",
    "bbox",
    "limit",
    "page_size",
    "max_pages",
    "cql_filter",
    "where_as_cql",
    "extra_params",
    "fields",
    "filter",
)


def _pick_query_overrides(local_vars: Mapping[str, Any]) -> dict[str, Any]:
    """Pull the per-call ``Query`` override kwargs out of a method's ``locals()``.

    Each :class:`Source` / :class:`AsyncSource` query method binds the
    overrides as explicit keyword parameters (for IDE/type signal) and
    forwards them through this helper. Centralizing the kwarg list keeps
    the 13-name signature in one place and lets bodies stay short.
    """
    return {name: local_vars[name] for name in _QUERY_OVERRIDE_KWARGS}


class Source:
    """Source-bound facade over the shared query API and protocol escape hatches.

    Binds a :class:`SourceDescriptor` to a :class:`HonuaClient` so callers
    can issue protocol-neutral :class:`Query` requests (``query``,
    ``stream``) without rebuilding the source identifier on each call.
    Routes requests through the canonical query dispatcher and exposes
    capability introspection via :meth:`supports`; falls back to the
    underlying protocol clients (``feature_server``, ``ogc_features``,
    ``stac``, ``odata``) when callers need protocol-specific escape
    hatches. Construct via :meth:`HonuaClient.source` rather than
    directly.

    Attributes:
        descriptor: The normalized :class:`SourceDescriptor` describing
            this source's protocol, addressing fields, and advertised
            capabilities.
    """

    def __init__(
        self,
        client: SourceClientProtocol,
        descriptor: SourceDescriptor | Mapping[str, Any],
    ) -> None:
        self._client = client
        self.descriptor = _coerce_descriptor(descriptor)

    @property
    def id(self) -> str:
        return self.descriptor.id

    @property
    def protocol_id(self) -> str:
        return self.descriptor.protocol

    def supports(self, capability: Capability | str) -> bool:
        return _source_facade_supports(self.descriptor, capability)

    def query(  # noqa: PLR0913 -- explicit kwargs mirror Query fields for IDE/type signal
        self,
        query: Query | Mapping[str, Any] | None = None,
        *,
        where: str | None = None,
        out_fields: str | Sequence[str] | None = None,
        return_geometry: bool | None = None,
        bbox: str | Sequence[int | float] | None = None,
        limit: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        cql_filter: str | None = None,
        where_as_cql: bool | None = None,
        extra_params: Mapping[str, Any] | None = None,
        fields: str | Sequence[str] | None = None,
        filter: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Result[QueryFeature]:
        """Run a canonical source query and collect normalized features.

        Accepts either a :class:`Query` (or mapping) plus explicit keyword
        overrides matching :class:`Query` fields. Two legacy keyword aliases
        remain accepted for source compatibility but emit
        :class:`DeprecationWarning`; migrate to the canonical
        :class:`Query` field names:

        * ``fields=`` is deprecated — use ``out_fields=``.
        * ``filter=`` is deprecated — use ``where=`` (see :class:`Query`
          for filter-routing semantics across SQL- and CQL-style protocols).

        Pass ``cql_filter=`` explicitly when targeting OGC Features / STAC
        with a CQL2-text expression — that bypasses the ``where`` field
        and routes the expression directly to the protocol's ``filter``
        field. Passing only ``where=`` against an OGC/STAC source raises
        :class:`ValueError`; opt into the old silent forwarding behavior
        with ``where_as_cql=True`` if you have verified the string is
        already valid CQL2-text.

        Per-call ``timeout`` / ``extra_headers`` / ``idempotency_key`` are
        forwarded to the bound client's ``query`` method (and from there
        to FeatureServer, OGC Features, and STAC pagination wrappers).
        """
        query_model = _coerce_query(query, **_pick_query_overrides(locals()))
        self._require("query")
        feature_query = _feature_query_for_source(self.descriptor, query_model)
        legacy_result = self._client.query(
            feature_query,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return _result_from_legacy(legacy_result, self.descriptor, query_model)

    def query_all(  # noqa: PLR0913 -- explicit kwargs mirror Query fields for IDE/type signal
        self,
        query: Query | Mapping[str, Any] | None = None,
        *,
        where: str | None = None,
        out_fields: str | Sequence[str] | None = None,
        return_geometry: bool | None = None,
        bbox: str | Sequence[int | float] | None = None,
        limit: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        cql_filter: str | None = None,
        where_as_cql: bool | None = None,
        extra_params: Mapping[str, Any] | None = None,
        fields: str | Sequence[str] | None = None,
        filter: str | None = None,
    ) -> tuple[QueryFeature, ...]:
        """Return all normalized features for a canonical source query."""
        return self.query(query, **_pick_query_overrides(locals())).features

    def stream(  # noqa: PLR0913 -- explicit kwargs mirror Query fields for IDE/type signal
        self,
        query: Query | Mapping[str, Any] | None = None,
        *,
        where: str | None = None,
        out_fields: str | Sequence[str] | None = None,
        return_geometry: bool | None = None,
        bbox: str | Sequence[int | float] | None = None,
        limit: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        cql_filter: str | None = None,
        where_as_cql: bool | None = None,
        extra_params: Mapping[str, Any] | None = None,
        fields: str | Sequence[str] | None = None,
        filter: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Iterator[QueryFeature]:
        """Stream normalized features for a canonical source query.

        Per-call ``timeout`` / ``extra_headers`` / ``idempotency_key`` are
        forwarded to the bound client's ``iter_query`` method.
        """
        query_model = _coerce_query(query, **_pick_query_overrides(locals()))
        self._require("stream")
        feature_query = _feature_query_for_source(self.descriptor, query_model)
        for feature in self._client.iter_query(
            feature_query,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        ):
            yield replace(feature, protocol=self.descriptor.protocol, source=self.descriptor.id)

    def iter_features(  # noqa: PLR0913 -- explicit kwargs mirror Query fields for IDE/type signal
        self,
        query: Query | Mapping[str, Any] | None = None,
        *,
        where: str | None = None,
        out_fields: str | Sequence[str] | None = None,
        return_geometry: bool | None = None,
        bbox: str | Sequence[int | float] | None = None,
        limit: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        cql_filter: str | None = None,
        where_as_cql: bool | None = None,
        extra_params: Mapping[str, Any] | None = None,
        fields: str | Sequence[str] | None = None,
        filter: str | None = None,
    ) -> Iterator[QueryFeature]:
        """Alias for ``stream()`` using a Python iterator name."""
        yield from self.stream(query, **_pick_query_overrides(locals()))

    def apply_edits(  # noqa: PLR0913 -- mirrors the public client signature
        self,
        *,
        adds: Sequence[Mapping[str, Any]] | None = None,
        updates: Sequence[Mapping[str, Any]] | None = None,
        deletes: Sequence[int] | str | None = None,
        rollback_on_failure: bool = True,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> ApplyEditsResult:
        """Apply edits for source protocols that expose a normalized edit helper.

        Args:
            adds: Sequence of feature mappings to insert.
            updates: Sequence of feature mappings to update by ``OBJECTID``.
            deletes: Either a sequence of object ids or a comma-string of
                ids to delete.
            rollback_on_failure: Whether the server should roll the entire
                batch back if any individual edit fails.
            idempotency_key: Stripe-style ``Idempotency-Key`` header value.
            timeout: Per-request timeout forwarded to the transport layer.
            extra_headers: Additional HTTP headers merged onto the request.
        """
        self._require("applyEdits")
        return self._client.apply_edits_result(
            _service_id(self.descriptor),
            _layer_id(self.descriptor),
            adds=adds,
            updates=updates,
            deletes=deletes,
            rollback_on_failure=rollback_on_failure,
            idempotency_key=idempotency_key,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def protocol(self, kind: Protocol | str | None = None) -> Any:
        """Return the native protocol client for source-specific operations."""
        return _protocol_client(self._client, self.descriptor, kind)

    def _require(self, capability: Capability | str) -> None:
        normalized = normalize_capability(capability)
        if not self.supports(normalized):
            raise HonuaCapabilityNotSupportedError(
                normalized,
                self.descriptor.protocol,
                source_id=self.descriptor.id,
                reason=_unsupported_facade_reason(self.descriptor, normalized),
            )


class AsyncSource:
    """Async source-bound facade over the shared query API and protocol escape hatches.

    Asynchronous counterpart to :class:`Source`. Binds a
    :class:`SourceDescriptor` to an :class:`AsyncHonuaClient` so callers
    can ``await`` protocol-neutral :class:`Query` requests (``query``,
    ``stream``) without rebuilding the source identifier on each call.
    Capability introspection (:meth:`supports`) and protocol escape
    hatches mirror the sync facade. Construct via
    :meth:`AsyncHonuaClient.source` rather than directly.

    Attributes:
        descriptor: The normalized :class:`SourceDescriptor` describing
            this source's protocol, addressing fields, and advertised
            capabilities.
    """

    def __init__(
        self,
        client: AsyncSourceClientProtocol,
        descriptor: SourceDescriptor | Mapping[str, Any],
    ) -> None:
        self._client = client
        self.descriptor = _coerce_descriptor(descriptor)

    @property
    def id(self) -> str:
        return self.descriptor.id

    @property
    def protocol_id(self) -> str:
        return self.descriptor.protocol

    def supports(self, capability: Capability | str) -> bool:
        return _source_facade_supports(self.descriptor, capability)

    async def query(  # noqa: PLR0913 -- explicit kwargs mirror Query fields for IDE/type signal
        self,
        query: Query | Mapping[str, Any] | None = None,
        *,
        where: str | None = None,
        out_fields: str | Sequence[str] | None = None,
        return_geometry: bool | None = None,
        bbox: str | Sequence[int | float] | None = None,
        limit: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        cql_filter: str | None = None,
        where_as_cql: bool | None = None,
        extra_params: Mapping[str, Any] | None = None,
        fields: str | Sequence[str] | None = None,
        filter: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Result[QueryFeature]:
        """Run a canonical source query and collect normalized features.

        Accepts either a :class:`Query` (or mapping) plus explicit keyword
        overrides matching :class:`Query` fields. Two legacy keyword aliases
        remain accepted for source compatibility but emit
        :class:`DeprecationWarning`; migrate to the canonical
        :class:`Query` field names:

        * ``fields=`` is deprecated — use ``out_fields=``.
        * ``filter=`` is deprecated — use ``where=`` (see :class:`Query`
          for filter-routing semantics across SQL- and CQL-style protocols).

        Pass ``cql_filter=`` explicitly when targeting OGC Features / STAC
        with a CQL2-text expression — that bypasses the ``where`` field
        and routes the expression directly to the protocol's ``filter``
        field. Passing only ``where=`` against an OGC/STAC source raises
        :class:`ValueError`; opt into the old silent forwarding behavior
        with ``where_as_cql=True`` if you have verified the string is
        already valid CQL2-text.

        Per-call ``timeout`` / ``extra_headers`` / ``idempotency_key`` are
        forwarded to the bound client's ``query`` method.
        """
        query_model = _coerce_query(query, **_pick_query_overrides(locals()))
        self._require("query")
        feature_query = _feature_query_for_source(self.descriptor, query_model)
        legacy_result = await self._client.query(
            feature_query,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return _result_from_legacy(legacy_result, self.descriptor, query_model)

    async def query_all(  # noqa: PLR0913 -- explicit kwargs mirror Query fields for IDE/type signal
        self,
        query: Query | Mapping[str, Any] | None = None,
        *,
        where: str | None = None,
        out_fields: str | Sequence[str] | None = None,
        return_geometry: bool | None = None,
        bbox: str | Sequence[int | float] | None = None,
        limit: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        cql_filter: str | None = None,
        where_as_cql: bool | None = None,
        extra_params: Mapping[str, Any] | None = None,
        fields: str | Sequence[str] | None = None,
        filter: str | None = None,
    ) -> tuple[QueryFeature, ...]:
        """Return all normalized features for a canonical source query."""
        result = await self.query(query, **_pick_query_overrides(locals()))
        return result.features

    async def stream(  # noqa: PLR0913 -- explicit kwargs mirror Query fields for IDE/type signal
        self,
        query: Query | Mapping[str, Any] | None = None,
        *,
        where: str | None = None,
        out_fields: str | Sequence[str] | None = None,
        return_geometry: bool | None = None,
        bbox: str | Sequence[int | float] | None = None,
        limit: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        cql_filter: str | None = None,
        where_as_cql: bool | None = None,
        extra_params: Mapping[str, Any] | None = None,
        fields: str | Sequence[str] | None = None,
        filter: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> AsyncIterator[QueryFeature]:
        """Stream normalized features for a canonical source query.

        Per-call ``timeout`` / ``extra_headers`` / ``idempotency_key`` are
        forwarded to the bound client's ``iter_query`` method.
        """
        query_model = _coerce_query(query, **_pick_query_overrides(locals()))
        self._require("stream")
        feature_query = _feature_query_for_source(self.descriptor, query_model)
        async for feature in self._client.iter_query(
            feature_query,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        ):
            yield replace(feature, protocol=self.descriptor.protocol, source=self.descriptor.id)

    async def iter_features(  # noqa: PLR0913 -- explicit kwargs mirror Query fields for IDE/type signal
        self,
        query: Query | Mapping[str, Any] | None = None,
        *,
        where: str | None = None,
        out_fields: str | Sequence[str] | None = None,
        return_geometry: bool | None = None,
        bbox: str | Sequence[int | float] | None = None,
        limit: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        cql_filter: str | None = None,
        where_as_cql: bool | None = None,
        extra_params: Mapping[str, Any] | None = None,
        fields: str | Sequence[str] | None = None,
        filter: str | None = None,
    ) -> AsyncIterator[QueryFeature]:
        """Alias for ``stream()`` using a Python iterator name."""
        async for feature in self.stream(query, **_pick_query_overrides(locals())):
            yield feature

    async def apply_edits(  # noqa: PLR0913 -- mirrors the public client signature
        self,
        *,
        adds: Sequence[Mapping[str, Any]] | None = None,
        updates: Sequence[Mapping[str, Any]] | None = None,
        deletes: Sequence[int] | str | None = None,
        rollback_on_failure: bool = True,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> ApplyEditsResult:
        """Apply edits for source protocols that expose a normalized edit helper.

        Args:
            adds: Sequence of feature mappings to insert.
            updates: Sequence of feature mappings to update by ``OBJECTID``.
            deletes: Either a sequence of object ids or a comma-string of
                ids to delete.
            rollback_on_failure: Whether the server should roll the entire
                batch back if any individual edit fails.
            idempotency_key: Stripe-style ``Idempotency-Key`` header value.
            timeout: Per-request timeout forwarded to the transport layer.
            extra_headers: Additional HTTP headers merged onto the request.
        """
        self._require("applyEdits")
        return await self._client.apply_edits_result(
            _service_id(self.descriptor),
            _layer_id(self.descriptor),
            adds=adds,
            updates=updates,
            deletes=deletes,
            rollback_on_failure=rollback_on_failure,
            idempotency_key=idempotency_key,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def protocol(self, kind: Protocol | str | None = None) -> Any:
        """Return the native protocol client for source-specific operations."""
        return _protocol_client(self._client, self.descriptor, kind)

    def _require(self, capability: Capability | str) -> None:
        normalized = normalize_capability(capability)
        if not self.supports(normalized):
            raise HonuaCapabilityNotSupportedError(
                normalized,
                self.descriptor.protocol,
                source_id=self.descriptor.id,
                reason=_unsupported_facade_reason(self.descriptor, normalized),
            )


def _source_facade_supports(descriptor: SourceDescriptor, capability: Capability | str) -> bool:
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


def _coerce_query(  # noqa: PLR0913 -- explicit kwargs mirror Query fields for IDE/type signal
    value: Query | Mapping[str, Any] | None,
    *,
    where: str | None = None,
    out_fields: str | Sequence[str] | None = None,
    return_geometry: bool | None = None,
    bbox: str | Sequence[int | float] | None = None,
    limit: int | None = None,
    page_size: int | None = None,
    max_pages: int | None = None,
    cql_filter: str | None = None,
    where_as_cql: bool | None = None,
    extra_params: Mapping[str, Any] | None = None,
    fields: str | Sequence[str] | None = None,
    filter: str | None = None,
) -> Query:
    if value is None:
        query = Query()
    elif isinstance(value, Query):
        query = value
    elif isinstance(value, Mapping):
        query = Query.from_dict(value)
    else:
        raise TypeError("query must be a Query, mapping, or None.")

    # Legacy aliases — emit a DeprecationWarning and route to the canonical
    # field name. ``out_fields=``/``where=`` win when both forms are passed.
    if fields is not None and out_fields is None:
        warnings.warn(
            "Source.query(fields=...) is deprecated; use out_fields=... instead.",
            DeprecationWarning,
            stacklevel=3,
        )
        out_fields = fields
    if filter is not None and where is None:
        warnings.warn(
            "Source.query(filter=...) is deprecated; use where=... instead "
            "(or cql_filter=... for CQL-based protocols).",
            DeprecationWarning,
            stacklevel=3,
        )
        where = filter

    updates: dict[str, Any] = {}
    # ``None`` sentinel means "not provided" — anything else overrides the
    # corresponding field on the inbound Query.
    for key, kw_value in (
        ("where", where),
        ("out_fields", out_fields),
        ("return_geometry", return_geometry),
        ("bbox", bbox),
        ("limit", limit),
        ("page_size", page_size),
        ("max_pages", max_pages),
        ("cql_filter", cql_filter),
        ("where_as_cql", where_as_cql),
        ("extra_params", extra_params),
    ):
        if kw_value is not None:
            updates[key] = kw_value

    if not updates:
        return query

    data = {field_name: getattr(query, field_name) for field_name in _QUERY_FIELD_NAMES}

    pagination_updates = {}
    for key in ("limit", "page_size", "max_pages"):
        if key in updates:
            pagination_updates[key] = updates.pop(key)

    pagination = query.pagination
    if pagination_updates:
        pagination = replace(pagination, **pagination_updates)
    data["pagination"] = pagination

    data.update(updates)
    return Query(**data)


#: Protocols whose native filter syntax is SQL-style and consumed via the
#: ``where`` field of :class:`~honua_sdk.models.FeatureQuery`.
_SQL_WHERE_PROTOCOLS = frozenset(("geoservices-feature-service", "odata"))
#: Protocols whose native filter syntax is OGC CQL-style and consumed via the
#: ``filter`` field of :class:`~honua_sdk.models.FeatureQuery`.
_CQL_FILTER_PROTOCOLS = frozenset(("ogc-features", "stac"))


def _feature_query_for_source(descriptor: SourceDescriptor, query: Query) -> FeatureQuery:
    """Build the legacy :class:`FeatureQuery` for a canonical ``Source.query``.

    Filter routing precedence:

    * On CQL-based protocols (OGC Features, STAC):

      - ``query.cql_filter`` (if set) is routed to ``FeatureQuery.filter``
        unconditionally.
      - Otherwise, ``query.where`` is rejected with :class:`ValueError`
        unless the caller has opted in with ``where_as_cql=True``. The
        opt-in forwards ``where`` to ``filter`` unmodified.

    * On SQL-style protocols (GeoServices FeatureServer, OData):

      - ``query.where`` routes to ``FeatureQuery.where`` (SQL).
      - ``query.cql_filter`` raises :class:`ValueError` — CQL2-text is not
        valid for FeatureServer / OData and silently dropping it would
        mask the bug.
      - ``where_as_cql`` is a no-op (still routes ``where`` to SQL
        ``where``).

    Sending the same expression on both ``where`` and ``filter`` would
    silently double-apply the predicate on protocols whose adapters honor
    both, so we route to one and leave the other ``None``.
    """
    protocol = descriptor.protocol
    if protocol not in _NORMALIZED_QUERY_PROTOCOLS:
        raise HonuaCapabilityNotSupportedError(
            "query",
            protocol,
            source_id=descriptor.id,
            reason="Normalized Source.query is currently implemented for FeatureServer, OGC Features, STAC, and OData.",
        )

    if query.cql_filter is not None and protocol not in _CQL_FILTER_PROTOCOLS:
        raise ValueError("cql_filter is only valid for CQL-based protocols")

    if protocol in _CQL_FILTER_PROTOCOLS:
        where_value = None
        if query.cql_filter is not None:
            filter_value = query.cql_filter
        elif query.where is not None:
            if not query.where_as_cql:
                raise ValueError(
                    "Query.where is a SQL-style filter; pass `cql_filter=...` "
                    "(CQL2-text) when targeting OGC Features or STAC. To accept "
                    "silent forwarding, pass where_as_cql=True explicitly."
                )
            filter_value = query.where
        else:
            filter_value = None
    else:
        where_value = query.where if protocol in _SQL_WHERE_PROTOCOLS else None
        filter_value = None

    return FeatureQuery(
        source=_query_source(descriptor),
        protocol=protocol,
        layer_id=_query_layer_id(descriptor),
        where=where_value,
        filter=filter_value,
        bbox=query.bbox,
        fields=query.out_fields,
        return_geometry=query.return_geometry,
        page_size=query.page_size,
        limit=query.limit,
        max_pages=query.max_pages,
        extra_params=_extra_params_for_query(protocol, query),
    )


def _result_from_legacy(
    legacy_result: FeatureQueryResult,
    descriptor: SourceDescriptor,
    query: Query,
) -> Result[QueryFeature]:
    """Translate a :class:`FeatureQueryResult` into the canonical :class:`Result`.

    Pagination fidelity: ``exceeded_transfer_limit`` and ``total_count`` are
    sourced from the underlying ``FeatureQueryResult`` (which captures
    protocol-specific signals such as FeatureServer's
    ``exceededTransferLimit``, OGC/STAC's ``numberMatched`` and next-link,
    and OData's ``@odata.count`` / ``@odata.nextLink``) rather than being
    silently fabricated from ``len(features)``.
    """
    normalized_features = tuple(
        replace(feature, protocol=descriptor.protocol, source=descriptor.id)
        for feature in legacy_result.features
    )
    total_count = (
        legacy_result.total_count
        if legacy_result.total_count is not None
        else len(normalized_features)
    )
    return Result(
        features=normalized_features,
        exceeded_transfer_limit=bool(legacy_result.exceeded_transfer_limit),
        total_count=total_count,
        protocol=descriptor.protocol,
        source_id=descriptor.id,
        query=query,
        raw_legacy=legacy_result,
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


def _protocol_client(  # noqa: PLR0911 -- protocol dispatch
    client: SourceClientProtocol | AsyncSourceClientProtocol,
    descriptor: SourceDescriptor,
    kind: Protocol | str | None,
) -> Any:
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
