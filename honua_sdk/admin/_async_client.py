"""Async Admin API client for Honua Server."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from ..errors import HonuaHttpError
from .._async_retry import AsyncRetryTransport
from .._http import (
    _apply_sensitive_auth_headers,
    _build_sensitive_auth_headers,
    _encode_path_segment,
    _extract_trusted_authority,
    _normalize_base_url,
    _to_http_error,
    _to_transport_error,
)
from ._models import (
    AdminCompatibilityBaseline,
    AdminCompatibilityCheckResult,
    AdminCompatibilityFeatureFlags,
    AdminCapabilitiesResponse,
    AdminVersionResponse,
    ConnectionTestResult,
    CreateSecureConnectionRequest,
    EncryptionValidationResult,
    KeyRotationResult,
    LayerStyleResponse,
    LayerStyleUpdateRequest,
    ManifestApplyRequest,
    ManifestApplyResult,
    MetadataManifest,
    MetadataResource,
    PublishLayerRequest,
    PublishedLayerSummary,
    SecureConnectionDetail,
    SecureConnectionSummary,
    ServiceSettingsResponse,
    ServiceSummary,
    TableDiscoveryResponse,
    UpdateSecureConnectionRequest,
    _parse_version_components,
    get_release_channel_rank,
)


class AsyncHonuaAdminClient:
    """Asynchronous client for the Honua Admin API."""

    MINIMUM_SUPPORTED_SERVER_BASELINE = AdminCompatibilityBaseline()

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        api_key: str | None = None,
        bearer_token: str | None = None,
        follow_redirects: bool = False,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 3,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("Provide either `client` or `transport`, not both.")

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

    # -- context manager ----------------------------------------------------

    async def __aenter__(self) -> AsyncHonuaAdminClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Release underlying resources if this instance owns the HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    # -- internal helpers ---------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
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

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Issue a request and unwrap the ApiResponse envelope.

        The Honua admin API wraps every successful response in::

            {"success": true, "data": <payload>, "message": "...", "timestamp": "..."}

        This method returns the inner ``data`` value.
        """
        response = await self._request(method, path, params=params, json_body=json_body, headers=headers)
        if not response.content:
            return None

        try:
            payload = response.json()
        except ValueError:
            return response.text

        if isinstance(payload, Mapping) and "data" in payload:
            return payload["data"]
        return payload

    # ======================================================================
    # Services
    # ======================================================================

    async def list_services(self) -> list[ServiceSummary]:
        """GET /api/v1/admin/services/"""
        data = await self._request_json("GET", "/api/v1/admin/services/")
        if not isinstance(data, list):
            return []
        return [ServiceSummary.from_dict(s) for s in data]

    async def get_service_settings(self, name: str) -> ServiceSettingsResponse:
        """GET /api/v1/admin/services/{name}/settings"""
        service_name = _encode_path_segment(name)
        data = await self._request_json("GET", f"/api/v1/admin/services/{service_name}/settings")
        return ServiceSettingsResponse.from_dict(data)

    async def update_protocols(self, name: str, protocols: list[str]) -> ServiceSettingsResponse:
        """PUT /api/v1/admin/services/{name}/protocols"""
        service_name = _encode_path_segment(name)
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/services/{service_name}/protocols",
            json_body=protocols,
        )
        return ServiceSettingsResponse.from_dict(data)

    async def update_mapserver_settings(self, name: str, **kwargs: Any) -> ServiceSettingsResponse:
        """PUT /api/v1/admin/services/{name}/mapserver"""
        from ._models import _to_camel

        service_name = _encode_path_segment(name)
        body = {_to_camel(k): v for k, v in kwargs.items()}
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/services/{service_name}/mapserver",
            json_body=body,
        )
        return ServiceSettingsResponse.from_dict(data)

    # ======================================================================
    # Metadata Resources
    # ======================================================================

    async def list_metadata_resources(
        self,
        kind: str | None = None,
        namespace: str | None = None,
    ) -> list[MetadataResource]:
        """GET /api/v1/admin/metadata/resources"""
        params: dict[str, str] = {}
        if kind is not None:
            params["kind"] = kind
        if namespace is not None:
            params["namespace"] = namespace
        data = await self._request_json(
            "GET",
            "/api/v1/admin/metadata/resources",
            params=params or None,
        )
        if not isinstance(data, list):
            return []
        return [MetadataResource.from_dict(r) for r in data]

    async def get_metadata_resource(
        self,
        kind: str,
        ns: str,
        name: str,
    ) -> tuple[MetadataResource, str | None]:
        """GET /api/v1/admin/metadata/resources/{kind}/{ns}/{name}

        Returns ``(resource, etag)`` where *etag* may be ``None`` if the
        server did not include an ``ETag`` header.
        """
        kind_segment = _encode_path_segment(kind)
        namespace_segment = _encode_path_segment(ns)
        name_segment = _encode_path_segment(name)
        response = await self._request(
            "GET",
            f"/api/v1/admin/metadata/resources/{kind_segment}/{namespace_segment}/{name_segment}",
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise HonuaHttpError(
                response.status_code,
                "Failed to decode metadata resource JSON response",
                body=response.text,
            ) from exc
        inner = payload.get("data", payload) if isinstance(payload, Mapping) else payload
        resource = MetadataResource.from_dict(inner)
        etag = response.headers.get("ETag") or response.headers.get("etag")
        return resource, etag

    async def create_metadata_resource(self, resource: MetadataResource) -> MetadataResource:
        """POST /api/v1/admin/metadata/resources"""
        data = await self._request_json(
            "POST",
            "/api/v1/admin/metadata/resources",
            json_body=resource.to_dict(),
        )
        return MetadataResource.from_dict(data)

    async def update_metadata_resource(
        self,
        kind: str,
        ns: str,
        name: str,
        resource: MetadataResource,
        *,
        if_match: str | None = None,
    ) -> MetadataResource:
        """PUT /api/v1/admin/metadata/resources/{kind}/{ns}/{name}"""
        kind_segment = _encode_path_segment(kind)
        namespace_segment = _encode_path_segment(ns)
        name_segment = _encode_path_segment(name)
        hdrs: dict[str, str] = {}
        if if_match is not None:
            hdrs["If-Match"] = if_match
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/metadata/resources/{kind_segment}/{namespace_segment}/{name_segment}",
            json_body=resource.to_dict(),
            headers=hdrs or None,
        )
        return MetadataResource.from_dict(data)

    async def delete_metadata_resource(
        self,
        kind: str,
        ns: str,
        name: str,
        *,
        if_match: str | None = None,
    ) -> None:
        """DELETE /api/v1/admin/metadata/resources/{kind}/{ns}/{name}"""
        kind_segment = _encode_path_segment(kind)
        namespace_segment = _encode_path_segment(ns)
        name_segment = _encode_path_segment(name)
        hdrs: dict[str, str] = {}
        if if_match is not None:
            hdrs["If-Match"] = if_match
        await self._request(
            "DELETE",
            f"/api/v1/admin/metadata/resources/{kind_segment}/{namespace_segment}/{name_segment}",
            headers=hdrs or None,
        )

    # ======================================================================
    # Manifests
    # ======================================================================

    async def get_version(self) -> AdminVersionResponse:
        """GET /api/v1/admin/version"""
        data = await self._request_json("GET", "/api/v1/admin/version")
        return AdminVersionResponse.from_dict(data)

    async def get_capabilities(self) -> AdminCapabilitiesResponse:
        """GET /api/v1/admin/capabilities"""
        data = await self._request_json("GET", "/api/v1/admin/capabilities")
        return AdminCapabilitiesResponse.from_dict(data)

    async def get_capability_flags(self) -> AdminCompatibilityFeatureFlags:
        """Return coarse feature flags from the admin compatibility contract."""
        compatibility = (await self.get_capabilities()).compatibility
        if compatibility is None:
            return AdminCompatibilityFeatureFlags(
                metadata_resources=False,
                manifest_export=False,
                manifest_apply=False,
                manifest_dry_run=False,
                manifest_prune=False,
            )
        return compatibility.features

    async def check_compatibility(self) -> AdminCompatibilityCheckResult:
        """Evaluate whether the connected server satisfies the admin SDK baseline."""
        capabilities = await self.get_capabilities()
        compatibility = capabilities.compatibility
        baseline = self.MINIMUM_SUPPORTED_SERVER_BASELINE
        reasons: list[str] = []
        warnings: list[str] = []

        if compatibility is None:
            reasons.append("Server did not return a compatibility contract.")
            return AdminCompatibilityCheckResult(
                supported=False,
                baseline=baseline,
                compatibility=None,
                reasons=reasons,
                warnings=warnings,
            )

        actual_version = _parse_version_components(compatibility.server_version)
        minimum_version = _parse_version_components(baseline.minimum_server_version)
        if actual_version is None:
            reasons.append(
                f"Server version {compatibility.server_version!r} could not be parsed."
            )
        elif minimum_version is None:
            reasons.append(
                "SDK minimum supported server version baseline could not be parsed."
            )
        elif actual_version < minimum_version:
            reasons.append(
                "Server version "
                f"{compatibility.server_version!r} is below required "
                f"{baseline.minimum_server_version!r}."
            )

        if compatibility.control_plane_api.major != baseline.control_plane_api_major:
            reasons.append(
                "Server control-plane API major "
                f"{compatibility.control_plane_api.major} does not match required "
                f"{baseline.control_plane_api_major}."
            )

        if compatibility.control_plane_api.base_path != baseline.base_path:
            reasons.append(
                "Server control-plane base path "
                f"{compatibility.control_plane_api.base_path!r} does not match "
                f"required {baseline.base_path!r}."
            )

        if compatibility.control_plane_api.deprecated:
            warnings.append("Server control-plane API major is marked deprecated.")

        actual_rank = get_release_channel_rank(compatibility.release_channel)
        minimum_rank = get_release_channel_rank(baseline.minimum_release_channel)
        if actual_rank is None:
            reasons.append(
                f"Server release channel {compatibility.release_channel!r} is unknown."
            )
        elif minimum_rank is None or actual_rank < minimum_rank:
            reasons.append(
                "Server release channel "
                f"{compatibility.release_channel!r} is below required "
                f"{baseline.minimum_release_channel!r}."
            )

        return AdminCompatibilityCheckResult(
            supported=not reasons,
            baseline=baseline,
            compatibility=compatibility,
            reasons=reasons,
            warnings=warnings,
        )

    async def get_manifest(self, namespace: str | None = None) -> MetadataManifest:
        """GET /api/v1/admin/manifest"""
        params: dict[str, str] | None = None
        if namespace is not None:
            params = {"namespace": namespace}
        data = await self._request_json("GET", "/api/v1/admin/manifest", params=params)
        return MetadataManifest.from_dict(data)

    async def apply_manifest(self, request: ManifestApplyRequest) -> ManifestApplyResult:
        """POST /api/v1/admin/manifest/apply"""
        data = await self._request_json(
            "POST",
            "/api/v1/admin/manifest/apply",
            json_body=request.to_dict(),
        )
        return ManifestApplyResult.from_dict(data)

    # ======================================================================
    # Connections
    # ======================================================================

    async def list_connections(self) -> list[SecureConnectionSummary]:
        """GET /api/v1/admin/connections"""
        data = await self._request_json("GET", "/api/v1/admin/connections")
        if not isinstance(data, list):
            return []
        return [SecureConnectionSummary.from_dict(c) for c in data]

    async def get_connection(self, id: str) -> SecureConnectionDetail:
        """GET /api/v1/admin/connections/{id}"""
        connection_id = _encode_path_segment(id)
        data = await self._request_json("GET", f"/api/v1/admin/connections/{connection_id}")
        return SecureConnectionDetail.from_dict(data)

    async def create_connection(self, request: CreateSecureConnectionRequest) -> SecureConnectionSummary:
        """POST /api/v1/admin/connections"""
        data = await self._request_json(
            "POST",
            "/api/v1/admin/connections",
            json_body=request.to_dict(),
        )
        return SecureConnectionSummary.from_dict(data)

    async def test_draft_connection(self, request: CreateSecureConnectionRequest) -> ConnectionTestResult:
        """POST /api/v1/admin/connections/test"""
        data = await self._request_json(
            "POST",
            "/api/v1/admin/connections/test",
            json_body=request.to_dict(),
        )
        return ConnectionTestResult.from_dict(data)

    async def update_connection(
        self,
        id: str,
        request: UpdateSecureConnectionRequest,
    ) -> SecureConnectionSummary:
        """PUT /api/v1/admin/connections/{id}"""
        connection_id = _encode_path_segment(id)
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/connections/{connection_id}",
            json_body=request.to_dict(),
        )
        return SecureConnectionSummary.from_dict(data)

    async def test_connection(self, id: str) -> ConnectionTestResult:
        """POST /api/v1/admin/connections/{id}/test"""
        connection_id = _encode_path_segment(id)
        data = await self._request_json(
            "POST",
            f"/api/v1/admin/connections/{connection_id}/test",
        )
        return ConnectionTestResult.from_dict(data)

    async def delete_connection(self, id: str) -> None:
        """DELETE /api/v1/admin/connections/{id}"""
        connection_id = _encode_path_segment(id)
        await self._request("DELETE", f"/api/v1/admin/connections/{connection_id}")

    async def validate_encryption(self) -> EncryptionValidationResult:
        """POST /api/v1/admin/connections/encryption/validate"""
        data = await self._request_json(
            "POST",
            "/api/v1/admin/connections/encryption/validate",
        )
        return EncryptionValidationResult.from_dict(data)

    async def rotate_encryption_key(self) -> KeyRotationResult:
        """POST /api/v1/admin/connections/encryption/rotate-key"""
        data = await self._request_json(
            "POST",
            "/api/v1/admin/connections/encryption/rotate-key",
        )
        return KeyRotationResult.from_dict(data)

    # ======================================================================
    # Layers
    # ======================================================================

    async def list_layers(
        self,
        conn_id: str,
        service_name: str | None = None,
    ) -> list[PublishedLayerSummary]:
        """GET /api/v1/admin/connections/{conn_id}/layers"""
        connection_id = _encode_path_segment(conn_id)
        params: dict[str, str] | None = None
        if service_name is not None:
            params = {"serviceName": service_name}
        data = await self._request_json(
            "GET",
            f"/api/v1/admin/connections/{connection_id}/layers",
            params=params,
        )
        if not isinstance(data, list):
            return []
        return [PublishedLayerSummary.from_dict(l) for l in data]

    async def publish_layer(
        self,
        conn_id: str,
        request: PublishLayerRequest,
    ) -> PublishedLayerSummary:
        """POST /api/v1/admin/connections/{conn_id}/layers"""
        connection_id = _encode_path_segment(conn_id)
        data = await self._request_json(
            "POST",
            f"/api/v1/admin/connections/{connection_id}/layers",
            json_body=request.to_dict(),
        )
        return PublishedLayerSummary.from_dict(data)

    async def set_layer_enabled(
        self,
        conn_id: str,
        layer_id: int,
        enabled: bool,
        service_name: str | None = None,
    ) -> PublishedLayerSummary:
        """PUT /api/v1/admin/connections/{conn_id}/layers/{layer_id}/enabled"""
        connection_id = _encode_path_segment(conn_id)
        params: dict[str, str] | None = None
        if service_name is not None:
            params = {"serviceName": service_name}
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/connections/{connection_id}/layers/{layer_id}/enabled",
            json_body={"enabled": enabled},
            params=params,
        )
        return PublishedLayerSummary.from_dict(data)

    async def set_service_layers_enabled(
        self,
        conn_id: str,
        enabled: bool,
        service_name: str | None = None,
    ) -> list[PublishedLayerSummary]:
        """PUT /api/v1/admin/connections/{conn_id}/layers/enabled"""
        connection_id = _encode_path_segment(conn_id)
        params: dict[str, str] | None = None
        if service_name is not None:
            params = {"serviceName": service_name}
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/connections/{connection_id}/layers/enabled",
            json_body={"enabled": enabled},
            params=params,
        )
        if not isinstance(data, list):
            return []
        return [PublishedLayerSummary.from_dict(l) for l in data]

    # ======================================================================
    # Discovery
    # ======================================================================

    async def discover_tables(self, conn_id: str) -> TableDiscoveryResponse:
        """GET /api/v1/admin/connections/{conn_id}/tables"""
        connection_id = _encode_path_segment(conn_id)
        data = await self._request_json(
            "GET",
            f"/api/v1/admin/connections/{connection_id}/tables",
        )
        return TableDiscoveryResponse.from_dict(data)

    # ======================================================================
    # Styles
    # ======================================================================

    async def get_layer_style(self, layer_id: int) -> LayerStyleResponse:
        """GET /api/v1/admin/metadata/layers/{layer_id}/style"""
        data = await self._request_json(
            "GET",
            f"/api/v1/admin/metadata/layers/{layer_id}/style",
        )
        return LayerStyleResponse.from_dict(data)

    async def update_layer_style(
        self,
        layer_id: int,
        request: LayerStyleUpdateRequest,
    ) -> LayerStyleResponse:
        """PUT /api/v1/admin/metadata/layers/{layer_id}/style"""
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/metadata/layers/{layer_id}/style",
            json_body=request.to_dict(),
        )
        return LayerStyleResponse.from_dict(data)

    # ======================================================================
    # Config
    # ======================================================================

    async def get_config(self) -> dict[str, Any]:
        """GET /api/v1/admin/config"""
        data = await self._request_json("GET", "/api/v1/admin/config")
        if isinstance(data, dict):
            return data
        return {}
