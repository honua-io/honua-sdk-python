"""Synchronous HTTP client for Honua Server APIs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
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
from ._retry import RetryTransport
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
    from .geocoding import HonuaGeocodingClient
    from .ogc import HonuaOgcFeatures
    from .protocols import (
        GeoServicesFeatureServerClient,
        GeoServicesGeometryServerClient,
        GeoServicesImageServerClient,
        GeoServicesMapServerClient,
        ODataClient,
        OgcCoveragesClient,
        OgcMapsClient,
        OgcProcessesClient,
        OgcTilesClient,
        StacClient,
        WfsClient,
        WmsClient,
        WmtsClient,
    )


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


class HonuaClient:
    """Task-oriented client for common Honua workflows."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        api_key: str | None = None,
        bearer_token: str | None = None,
        auth_provider: AuthProvider | None = None,
        follow_redirects: bool = False,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
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

        def _request_hook(request: httpx.Request) -> None:
            _apply_sensitive_auth_headers(
                request,
                trusted_authority=trusted_authority,
                auth_headers=auth_headers,
                auth_provider=auth_provider,
            )

        effective_transport = transport
        if max_retries > 0:
            inner = effective_transport or httpx.HTTPTransport()
            effective_transport = RetryTransport(inner, max_retries=max_retries)

        self._client = httpx.Client(
            base_url=normalized_base_url,
            timeout=timeout,
            follow_redirects=follow_redirects,
            transport=effective_transport,
            event_hooks={"request": [_request_hook]},
        )

    def __enter__(self) -> "HonuaClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        """Release underlying resources if this instance owns the HTTP client."""
        if self._owns_client:
            self._client.close()

    def readiness(self) -> dict[str, Any]:
        """Get readiness status from `/healthz/ready`."""
        return self._request_json("GET", "/healthz/ready")

    def capabilities(self) -> DataPlaneCapabilities:
        """Discover server-advertised data-plane protocols and feature flags."""
        try:
            payload = self._request_json("GET", "/api/v1/capabilities")
        except HonuaHttpError as exc:
            if exc.status_code != 404:
                raise
            return DataPlaneCapabilities.from_discovery(
                readiness=self.readiness(),
                catalog=self.list_services(),
            )
        return DataPlaneCapabilities.from_dict(payload)

    def supports(self, capability: str) -> bool:
        """Return whether a data-plane protocol or feature is advertised."""
        return self.capabilities().supports(capability)

    def list_services(self, *, response_format: str = "json") -> dict[str, Any]:
        """List services from the GeoServices catalog endpoint."""
        return self._request_json(
            "GET",
            "/rest/services",
            params={"f": response_format},
        )

    def list_service_summaries(self, *, response_format: str = "json") -> list[ServiceSummary]:
        """List services as typed catalog summaries."""
        response = self.list_services(response_format=response_format)
        services = response.get("services")
        if not isinstance(services, list):
            return []
        return [ServiceSummary.from_dict(service) for service in services if isinstance(service, Mapping)]

    def ogc_features(self) -> "HonuaOgcFeatures":
        """Return an OGC API Features wrapper bound to this client."""
        from .ogc import HonuaOgcFeatures

        return HonuaOgcFeatures(self)

    def geocoder(self, locator: str = "World") -> "HonuaGeocodingClient":
        """Return a GeocodeServer wrapper that reuses this client's HTTP session."""
        from .geocoding import HonuaGeocodingClient

        return HonuaGeocodingClient(str(self._client._base_url), locator_name=locator, client=self._client)

    def feature_server(self, service_id: str) -> "GeoServicesFeatureServerClient":
        """Return a GeoServices FeatureServer wrapper for a service."""
        from .protocols import GeoServicesFeatureServerClient

        return GeoServicesFeatureServerClient(self, service_id)

    def map_server(self, service_id: str) -> "GeoServicesMapServerClient":
        """Return a GeoServices MapServer wrapper for a service."""
        from .protocols import GeoServicesMapServerClient

        return GeoServicesMapServerClient(self, service_id)

    def image_server(self, service_id: str | None = None) -> "GeoServicesImageServerClient":
        """Return a GeoServices ImageServer wrapper."""
        from .protocols import GeoServicesImageServerClient

        return GeoServicesImageServerClient(self, service_id)

    def geometry_server(self) -> "GeoServicesGeometryServerClient":
        """Return the GeoServices GeometryServer wrapper."""
        from .protocols import GeoServicesGeometryServerClient

        return GeoServicesGeometryServerClient(self)

    def ogc_maps(self) -> "OgcMapsClient":
        """Return an OGC API Maps wrapper."""
        from .protocols import OgcMapsClient

        return OgcMapsClient(self)

    def ogc_tiles(self) -> "OgcTilesClient":
        """Return an OGC API Tiles wrapper."""
        from .protocols import OgcTilesClient

        return OgcTilesClient(self)

    def ogc_coverages(self) -> "OgcCoveragesClient":
        """Return an OGC API Coverages wrapper."""
        from .protocols import OgcCoveragesClient

        return OgcCoveragesClient(self)

    def ogc_processes(self) -> "OgcProcessesClient":
        """Return an OGC API Processes wrapper."""
        from .protocols import OgcProcessesClient

        return OgcProcessesClient(self)

    def stac(self) -> "StacClient":
        """Return a STAC API wrapper."""
        from .protocols import StacClient

        return StacClient(self)

    def wfs(self) -> "WfsClient":
        """Return a WFS 2.0 wrapper."""
        from .protocols import WfsClient

        return WfsClient(self)

    def wms(self, service_id: str) -> "WmsClient":
        """Return a service-scoped WMS wrapper."""
        from .protocols import WmsClient

        return WmsClient(self, service_id)

    def wmts(self, service_id: str) -> "WmtsClient":
        """Return a service-scoped WMTS wrapper."""
        from .protocols import WmtsClient

        return WmtsClient(self, service_id)

    def odata(self) -> "ODataClient":
        """Return an OData v4 wrapper."""
        from .protocols import ODataClient

        return ODataClient(self)

    def query(
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
            features=tuple(self.iter_query(query)),
            protocol=normalized_protocol,
            source=query.source,
            query=query,
        )

    def iter_query(
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
    ) -> Iterator[QueryFeature]:
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
            for feature in self.feature_server(query.source).query_items(
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
            for feature in self.ogc_features().collection(query.source).iter_items(
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
            for feature in self.stac().iter_items(
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
        for feature in self.odata().iter_features(
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

    def query_features(
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

        return self._request_json(
            "GET",
            f"/rest/services/{service_segment}/FeatureServer/{layer_id}/query",
            params=params,
        )

    def query_feature_set(
        self,
        service_id: str,
        layer_id: int,
        **kwargs: Any,
    ) -> FeatureSet:
        """Query a FeatureServer layer and return a typed feature set."""
        return FeatureSet.from_dict(self.query_features(service_id, layer_id, **kwargs))

    def query_features_all(
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
            page = self.query_feature_set(
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

    def apply_edits(
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

        return self._request_json(
            "POST",
            f"/rest/services/{service_segment}/FeatureServer/{layer_id}/applyEdits",
            json_body=payload,
        )

    def apply_edits_result(
        self,
        service_id: str,
        layer_id: int,
        **kwargs: Any,
    ) -> ApplyEditsResult:
        """Submit applyEdits and return typed operation results."""
        return ApplyEditsResult.from_dict(self.apply_edits(service_id, layer_id, **kwargs))

    def export_map(
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

        response = self._request("GET", f"/rest/services/{service_segment}/MapServer/export", params=params)
        return response.content

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        response = self._request(method, path, params=params, json_body=json_body, headers=headers)
        if not response.content:
            return {}

        try:
            payload = response.json()
        except ValueError:
            return {"raw": response.text}

        if isinstance(payload, Mapping):
            return dict(payload)
        return {"data": payload}

    def _request(
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
            response = self._client.request(
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
