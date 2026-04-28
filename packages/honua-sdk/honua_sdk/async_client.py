"""Asynchronous HTTP client for Honua Server APIs."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any

import httpx

from ._http import (
    _apply_sensitive_auth_headers,
    _build_sensitive_auth_headers,
    _encode_path_segment,
    _extract_trusted_authority,
    _normalize_base_url,
    _to_http_error,
    _to_transport_error,
    _validate_auth_configuration,
    _validate_external_client_auth_configuration,
)
from ._async_retry import AsyncRetryTransport
from ._query import (
    bbox_text,
    feature_server_extra_params,
    field_list,
    field_text,
    normalize_query_protocol,
    odata_layer_id,
    query_feature_from_feature_server,
    query_feature_from_geojson,
    query_feature_from_mapping,
    query_filter,
    query_max_pages,
    query_page_size,
    resolve_feature_query,
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
    from .auth import AuthProvider
    from .async_geocoding import AsyncHonuaGeocodingClient
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
        AsyncOgcTilesClient,
        AsyncStacClient,
        AsyncWfsClient,
        AsyncWmsClient,
        AsyncWmtsClient,
    )
    from .models import SourceDescriptor
    from .source import AsyncSource


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


class AsyncHonuaClient:
    """Async task-oriented client for common Honua workflows."""

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

        self._owns_client = client is None
        if client is not None:
            self._client = client
            return

        normalized_base_url = _normalize_base_url(base_url)
        trusted_authority = _extract_trusted_authority(httpx.URL(normalized_base_url))
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
            effective_transport = AsyncRetryTransport(inner, max_retries=max_retries)

        self._client = httpx.AsyncClient(
            base_url=normalized_base_url,
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
        """Release underlying resources if this instance owns the HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def readiness(self) -> dict[str, Any]:
        """Get readiness status from ``/healthz/ready``."""
        return await self._request_json("GET", "/healthz/ready")

    async def capabilities(self) -> DataPlaneCapabilities:
        """Discover server-advertised data-plane protocols and feature flags."""
        try:
            payload = await self._request_json("GET", "/api/v1/capabilities")
        except HonuaHttpError as exc:
            if exc.status_code != 404:
                raise
            return DataPlaneCapabilities.from_discovery(
                readiness=await self.readiness(),
                catalog=await self.list_services(),
            )
        return DataPlaneCapabilities.from_dict(payload)

    async def supports(self, capability: str) -> bool:
        """Return whether a data-plane protocol or feature is advertised."""
        return (await self.capabilities()).supports(capability)

    def source(self, descriptor: "SourceDescriptor | Mapping[str, Any]") -> "AsyncSource":
        """Return an async source-bound facade for canonical Source/Query/Result workflows."""
        from .source import AsyncSource

        return AsyncSource(self, descriptor)

    async def list_services(self, *, response_format: str = "json") -> dict[str, Any]:
        """List services from the GeoServices catalog endpoint."""
        return await self._request_json(
            "GET",
            "/rest/services",
            params={"f": response_format},
        )

    async def list_service_summaries(self, *, response_format: str = "json") -> list[ServiceSummary]:
        """List services as typed catalog summaries."""
        response = await self.list_services(response_format=response_format)
        services = response.get("services")
        if not isinstance(services, list):
            return []
        return [ServiceSummary.from_dict(service) for service in services if isinstance(service, Mapping)]

    def ogc_features(self) -> "AsyncHonuaOgcFeatures":
        """Return an async OGC API Features wrapper bound to this client."""
        from .ogc import AsyncHonuaOgcFeatures

        return AsyncHonuaOgcFeatures(self)

    def geocoder(self, locator: str = "World") -> "AsyncHonuaGeocodingClient":
        """Return an async GeocodeServer wrapper that reuses this client's HTTP session."""
        from .async_geocoding import AsyncHonuaGeocodingClient

        return AsyncHonuaGeocodingClient(str(self._client._base_url), locator_name=locator, client=self._client)

    def feature_server(self, service_id: str) -> "AsyncGeoServicesFeatureServerClient":
        """Return an async GeoServices FeatureServer wrapper for a service."""
        from .protocols import AsyncGeoServicesFeatureServerClient

        return AsyncGeoServicesFeatureServerClient(self, service_id)

    def map_server(self, service_id: str) -> "AsyncGeoServicesMapServerClient":
        """Return an async GeoServices MapServer wrapper for a service."""
        from .protocols import AsyncGeoServicesMapServerClient

        return AsyncGeoServicesMapServerClient(self, service_id)

    def image_server(self, service_id: str | None = None) -> "AsyncGeoServicesImageServerClient":
        """Return an async GeoServices ImageServer wrapper."""
        from .protocols import AsyncGeoServicesImageServerClient

        return AsyncGeoServicesImageServerClient(self, service_id)

    def geometry_server(self) -> "AsyncGeoServicesGeometryServerClient":
        """Return the async GeoServices GeometryServer wrapper."""
        from .protocols import AsyncGeoServicesGeometryServerClient

        return AsyncGeoServicesGeometryServerClient(self)

    def ogc_maps(self) -> "AsyncOgcMapsClient":
        """Return an async OGC API Maps wrapper."""
        from .protocols import AsyncOgcMapsClient

        return AsyncOgcMapsClient(self)

    def ogc_tiles(self) -> "AsyncOgcTilesClient":
        """Return an async OGC API Tiles wrapper."""
        from .protocols import AsyncOgcTilesClient

        return AsyncOgcTilesClient(self)

    def ogc_coverages(self) -> "AsyncOgcCoveragesClient":
        """Return an async OGC API Coverages wrapper."""
        from .protocols import AsyncOgcCoveragesClient

        return AsyncOgcCoveragesClient(self)

    def ogc_processes(self) -> "AsyncOgcProcessesClient":
        """Return an async OGC API Processes wrapper."""
        from .protocols import AsyncOgcProcessesClient

        return AsyncOgcProcessesClient(self)

    def stac(self) -> "AsyncStacClient":
        """Return an async STAC API wrapper."""
        from .protocols import AsyncStacClient

        return AsyncStacClient(self)

    def wfs(self) -> "AsyncWfsClient":
        """Return an async WFS 2.0 wrapper."""
        from .protocols import AsyncWfsClient

        return AsyncWfsClient(self)

    def wms(self, service_id: str) -> "AsyncWmsClient":
        """Return an async service-scoped WMS wrapper."""
        from .protocols import AsyncWmsClient

        return AsyncWmsClient(self, service_id)

    def wmts(self, service_id: str) -> "AsyncWmtsClient":
        """Return an async service-scoped WMTS wrapper."""
        from .protocols import AsyncWmtsClient

        return AsyncWmtsClient(self, service_id)

    def odata(self) -> "AsyncODataClient":
        """Return an async OData v4 wrapper."""
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
    ) -> FeatureQueryResult:
        """Run a protocol-neutral feature query and collect normalized features."""
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
        normalized_protocol = normalize_query_protocol(query.protocol)
        return FeatureQueryResult(
            features=tuple([feature async for feature in self.iter_query(query)]),
            protocol=normalized_protocol,
            source=query.source,
            query=query,
        )

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
    ) -> AsyncIterator[QueryFeature]:
        """Stream normalized features from FeatureServer, OGC Features, STAC, or OData."""
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
        normalized_protocol = normalize_query_protocol(query.protocol)

        if normalized_protocol == "feature-server":
            feature_server_layer_id = 0 if query.layer_id is None else query.layer_id
            where_text = query.where if query.where is not None else (query.filter or "1=1")
            async for feature in self.feature_server(query.source).query_items(
                feature_server_layer_id,
                where=where_text,
                out_fields=field_text(query.fields, wildcard="*") or "*",
                return_geometry=query.return_geometry,
                page_size=query_page_size(query, 1000),
                limit=query.limit,
                max_pages=query_max_pages(query, 100),
                extra_params=feature_server_extra_params(query),
            ):
                yield query_feature_from_feature_server(
                    feature,
                    source=query.source,
                    protocol=normalized_protocol,
                )
            return

        if normalized_protocol == "ogc-features":
            properties = field_list(query.fields)
            async for feature in self.ogc_features().collection(query.source).iter_items(
                filter=query_filter(query),
                bbox=query.bbox,
                properties=properties,
                page_size=query.page_size,
                limit=query.limit,
                max_pages=query.max_pages,
                extra_params=query.extra_params,
            ):
                yield query_feature_from_geojson(
                    feature,
                    source=query.source,
                    protocol=normalized_protocol,
                )
            return

        if normalized_protocol == "stac":
            params = dict(query.extra_params)
            if query.bbox is not None:
                params.setdefault("bbox", bbox_text(query.bbox))
            if query_filter(query) is not None:
                params.setdefault("filter", query_filter(query))
            if field_text(query.fields) is not None:
                params.setdefault("fields", field_text(query.fields))
            async for feature in self.stac().iter_items(
                query.source,
                extra_params=params,
                page_size=query.page_size,
                limit=query.limit,
                max_pages=query.max_pages,
            ):
                yield query_feature_from_geojson(
                    feature,
                    source=query.source,
                    protocol=normalized_protocol,
                )
            return

        if query.bbox is not None:
            raise ValueError("bbox is not supported for OData shared queries; express spatial filters in `filter`.")
        async for feature in self.odata().iter_features(
            layer_id=odata_layer_id(query),
            filter=query_filter(query),
            select=field_list(query.fields),
            page_size=query.page_size,
            limit=query.limit,
            max_pages=query.max_pages,
            extra_params=query.extra_params,
        ):
            yield query_feature_from_mapping(
                feature,
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
    ) -> dict[str, Any]:
        """Query features from a FeatureServer layer."""
        service_segment = _encode_path_segment(service_id)
        if isinstance(out_fields, Sequence) and not isinstance(out_fields, str):
            out_fields_value = ",".join(str(value) for value in out_fields)
        else:
            out_fields_value = str(out_fields)

        params: dict[str, Any] = {
            "f": "json",
            "where": where,
            "outFields": out_fields_value,
            "returnGeometry": _bool_text(return_geometry),
        }
        if extra_params:
            params.update(extra_params)

        return await self._request_json(
            "GET",
            f"/rest/services/{service_segment}/FeatureServer/{layer_id}/query",
            params=params,
        )

    async def query_feature_set(
        self,
        service_id: str,
        layer_id: int,
        **kwargs: Any,
    ) -> FeatureSet:
        """Query a FeatureServer layer and return a typed feature set."""
        return FeatureSet.from_dict(await self.query_features(service_id, layer_id, **kwargs))

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
    ) -> list[Feature]:
        """Page through FeatureServer query results and return typed features."""
        if page_size <= 0:
            raise ValueError("page_size must be greater than zero.")
        if max_pages <= 0:
            raise ValueError("max_pages must be greater than zero.")
        if limit is not None and limit <= 0:
            return []

        features: list[Feature] = []
        offset = int((extra_params or {}).get("resultOffset", 0))
        base_extra_params = dict(extra_params or {})
        for _ in range(max_pages):
            remaining = None if limit is None else limit - len(features)
            if remaining is not None and remaining <= 0:
                break
            record_count = page_size if remaining is None else min(page_size, remaining)
            page_extra_params = {
                **base_extra_params,
                "resultOffset": offset,
                "resultRecordCount": record_count,
            }
            page = await self.query_feature_set(
                service_id,
                layer_id,
                where=where,
                out_fields=out_fields,
                return_geometry=return_geometry,
                extra_params=page_extra_params,
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
    ) -> dict[str, Any]:
        """Submit a layer-level applyEdits request."""
        service_segment = _encode_path_segment(service_id)
        payload: dict[str, Any] = {
            "f": "json",
            "rollbackOnFailure": rollback_on_failure,
        }
        if adds is not None:
            payload["adds"] = list(adds)
        if updates is not None:
            payload["updates"] = list(updates)
        if deletes is not None:
            if isinstance(deletes, str):
                payload["deletes"] = deletes
            else:
                payload["deletes"] = list(deletes)

        return await self._request_json(
            "POST",
            f"/rest/services/{service_segment}/FeatureServer/{layer_id}/applyEdits",
            json_body=payload,
        )

    async def apply_edits_result(
        self,
        service_id: str,
        layer_id: int,
        **kwargs: Any,
    ) -> ApplyEditsResult:
        """Submit applyEdits and return typed operation results."""
        return ApplyEditsResult.from_dict(await self.apply_edits(service_id, layer_id, **kwargs))

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
    ) -> bytes:
        """Request rendered map bytes from MapServer export."""
        service_segment = _encode_path_segment(service_id)
        if isinstance(bbox, str):
            bbox_value = bbox
        else:
            bbox_value = ",".join(str(value) for value in bbox)

        params: dict[str, Any] = {
            "f": "image",
            "bbox": bbox_value,
            "size": f"{size[0]},{size[1]}",
            "format": image_format,
            "transparent": _bool_text(transparent),
            "dpi": str(dpi),
        }
        if extra_params:
            params.update(extra_params)

        response = await self._request("GET", f"/rest/services/{service_segment}/MapServer/export", params=params)
        return response.content

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self._request(method, path, params=params, json_body=json_body, headers=headers)
        if not response.content:
            return {}

        try:
            payload = response.json()
        except ValueError:
            return {"raw": response.text}

        if isinstance(payload, Mapping):
            return dict(payload)
        return {"data": payload}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        # Build a full URL so httpx does not re-decode percent-encoded
        # path segments during base-URL resolution.
        base = self._client._base_url
        url = base.copy_with(raw_path=path.encode("ascii"))
        try:
            response = await self._client.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise _to_transport_error(exc) from exc
        if response.status_code >= 400:
            raise _to_http_error(response)
        return response
