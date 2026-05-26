"""Asynchronous HTTP client for Honua Server APIs."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any

import httpx

from . import _endpoints
from ._async_retry import AsyncRetryTransport
from ._http import (
    _apply_sensitive_auth_headers,
    _build_sensitive_auth_headers,
    _extract_trusted_authority,
    _normalize_base_url,
    _to_http_error,
    _to_transport_error,
    _validate_auth_configuration,
    _validate_external_client_auth_configuration,
)
from ._query import (
    features_from_geojson_page,
    normalize_query_protocol,
    odata_features_from_page,
    odata_pagination_signals,
    ogc_pagination_signals,
    query_feature_from_feature_server,
    query_feature_from_geojson,
    query_feature_from_mapping,
    resolve_feature_query,
)
from ._query_dispatch import (
    feature_server_items_kwargs,
    feature_server_pages_kwargs,
    merge_idempotency_into_headers,
    merge_request_headers,
    odata_items_kwargs,
    odata_pages_kwargs,
    ogc_features_items_kwargs,
    ogc_features_pages_kwargs,
    reject_odata_bbox,
    stac_items_kwargs,
    stac_pages_kwargs,
    validate_filter_routing,
)
from .errors import HonuaHttpError
from .models import (
    ApplyEditsResult,
    DataPlaneCapabilities,
    Feature,
    FeatureQuery,
    FeatureQueryResult,
    FeatureSet,
    QueryFeature,
    QueryProtocol,
    ServiceSummary,
)

if TYPE_CHECKING:
    from .async_geocoding import AsyncHonuaGeocodingClient
    from .auth import AuthProvider
    from .geoprocessing import AsyncHonuaGeoprocessing
    from .models import SourceDescriptor
    from .ogc import AsyncHonuaOgcFeatures
    from .protocols import (
        AsyncGeoServicesFeatureServerClient,
        AsyncGeoServicesGeometryServerClient,
        AsyncGeoServicesImageServerClient,
        AsyncGeoServicesMapServerClient,
        AsyncODataClient,
        AsyncOgcCoveragesClient,
        AsyncOgcMapsClient,
        AsyncOgcProcessesClient,
        AsyncOgcRecordsClient,
        AsyncOgcTilesClient,
        AsyncSceneClient,
        AsyncStacClient,
        AsyncWfsClient,
        AsyncWmsClient,
        AsyncWmtsClient,
    )
    from .protocols.scenes import AsyncElevationClient
    from .source import AsyncSource
    from .workflow import AsyncHonuaWorkflow


class AsyncHonuaClient:
    """Task-oriented asynchronous client for common Honua data-plane workflows.

    Async counterpart to :class:`honua_sdk.HonuaClient`: wraps the Honua
    REST/HTTP surface (catalog, FeatureServer, OGC API Features, STAC,
    OData, WFS, WMS, WMTS, geocoding) and the canonical
    ``Source`` / ``Query`` / ``Result`` facade behind a single typed
    entrypoint.

    Authentication is configured at construction with at most one of
    ``api_key``, ``bearer_token``, or ``auth_provider`` (mutually
    exclusive). When ``client`` is supplied as a pre-built
    :class:`httpx.AsyncClient`, no auth kwargs may be passed — configure
    them on the client instead.

    Retries: only idempotent methods (GET/HEAD/PUT/DELETE/OPTIONS) on
    transient statuses (429/502/503/504) are retried by default. Opt
    POST in by configuring ``retry_methods`` on the underlying retry
    transport; mutating helpers such as :meth:`apply_edits` then
    auto-generate ``Idempotency-Key`` headers.

    Use as an async context manager so the underlying transport closes
    deterministically::

        async with AsyncHonuaClient("https://example.com", api_key="...") as client:
            result = await client.source(descriptor).query(Query(where="1=1"))

    Per-call overrides (``timeout``, ``extra_headers``,
    ``idempotency_key``) are exposed on every method; use
    :meth:`with_options` for sticky per-clone overrides (shared
    transport unless ``base_url`` is supplied).

    See also: :class:`honua_sdk.source.Source` and the Core Client guide
    at ``docs/core-client.md``.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        api_key: str | None = None,
        bearer_token: str | None = None,
        auth_provider: AuthProvider | None = None,
        follow_redirects: bool = False,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 3,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("Provide either `client` or `transport`, not both.")
        _validate_auth_configuration(bearer_token=bearer_token, auth_provider=auth_provider)
        _validate_external_client_auth_configuration(
            client=client,
            api_key=api_key,
            bearer_token=bearer_token,
            auth_provider=auth_provider,
        )

        # Stash constructor inputs so ``with_options`` can build an
        # independent clone without re-deriving these from ``self``.
        self._init_base_url = base_url
        self._init_timeout = timeout
        self._init_api_key = api_key
        self._init_bearer_token = bearer_token
        self._init_auth_provider = auth_provider
        self._init_follow_redirects = follow_redirects
        self._init_transport = transport
        self._init_max_retries = max_retries

        self._owns_client = client is None
        # Per-request overrides set by ``with_options``; ``None`` means the
        # underlying client's defaults apply. ``_options_max_retries`` is
        # forwarded to the retry transport via ``request.extensions``.
        self._options_timeout: float | None = None
        self._options_max_retries: int | None = None
        # Track whether the retry transport opted POST in so that mutating
        # helpers (apply_edits) can auto-generate idempotency keys.
        self._retry_methods: frozenset[str] = frozenset()
        if client is not None:
            self._client = client
            # Capture the public ``base_url`` from the supplied client so we
            # never reach into the private ``_base_url`` attribute of
            # :class:`httpx.AsyncClient` from request-time code paths.
            self._base_url: httpx.URL = httpx.URL(client.base_url)
            return

        normalized_base_url = _normalize_base_url(base_url)
        self._base_url = httpx.URL(normalized_base_url)
        trusted_authority = _extract_trusted_authority(self._base_url)
        auth_headers = _build_sensitive_auth_headers(api_key=api_key, bearer_token=bearer_token)

        async def _request_hook(request: httpx.Request) -> None:
            _apply_sensitive_auth_headers(
                request,
                trusted_authority=trusted_authority,
                auth_headers=auth_headers,
                auth_provider=auth_provider,
            )

        effective_transport = transport
        if max_retries > 0:
            inner = effective_transport or httpx.AsyncHTTPTransport()
            retry_transport = AsyncRetryTransport(inner, max_retries=max_retries)
            effective_transport = retry_transport
            self._retry_methods = retry_transport.retry_methods

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            follow_redirects=follow_redirects,
            transport=effective_transport,
            event_hooks={"request": [_request_hook]},
        )

    async def __aenter__(self) -> "AsyncHonuaClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Release underlying HTTP resources if this instance owns the client.

        When the client was constructed with an externally supplied
        :class:`httpx.AsyncClient`, ownership stays with the caller and
        this coroutine is a no-op.
        """
        if self._owns_client:
            await self._client.aclose()

    def with_options(
        self,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        base_url: str | None = None,
    ) -> "AsyncHonuaClient":
        """Return a clone with overridden options.

        When only ``timeout`` and/or ``max_retries`` are supplied, the
        returned client **reuses the original's** :class:`httpx.AsyncClient`
        and its connection pool — only the per-request ``timeout`` and
        (optionally) the per-request retry budget are overridden. In this
        transport-sharing mode the clone does **not** own the underlying
        client; awaiting :meth:`close` on the clone is a no-op. Only the
        original is responsible for closing the transport.

        **Passing ``base_url`` creates an independent client; the
        transport is NOT shared.** Because the underlying
        :class:`httpx.AsyncClient` binds its ``base_url`` (and
        authority-bound timeouts, event hooks, and connection-pool keys)
        at construction time, swapping the base URL on a shared client
        would silently target the wrong host for any code path that
        relies on those bindings. To avoid that footgun, supplying
        ``base_url`` builds a fresh :class:`httpx.AsyncClient` for the
        clone and the clone owns it — you must ``await
        clone.close()`` (or use ``async with``) independently of the
        original.

        Args:
            timeout: When set, overrides the per-request timeout. Smaller
                ``timeout`` values automatically build an independent
                client (with the smaller transport timeout); larger
                values reuse the parent's transport with a per-request
                ``httpx.Timeout(...)`` override.
            max_retries: When set, overrides the retry budget. ``0``
                disables retries on the clone via a per-request extension
                read by the retry transport.
            base_url: When set, the returned clone is fully independent
                (owns its own :class:`httpx.AsyncClient` and connection
                pool) and must be closed separately. The transport is
                NOT shared with the original.

        Returns:
            An :class:`AsyncHonuaClient` — transport-sharing when the
            override timeout is greater than or equal to the parent's
            configured timeout, independently-owned when ``base_url`` is
            supplied or when ``timeout`` is smaller than the parent's
            configured timeout.
        """
        if self._init_base_url is None and base_url is None and self._base_url is None:
            raise ValueError(
                "with_options() requires base_url when the original client was "
                "constructed with a pre-built httpx.AsyncClient."
            )
        needs_independent_clone = base_url is not None or (
            timeout is not None and timeout < self._init_timeout
        )
        if needs_independent_clone:
            # Independent clone: build a fresh httpx.AsyncClient so the new
            # base_url is honored end-to-end (URL resolution, authority-bound
            # timeouts, event hooks, connection pool keys), or so a smaller
            # transport timeout is actually applied (the parent's bound
            # timeout floors per-request overrides on the shared client).
            # The clone owns the new client and must be closed independently
            # of the original.
            effective_timeout = (
                timeout
                if (timeout is not None and timeout < self._init_timeout)
                else self._init_timeout
            )
            clone = self.__class__(
                base_url if base_url is not None else self._init_base_url,
                timeout=effective_timeout,
                api_key=self._init_api_key,
                bearer_token=self._init_bearer_token,
                auth_provider=self._init_auth_provider,
                follow_redirects=self._init_follow_redirects,
                transport=self._init_transport,
                max_retries=self._init_max_retries,
            )
            clone._options_timeout = (
                timeout if timeout is not None else self._options_timeout
            )
            clone._options_max_retries = (
                max_retries if max_retries is not None else self._options_max_retries
            )
            return clone

        # Shallow-copy ``self`` so future ``_init_*`` slots ride along
        # automatically; see the sync ``HonuaClient.with_options`` for
        # the full rationale.
        clone = copy.copy(self)
        clone._owns_client = False  # clone never closes the shared transport
        clone._options_timeout = (
            timeout if timeout is not None else self._options_timeout
        )
        clone._options_max_retries = (
            max_retries if max_retries is not None else self._options_max_retries
        )
        return clone

    async def readiness(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch the readiness payload from ``/healthz/ready``.

        Returns:
            The raw readiness JSON payload as a ``dict``.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server returned a non-success status.
            HonuaTransportError: The request failed before any response
                was received.
        """
        prep = _endpoints.build_readiness_request()
        return await self._request_json(
            prep.method,
            prep.path,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    async def capabilities(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> DataPlaneCapabilities:
        """Discover server-advertised data-plane protocols and feature flags.

        When the server does not expose ``/api/v1/capabilities`` (older
        deployments answer ``404``), this falls back to deriving a
        :class:`DataPlaneCapabilities` from readiness and the service
        catalog.

        Returns:
            A :class:`DataPlaneCapabilities` describing protocol/feature
            availability.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request` (and to the readiness/list_services fallback).

        Raises:
            HonuaHttpError: The server returned a non-404 error status.
            HonuaTransportError: The request failed at the transport layer.
        """
        prep = _endpoints.build_capabilities_request()
        try:
            payload = await self._request_json(
                prep.method,
                prep.path,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        except HonuaHttpError as exc:
            if exc.status_code != 404:
                raise
            return DataPlaneCapabilities.from_discovery(
                readiness=await self.readiness(timeout=timeout, extra_headers=extra_headers),
                catalog=await self.list_services(timeout=timeout, extra_headers=extra_headers),
            )
        return _endpoints.parse_capabilities(payload)

    async def supports(
        self,
        capability: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> bool:
        """Return whether the server advertises a given data-plane capability.

        Args:
            capability: Capability identifier (protocol slug such as
                ``"feature-server"`` or a feature flag name).

        Returns:
            ``True`` when the server advertises the capability,
            ``False`` otherwise.

        Raises:
            HonuaHttpError: The underlying capability lookup failed
                server-side with a non-404 status.
            HonuaTransportError: The capability lookup failed at the
                transport layer.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`capabilities`.
        """
        return (
            await self.capabilities(timeout=timeout, extra_headers=extra_headers)
        ).supports(capability)

    def source(self, descriptor: "SourceDescriptor | Mapping[str, Any]") -> "AsyncSource":
        """Return an async source-bound facade for Source/Query/Result workflows.

        Args:
            descriptor: A :class:`SourceDescriptor` (or mapping convertible
                to one) identifying the dataset and protocol the facade
                should target.

        Returns:
            An :class:`AsyncSource` bound to this client's transport.
        """
        from .source import AsyncSource

        return AsyncSource(self, descriptor)

    async def list_services(
        self,
        *,
        response_format: str = "json",
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """List services from the GeoServices catalog endpoint.

        Args:
            response_format: Value passed as the ``f`` query parameter on
                ``/rest/services`` (defaults to ``"json"``).

        Returns:
            The raw catalog payload as a ``dict``.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server returned a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        prep = _endpoints.build_list_services_request(response_format=response_format)
        return await self._request_json(
            prep.method,
            prep.path,
            params=prep.params,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    async def list_service_summaries(
        self,
        *,
        response_format: str = "json",
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[ServiceSummary]:
        """List services as typed catalog summaries.

        Args:
            response_format: Value passed as the ``f`` query parameter on
                ``/rest/services`` (defaults to ``"json"``).

        Returns:
            A list of :class:`ServiceSummary` objects; empty when the
            catalog payload does not contain a ``services`` list.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`list_services`.

        Raises:
            HonuaHttpError: The server returned a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        return _endpoints.parse_service_summaries(
            await self.list_services(
                response_format=response_format,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        )

    def ogc_features(self) -> "AsyncHonuaOgcFeatures":
        """Return an async OGC API Features wrapper bound to this client.

        Returns:
            An :class:`AsyncHonuaOgcFeatures` facade that reuses this
            client's HTTP session.
        """
        from .ogc import AsyncHonuaOgcFeatures

        return AsyncHonuaOgcFeatures(self)

    def geocoder(self, locator: str = "World") -> "AsyncHonuaGeocodingClient":
        """Return an async GeocodeServer wrapper that reuses this client's session.

        Args:
            locator: GeocodeServer locator name (defaults to ``"World"``).

        Returns:
            An :class:`AsyncHonuaGeocodingClient` bound to ``locator``.
        """
        from .async_geocoding import AsyncHonuaGeocodingClient

        return AsyncHonuaGeocodingClient(str(self._base_url), locator_name=locator, client=self._client)

    def feature_server(self, service_id: str) -> "AsyncGeoServicesFeatureServerClient":
        """Return an async GeoServices FeatureServer wrapper for a service.

        Args:
            service_id: Service identifier as advertised by the catalog.

        Returns:
            An :class:`AsyncGeoServicesFeatureServerClient` bound to this
            client's transport.

        Raises:
            HonuaHttpError: A subsequent request issued through the
                returned wrapper fails server-side (the factory itself
                does not perform I/O).
        """
        from .protocols import AsyncGeoServicesFeatureServerClient

        return AsyncGeoServicesFeatureServerClient(self, service_id)

    def map_server(self, service_id: str) -> "AsyncGeoServicesMapServerClient":
        """Return an async GeoServices MapServer wrapper for a service.

        Args:
            service_id: Service identifier as advertised by the catalog.

        Returns:
            An :class:`AsyncGeoServicesMapServerClient` bound to this
            client's transport.
        """
        from .protocols import AsyncGeoServicesMapServerClient

        return AsyncGeoServicesMapServerClient(self, service_id)

    def image_server(self, service_id: str | None = None) -> "AsyncGeoServicesImageServerClient":
        """Return an async GeoServices ImageServer wrapper.

        Args:
            service_id: Optional service identifier; when ``None`` the
                wrapper targets the deployment-level ImageServer surface.

        Returns:
            An :class:`AsyncGeoServicesImageServerClient` bound to this
            client.
        """
        from .protocols import AsyncGeoServicesImageServerClient

        return AsyncGeoServicesImageServerClient(self, service_id)

    def geometry_server(self) -> "AsyncGeoServicesGeometryServerClient":
        """Return the async GeoServices GeometryServer wrapper.

        Returns:
            An :class:`AsyncGeoServicesGeometryServerClient` bound to
            this client's transport.
        """
        from .protocols import AsyncGeoServicesGeometryServerClient

        return AsyncGeoServicesGeometryServerClient(self)

    def ogc_maps(self) -> "AsyncOgcMapsClient":
        """Return an async OGC API Maps wrapper.

        Returns:
            An :class:`AsyncOgcMapsClient` bound to this client's
            transport.
        """
        from .protocols import AsyncOgcMapsClient

        return AsyncOgcMapsClient(self)

    def ogc_tiles(self) -> "AsyncOgcTilesClient":
        """Return an async OGC API Tiles wrapper.

        Returns:
            An :class:`AsyncOgcTilesClient` bound to this client's
            transport.
        """
        from .protocols import AsyncOgcTilesClient

        return AsyncOgcTilesClient(self)

    def ogc_coverages(self) -> "AsyncOgcCoveragesClient":
        """Return an async OGC API Coverages wrapper.

        Returns:
            An :class:`AsyncOgcCoveragesClient` bound to this client's
            transport.
        """
        from .protocols import AsyncOgcCoveragesClient

        return AsyncOgcCoveragesClient(self)

    def ogc_processes(self) -> "AsyncOgcProcessesClient":
        """Return an async OGC API Processes wrapper.

        Returns:
            An :class:`AsyncOgcProcessesClient` bound to this client's
            transport.
        """
        from .protocols import AsyncOgcProcessesClient

        return AsyncOgcProcessesClient(self)

    def ogc_records(self) -> "AsyncOgcRecordsClient":
        """Return an async OGC API Records wrapper."""
        from .protocols import AsyncOgcRecordsClient

        return AsyncOgcRecordsClient(self)

    def geoprocessing(self) -> "AsyncHonuaGeoprocessing":
        """Return an async geoprocessing (OGC API Processes) client.

        Returns:
            An :class:`~honua_sdk.geoprocessing.AsyncHonuaGeoprocessing` bound
            to this client's transport for listing/describing processes and
            submitting + polling + fetching the results of process executions.
        """
        from .geoprocessing import AsyncHonuaGeoprocessing

        return AsyncHonuaGeoprocessing(self)

    def workflow(self) -> "AsyncHonuaWorkflow":
        """Return an async workflow package authoring + publication client.

        Returns:
            An :class:`~honua_sdk.workflow.AsyncHonuaWorkflow` bound to this
            client's transport for authoring workflow package drafts,
            snapshotting immutable versions, validating / dry-running /
            publishing them, and running publications over the server's
            ``/api/v1/console`` workflow package surface (the durable
            replacement for the dropped GeoETL pipeline endpoints; admin
            authorization required server-side).
        """
        from .workflow import AsyncHonuaWorkflow

        return AsyncHonuaWorkflow(self)

    def stac(self) -> "AsyncStacClient":
        """Return an async STAC API wrapper.

        Returns:
            An :class:`AsyncStacClient` bound to this client's transport.
        """
        from .protocols import AsyncStacClient

        return AsyncStacClient(self)

    def scenes(self) -> "AsyncSceneClient":
        """Return an async 3D scene metadata + resolution wrapper.

        Returns:
            An :class:`AsyncSceneClient` bound to this client's transport.
        """
        from .protocols import AsyncSceneClient

        return AsyncSceneClient(self)

    def elevation(self) -> "AsyncElevationClient":
        """Return an async elevation HTTP API wrapper.

        Returns:
            An :class:`AsyncElevationClient` bound to this client's transport.
        """
        from .protocols.scenes import AsyncElevationClient

        return AsyncElevationClient(self)

    def wfs(self) -> "AsyncWfsClient":
        """Return an async WFS 2.0 wrapper.

        Returns:
            An :class:`AsyncWfsClient` bound to this client's transport.
        """
        from .protocols import AsyncWfsClient

        return AsyncWfsClient(self)

    def wms(self, service_id: str) -> "AsyncWmsClient":
        """Return an async service-scoped WMS wrapper.

        Args:
            service_id: Service identifier as advertised by the catalog.

        Returns:
            An :class:`AsyncWmsClient` bound to this client's transport.
        """
        from .protocols import AsyncWmsClient

        return AsyncWmsClient(self, service_id)

    def wmts(self, service_id: str) -> "AsyncWmtsClient":
        """Return an async service-scoped WMTS wrapper.

        Args:
            service_id: Service identifier as advertised by the catalog.

        Returns:
            An :class:`AsyncWmtsClient` bound to this client's transport.
        """
        from .protocols import AsyncWmtsClient

        return AsyncWmtsClient(self, service_id)

    def odata(self) -> "AsyncODataClient":
        """Return an async OData v4 wrapper.

        Returns:
            An :class:`AsyncODataClient` bound to this client's transport.
        """
        from .protocols import AsyncODataClient

        return AsyncODataClient(self)

    async def query(
        self,
        source: str | FeatureQuery,
        *,
        protocol: QueryProtocol | None = None,
        layer_id: int | None = None,
        where: str | None = None,
        filter: str | None = None,
        bbox: str | Sequence[int | float] | None = None,
        fields: str | Sequence[str] | None = None,
        return_geometry: bool | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> FeatureQueryResult:
        """Run a protocol-neutral feature query and collect normalized features.

        Args:
            source: Either a source identifier (service name, OGC
                collection id, STAC collection id, OData entity set) or a
                pre-built :class:`FeatureQuery`. When a query object is
                provided the remaining keyword arguments are ignored.
            protocol: Override the protocol resolved from ``source``.
            layer_id: FeatureServer layer index or OData layer id when the
                protocol requires one.
            where: GeoServices-style ``WHERE`` clause (FeatureServer only).
            filter: CQL2/OData filter expression (OGC Features / STAC / OData).
            bbox: Spatial filter as a list/tuple of coordinates or comma
                string. Not supported when ``protocol`` is OData.
            fields: Attribute selection; comma-string or sequence of names.
            return_geometry: Whether to include geometry (FeatureServer).
            page_size: Page size hint for paginated protocols.
            limit: Maximum number of features to collect across all pages.
            max_pages: Safety cap on pages walked.
            extra_params: Additional protocol-specific query parameters
                merged into each request.
            timeout: Per-call timeout override forwarded to every page
                request across all protocols (FeatureServer, OGC Features,
                STAC, OData). Accepts a ``float`` seconds value or an
                :class:`httpx.Timeout`.
            idempotency_key: Stripe-style ``Idempotency-Key`` header
                value attached to every page request. Merged into
                ``extra_headers`` before forwarding.
            extra_headers: Additional HTTP headers merged into every
                page request across all protocols.

        Returns:
            A :class:`FeatureQueryResult` containing the normalized
            features, resolved protocol, source, and the effective query.

        Raises:
            ValueError: ``bbox`` is supplied for the OData protocol.
            HonuaHttpError: A page request returned a non-success status.
            HonuaTransportError: A page request failed at the transport layer.
        """
        query = resolve_feature_query(
            source,
            protocol=protocol,
            layer_id=layer_id,
            where=where,
            filter=filter,
            bbox=bbox,
            fields=fields,
            return_geometry=return_geometry,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            extra_params=extra_params,
        )
        normalized_protocol = normalize_query_protocol(query.protocol)  # type: ignore[arg-type]
        validate_filter_routing(query, normalized_protocol)
        features, exceeded, total_count, pages_seen = await self._collect_query_pages(
            query,
            normalized_protocol,
            timeout=timeout,
            extra_headers=merge_idempotency_into_headers(extra_headers, idempotency_key),
        )
        return FeatureQueryResult(
            features=features,
            protocol=normalized_protocol,
            source=query.source,
            query=query,
            exceeded_transfer_limit=exceeded,
            total_count=total_count,
            pages_seen=pages_seen,
        )

    async def _collect_query_pages(
        self,
        query: FeatureQuery,
        normalized_protocol: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> tuple[tuple[QueryFeature, ...], bool, int | None, int]:
        """Walk protocol pages and capture pagination signals (async).

        Returns ``(features, exceeded_transfer_limit, total_count, pages_seen)``.

        Per-call ``timeout`` / ``extra_headers`` are forwarded to every
        protocol's pagination wrapper (FeatureServer, OGC Features, STAC,
        OData). The kwarg construction for each protocol lives in
        :mod:`._query_dispatch` so the sync and async dispatchers share
        every non-IO step.
        """
        collected: list[QueryFeature] = []
        exceeded = False
        total_count: int | None = None
        pages_seen = 0
        limit = query.limit

        def _extend(items: list[QueryFeature]) -> bool:
            if limit is not None:
                remaining = limit - len(collected)
                if remaining <= 0:
                    return True
                items = items[:remaining]
            collected.extend(items)
            return limit is not None and len(collected) >= limit

        if normalized_protocol == "feature-server":
            async for page in self.feature_server(query.source).query_pages(
                **feature_server_pages_kwargs(
                    query, timeout=timeout, extra_headers=extra_headers
                ),
            ):
                pages_seen += 1
                exceeded = bool(page.exceeded_transfer_limit)
                page_features = [
                    query_feature_from_feature_server(
                        feature, source=query.source, protocol=normalized_protocol
                    )
                    for feature in page.features
                ]
                if _extend(page_features):
                    break
            return tuple(collected), exceeded, len(collected), pages_seen

        if normalized_protocol == "ogc-features":
            last_page: Any = None
            async for page in self.ogc_features().collection(query.source).items_pages(  # type: ignore[assignment]
                **ogc_features_pages_kwargs(
                    query, timeout=timeout, extra_headers=extra_headers
                ),
            ):
                pages_seen += 1
                last_page = page
                page_features = [
                    query_feature_from_geojson(
                        item, source=query.source, protocol=normalized_protocol
                    )
                    for item in features_from_geojson_page(page)  # type: ignore[arg-type]
                ]
                if _extend(page_features):
                    break
            total_count, exceeded = ogc_pagination_signals(last_page)
            return tuple(collected), exceeded, total_count, pages_seen

        if normalized_protocol == "stac":
            async for page in self.stac().item_pages(  # type: ignore[assignment]
                query.source,
                **stac_pages_kwargs(
                    query, timeout=timeout, extra_headers=extra_headers
                ),
            ):
                pages_seen += 1
                last_page = page
                page_features = [
                    query_feature_from_geojson(
                        item, source=query.source, protocol=normalized_protocol
                    )
                    for item in features_from_geojson_page(page)  # type: ignore[arg-type]
                ]
                if _extend(page_features):
                    break
            total_count, exceeded = ogc_pagination_signals(last_page)
            return tuple(collected), exceeded, total_count, pages_seen

        reject_odata_bbox(query)
        async for page in self.odata().features_pages(  # type: ignore[assignment]
            **odata_pages_kwargs(
                query, timeout=timeout, extra_headers=extra_headers
            ),
        ):
            pages_seen += 1
            last_page = page
            page_features = [
                query_feature_from_mapping(
                    item, source=query.source, protocol=normalized_protocol
                )
                for item in odata_features_from_page(page)  # type: ignore[arg-type]
            ]
            if _extend(page_features):
                break
        total_count, exceeded = odata_pagination_signals(last_page)
        return tuple(collected), exceeded, total_count, pages_seen

    async def iter_query(
        self,
        source: str | FeatureQuery,
        *,
        protocol: QueryProtocol | None = None,
        layer_id: int | None = None,
        where: str | None = None,
        filter: str | None = None,
        bbox: str | Sequence[int | float] | None = None,
        fields: str | Sequence[str] | None = None,
        return_geometry: bool | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> AsyncIterator[QueryFeature]:
        """Stream normalized features from FeatureServer, OGC Features, STAC, or OData.

        This is the streaming counterpart to :meth:`query` — features are
        yielded one at a time so callers can short-circuit large result
        sets.

        Args:
            source: Source identifier or pre-built :class:`FeatureQuery`.
                When a query object is provided the remaining keyword
                arguments are ignored.
            protocol: Override the protocol resolved from ``source``.
            layer_id: FeatureServer layer index or OData layer id when the
                protocol requires one.
            where: GeoServices-style ``WHERE`` clause (FeatureServer only).
            filter: CQL2/OData filter expression for OGC/STAC/OData.
            bbox: Spatial filter; not supported for OData.
            fields: Attribute selection.
            return_geometry: Whether to include geometry (FeatureServer).
            page_size: Page size hint for paginated protocols.
            limit: Maximum number of features to yield across all pages.
            max_pages: Safety cap on pages walked.
            extra_params: Protocol-specific query parameters merged into
                each request.

        Per-call ``timeout`` / ``extra_headers`` are forwarded to every
        protocol's pagination wrapper (FeatureServer, OGC Features, STAC,
        OData). ``idempotency_key`` is merged into ``extra_headers``
        before forwarding.

        Yields:
            Normalized :class:`QueryFeature` objects.

        Raises:
            ValueError: ``bbox`` is supplied for the OData protocol.
            HonuaHttpError: A page request returned a non-success status.
            HonuaTransportError: A page request failed at the transport layer.
        """
        query = resolve_feature_query(
            source,
            protocol=protocol,
            layer_id=layer_id,
            where=where,
            filter=filter,
            bbox=bbox,
            fields=fields,
            return_geometry=return_geometry,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            extra_params=extra_params,
        )
        normalized_protocol = normalize_query_protocol(query.protocol)  # type: ignore[arg-type]
        validate_filter_routing(query, normalized_protocol)
        extra_headers = merge_idempotency_into_headers(extra_headers, idempotency_key)

        if normalized_protocol == "feature-server":
            async for feature in self.feature_server(query.source).query_items(
                **feature_server_items_kwargs(
                    query, timeout=timeout, extra_headers=extra_headers
                ),
            ):
                yield query_feature_from_feature_server(
                    feature,
                    source=query.source,
                    protocol=normalized_protocol,
                )
            return

        if normalized_protocol == "ogc-features":
            async for feature in self.ogc_features().collection(query.source).iter_items(  # type: ignore[assignment]
                **ogc_features_items_kwargs(
                    query, timeout=timeout, extra_headers=extra_headers
                ),
            ):
                yield query_feature_from_geojson(
                    feature,  # type: ignore[arg-type]
                    source=query.source,
                    protocol=normalized_protocol,
                )
            return

        if normalized_protocol == "stac":
            async for feature in self.stac().iter_items(  # type: ignore[assignment]
                query.source,
                **stac_items_kwargs(
                    query, timeout=timeout, extra_headers=extra_headers
                ),
            ):
                yield query_feature_from_geojson(
                    feature,  # type: ignore[arg-type]
                    source=query.source,
                    protocol=normalized_protocol,
                )
            return

        reject_odata_bbox(query)
        async for feature in self.odata().iter_features(  # type: ignore[assignment]
            **odata_items_kwargs(
                query, timeout=timeout, extra_headers=extra_headers
            ),
        ):
            yield query_feature_from_mapping(
                feature,  # type: ignore[arg-type]
                source=query.source,
                protocol=normalized_protocol,
            )

    async def query_features(
        self,
        service_id: str,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: str | Sequence[str] = "*",
        return_geometry: bool = True,
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Query features from a FeatureServer layer and return raw JSON.

        Args:
            service_id: GeoServices service identifier; URL-encoded.
            layer_id: Numeric layer index within the FeatureServer.
            where: GeoServices ``WHERE`` clause; defaults to ``"1=1"``.
            out_fields: Field selection; either a comma-string or sequence
                of names. Defaults to ``"*"``.
            return_geometry: Whether the server should include geometry.
            extra_params: Additional query-string parameters merged into
                the request (e.g. ``resultOffset``, ``resultRecordCount``).

        Returns:
            The raw FeatureServer ``query`` response as a ``dict``.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server returned a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        prep = _endpoints.build_query_features_request(
            service_id,
            layer_id,
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            extra_params=extra_params,
        )
        return await self._request_json(
            prep.method,
            prep.path,
            params=prep.params,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    async def query_feature_set(
        self,
        service_id: str,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: str | Sequence[str] = "*",
        return_geometry: bool = True,
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> FeatureSet:
        """Query a FeatureServer layer and return a typed :class:`FeatureSet`.

        Args:
            service_id: GeoServices service identifier; URL-encoded.
            layer_id: Numeric layer index within the FeatureServer.
            where: GeoServices ``WHERE`` clause; defaults to ``"1=1"``.
            out_fields: Field selection; either a comma-string or sequence
                of names. Defaults to ``"*"``.
            return_geometry: Whether the server should include geometry.
            extra_params: Additional query-string parameters merged into
                the request (e.g. ``resultOffset``, ``resultRecordCount``).

        Returns:
            A :class:`FeatureSet` parsed from the raw query response.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`query_features`.

        Raises:
            HonuaHttpError: The server returned a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        return _endpoints.parse_feature_set(
            await self.query_features(
                service_id,
                layer_id,
                where=where,
                out_fields=out_fields,
                return_geometry=return_geometry,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        )

    async def query_features_all(
        self,
        service_id: str,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: str | Sequence[str] = "*",
        return_geometry: bool = True,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int = 100,
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[Feature]:
        """Page through FeatureServer query results and return typed features.

        Walks the FeatureServer ``query`` endpoint with ``resultOffset`` /
        ``resultRecordCount`` until either ``limit`` is reached, the
        server stops indicating that the transfer limit was exceeded, or
        ``max_pages`` is hit.

        Args:
            service_id: GeoServices service identifier; URL-encoded.
            layer_id: Numeric layer index within the FeatureServer.
            where: GeoServices ``WHERE`` clause; defaults to ``"1=1"``.
            out_fields: Field selection; comma-string or sequence of names.
            return_geometry: Whether the server should include geometry.
            page_size: Page size hint forwarded as ``resultRecordCount``.
                Must be greater than zero.
            limit: Optional cap on the total number of features returned.
            max_pages: Safety cap on the number of pages walked. Must be
                greater than zero.
            extra_params: Additional query parameters. Any
                ``resultOffset`` value is honored as the starting offset.

        Returns:
            A list of typed :class:`Feature` objects up to ``limit``.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to every page-level :meth:`query_feature_set` call.

        Raises:
            ValueError: ``page_size`` or ``max_pages`` is not positive.
            HonuaHttpError: A page request returned a non-success status.
            HonuaTransportError: A page request failed at the transport layer.
        """
        _endpoints.validate_paging(page_size, max_pages)
        if limit is not None and limit <= 0:
            return []

        features: list[Feature] = []
        offset = _endpoints.initial_offset(extra_params)
        base_extra_params = dict(extra_params or {})
        for _ in range(max_pages):
            remaining = None if limit is None else limit - len(features)
            if remaining is not None and remaining <= 0:
                break
            record_count = _endpoints.page_record_count(page_size, remaining)
            page = await self.query_feature_set(
                service_id,
                layer_id,
                where=where,
                out_fields=out_fields,
                return_geometry=return_geometry,
                extra_params=_endpoints.page_extra_params(
                    base_extra_params,
                    offset=offset,
                    record_count=record_count,
                ),
                timeout=timeout,
                extra_headers=extra_headers,
            )
            page_features = list(page.features)
            if remaining is not None:
                page_features = page_features[:remaining]
            features.extend(page_features)
            if len(page.features) < record_count or not page.exceeded_transfer_limit:
                break
            offset += len(page.features)

        return features

    async def apply_edits(
        self,
        service_id: str,
        layer_id: int,
        *,
        adds: Sequence[Mapping[str, Any]] | None = None,
        updates: Sequence[Mapping[str, Any]] | None = None,
        deletes: Sequence[int] | str | None = None,
        rollback_on_failure: bool = True,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Submit a layer-level GeoServices ``applyEdits`` request.

        Args:
            service_id: GeoServices service identifier; URL-encoded.
            layer_id: Numeric layer index within the FeatureServer.
            adds: Sequence of feature mappings to insert.
            updates: Sequence of feature mappings to update by ``OBJECTID``.
            deletes: Either a sequence of object ids or a comma-string of
                ids to delete.
            rollback_on_failure: Whether the server should roll the entire
                batch back if any individual edit fails.
            idempotency_key: Stripe-style ``Idempotency-Key`` header value.
                When ``None`` and the underlying retry transport is
                configured to retry ``POST`` (i.e. the caller opted in via
                ``retry_methods``), a fresh ``uuid4`` hex is generated so
                that retries are de-duplicated server-side. Pass an explicit
                value to make the request idempotent across application
                retries as well.

        Returns:
            The raw ``applyEdits`` response payload as a ``dict``.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server returned a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        prep = _endpoints.build_apply_edits_request(
            service_id,
            layer_id,
            adds=adds,
            updates=updates,
            deletes=deletes,
            rollback_on_failure=rollback_on_failure,
            headers=self._idempotency_headers(idempotency_key),
        )
        return await self._request_json(
            prep.method,
            prep.path,
            json_body=prep.json,
            headers=prep.headers,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    async def apply_edits_result(
        self,
        service_id: str,
        layer_id: int,
        *,
        adds: Sequence[Mapping[str, Any]] | None = None,
        updates: Sequence[Mapping[str, Any]] | None = None,
        deletes: Sequence[int] | str | None = None,
        rollback_on_failure: bool = True,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> ApplyEditsResult:
        """Submit ``applyEdits`` and return typed per-operation results.

        Args:
            service_id: GeoServices service identifier; URL-encoded.
            layer_id: Numeric layer index within the FeatureServer.
            adds: Sequence of feature mappings to insert.
            updates: Sequence of feature mappings to update by ``OBJECTID``.
            deletes: Either a sequence of object ids or a comma-string of
                ids to delete.
            rollback_on_failure: Whether the server should roll the entire
                batch back if any individual edit fails.
            idempotency_key: Stripe-style ``Idempotency-Key`` header value;
                forwarded to :meth:`apply_edits`. See that method for
                auto-generation semantics.

        Returns:
            An :class:`ApplyEditsResult` parsed from the response.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`apply_edits`.

        Raises:
            HonuaHttpError: The server returned a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        return _endpoints.parse_apply_edits_result(
            await self.apply_edits(
                service_id,
                layer_id,
                adds=adds,
                updates=updates,
                deletes=deletes,
                rollback_on_failure=rollback_on_failure,
                idempotency_key=idempotency_key,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        )

    def _idempotency_headers(self, idempotency_key: str | None) -> dict[str, str] | None:
        """Build the ``Idempotency-Key`` header dict, auto-generating if needed."""
        return _endpoints.build_idempotency_headers(
            idempotency_key, retry_methods=self._retry_methods
        )

    async def export_map(
        self,
        service_id: str,
        bbox: Sequence[float] | str,
        *,
        size: tuple[int, int] = (400, 400),
        image_format: str = "png",
        transparent: bool = True,
        dpi: int = 96,
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> bytes:
        """Request rendered map bytes from the MapServer ``export`` endpoint.

        Args:
            service_id: GeoServices service identifier; URL-encoded.
            bbox: Bounding box as a sequence of floats (xmin, ymin, xmax,
                ymax) or pre-formatted comma string.
            size: ``(width, height)`` in pixels; defaults to ``(400, 400)``.
            image_format: Output image format (``"png"``, ``"jpg"``, ...).
            transparent: Whether the rendered image should be transparent
                where there is no data.
            dpi: Output DPI value forwarded to the server.
            extra_params: Additional query parameters merged into the
                request (e.g. ``layers``, ``layerDefs``).

        Returns:
            The raw image bytes returned by the server.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server returned a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        prep = _endpoints.build_export_map_request(
            service_id,
            bbox,
            size=size,
            image_format=image_format,
            transparent=transparent,
            dpi=dpi,
            extra_params=extra_params,
        )
        response = await self._request(
            prep.method,
            prep.path,
            params=prep.params,
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return response.content

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        response = await self._request(
            method,
            path,
            params=params,
            json_body=json_body,
            headers=headers,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return _endpoints.parse_json_response_body(response)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        """Issue a single HTTP request (async), applying per-call overrides.

        Per-request options (Stripe / OpenAI-SDK shaped):

        * ``timeout``: overrides client- and ``with_options``-level timeouts
          for this call only.
        * ``extra_headers``: merged into the outbound request headers.
        * ``idempotency_key``: when set, attaches an ``Idempotency-Key``
          header to the outbound request, overriding any header of the
          same name in ``headers`` / ``extra_headers``.
        """
        # Build a full URL so httpx does not re-decode percent-encoded
        # path segments during base-URL resolution.
        url = self._base_url.copy_with(raw_path=path.encode("ascii"))
        merged_headers = merge_request_headers(headers, extra_headers, idempotency_key)
        request_kwargs: dict[str, Any] = {
            "method": method,
            "url": url,
            "params": params,
            "json": json_body,
            "headers": merged_headers,
        }
        if timeout is not None:
            request_kwargs["timeout"] = (
                timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout)
            )
        elif self._options_timeout is not None:
            request_kwargs["timeout"] = httpx.Timeout(self._options_timeout)
        if self._options_max_retries is not None:
            request_kwargs["extensions"] = {
                "honua_max_retries": self._options_max_retries,
            }
        try:
            response = await self._client.request(**request_kwargs)
        except httpx.HTTPError as exc:
            raise _to_transport_error(exc) from exc
        if response.status_code >= 400:
            raise _to_http_error(response)
        return response


