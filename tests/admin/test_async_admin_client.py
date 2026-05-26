"""Tests for the async admin client, mirroring sync coverage patterns."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from honua_admin import (
    AdminCompatibilityFeatureFlags,
    AsyncHonuaAdminClient,
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
    PublishedLayerSummary,
    PublishLayerRequest,
    SecureConnectionDetail,
    SecureConnectionSummary,
    ServiceSettingsResponse,
    ServiceSummary,
    TableDiscoveryResponse,
    UpdateSecureConnectionRequest,
)
from honua_sdk import CallableAuthProvider, HonuaHttpError
from honua_sdk.errors import HonuaTransportError

from .conftest import make_api_response


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


pytestmark = pytest.mark.anyio


def _async_admin_client(handler: Any) -> AsyncHonuaAdminClient:
    transport = httpx.MockTransport(handler)
    return AsyncHonuaAdminClient("http://test.honua.io", transport=transport)


# ---------------------------------------------------------------------------
# list_services
# ---------------------------------------------------------------------------


async def test_async_list_services_returns_typed_summaries() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json=make_api_response(
                [
                    {
                        "serviceName": "default",
                        "description": "Default service",
                        "layerCount": 5,
                        "enabledProtocols": ["FeatureServer"],
                    },
                    {
                        "serviceName": "testing",
                        "description": None,
                        "layerCount": 0,
                        "enabledProtocols": [],
                    },
                ]
            ),
        )

    async with _async_admin_client(handler) as client:
        result = await client.list_services()

    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/admin/services/"
    assert len(result) == 2
    assert isinstance(result[0], ServiceSummary)
    assert result[0].service_name == "default"
    assert result[0].layer_count == 5
    assert result[1].service_name == "testing"


async def test_async_list_services_empty_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response(None))

    async with _async_admin_client(handler) as client:
        result = await client.list_services()

    assert result == []


async def test_async_list_services_http_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": 404, "message": "Not Found"}})

    async with _async_admin_client(handler) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            await client.list_services()

    assert exc_info.value.status_code == 404


async def test_async_list_services_transport_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with _async_admin_client(handler) as client:
        with pytest.raises(HonuaTransportError):
            await client.list_services()


# ---------------------------------------------------------------------------
# get_capability_flags
# ---------------------------------------------------------------------------


async def test_async_get_capability_flags_with_compat_block() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "version": "1.2.3",
                    "buildSha": "abc",
                    "buildTime": "2026-03-01T00:00:00Z",
                    "compatibility": {
                        "schemaVersion": 1,
                        "minAdminApiVersion": "1.0.0",
                        "features": {
                            "metadataResources": True,
                            "manifestExport": True,
                            "manifestApply": True,
                            "manifestDryRun": False,
                            "manifestPrune": False,
                        },
                    },
                }
            ),
        )

    async with _async_admin_client(handler) as client:
        flags = await client.get_capability_flags()

    assert isinstance(flags, AdminCompatibilityFeatureFlags)
    assert flags.metadata_resources is True
    assert flags.manifest_apply is True
    assert flags.manifest_dry_run is False


async def test_async_get_capability_flags_without_compat_block() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "version": "0.9.0",
                    "buildSha": "older",
                    "buildTime": "2025-01-01T00:00:00Z",
                    # No `compatibility` key -> server too old.
                }
            ),
        )

    async with _async_admin_client(handler) as client:
        flags = await client.get_capability_flags()

    assert flags.metadata_resources is False
    assert flags.manifest_apply is False
    assert flags.manifest_dry_run is False
    assert flags.manifest_prune is False


# ---------------------------------------------------------------------------
# close() semantics
# ---------------------------------------------------------------------------


async def test_async_close_releases_owned_client() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response([]))

    transport = httpx.MockTransport(handler)
    client = AsyncHonuaAdminClient("http://test.honua.io", transport=transport)
    await client.list_services()
    await client.close()
    # Calling close twice is safe.
    await client.close()


async def test_async_close_is_noop_for_external_client() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    external = httpx.AsyncClient(base_url="http://test.honua.io/", transport=transport)
    client = AsyncHonuaAdminClient("http://test.honua.io", client=external)
    try:
        await client.close()
        # External client must still be usable.
        response = await external.get("/ping")
        assert response.status_code == 200
    finally:
        await external.aclose()


# ---------------------------------------------------------------------------
# with_options
# ---------------------------------------------------------------------------


async def test_async_with_options_overrides_timeout_and_retries() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response([]))

    transport = httpx.MockTransport(handler)
    client = AsyncHonuaAdminClient("http://test.honua.io", transport=transport, timeout=1.0)
    try:
        # ``timeout=2.0`` >= parent's 1.0 -> the clone reuses the parent
        # transport / connection pool.
        clone = client.with_options(timeout=2.0, max_retries=0)
        assert clone is not client
        assert clone._client is client._client
        assert clone._options_timeout == 2.0
        assert clone._options_max_retries == 0
        # The clone must remain usable via the shared transport.
        result = await clone.list_services()
        assert result == []
        # Closing the clone is a no-op on the shared transport.
        await clone.close()
    finally:
        await client.close()


async def test_async_with_options_overrides_base_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response([]))

    transport = httpx.MockTransport(handler)
    client = AsyncHonuaAdminClient("http://test.honua.io", transport=transport)
    try:
        clone = client.with_options(base_url="http://other.honua.io")
        assert clone._init_base_url == "http://other.honua.io"
        assert str(clone._base_url) == "http://other.honua.io/"
        # Supplying ``base_url`` forces an independent client so the new
        # authority is honored end-to-end (including the bound
        # ``httpx.AsyncClient.base_url``). The clone OWNS its own client.
        assert clone._client is not client._client
        assert clone._owns_client is True
        await clone.close()
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Init paths
# ---------------------------------------------------------------------------


async def test_async_init_rejects_client_and_transport_together() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    external = httpx.AsyncClient(base_url="http://test.honua.io", transport=transport)
    try:
        with pytest.raises(ValueError, match="either `client` or `transport`"):
            AsyncHonuaAdminClient(
                "http://test.honua.io",
                client=external,
                transport=transport,
            )
    finally:
        await external.aclose()


async def test_async_init_rejects_sdk_auth_options_with_external_client() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    external = httpx.AsyncClient(base_url="http://test.honua.io", transport=transport)
    try:
        with pytest.raises(ValueError, match="supplied `client`"):
            AsyncHonuaAdminClient(
                "http://test.honua.io",
                client=external,
                api_key="nope",
            )
    finally:
        await external.aclose()


async def test_async_init_api_key_sets_x_api_key_header() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["x_api_key"] = request.headers.get("x-api-key", "")
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=make_api_response([]))

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaAdminClient(
        "http://test.honua.io",
        api_key="admin-key",
        transport=transport,
    ) as client:
        await client.list_services()

    assert seen["x_api_key"] == "admin-key"
    assert seen["authorization"] == ""


async def test_async_init_bearer_token_sets_authorization_header() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=make_api_response([]))

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaAdminClient(
        "http://test.honua.io",
        bearer_token="admin-bearer",
        transport=transport,
    ) as client:
        await client.list_services()

    assert seen["authorization"] == "Bearer admin-bearer"


async def test_async_init_auth_provider_is_invoked_per_request() -> None:
    calls = {"count": 0}

    def provider_fn() -> dict[str, str]:
        calls["count"] += 1
        return {"Authorization": f"Bearer call-{calls['count']}"}

    auth = CallableAuthProvider(provider_fn)
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json=make_api_response([]))

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaAdminClient(
        "http://test.honua.io",
        auth_provider=auth,
        transport=transport,
    ) as client:
        await client.list_services()
        await client.list_services()

    assert seen == ["Bearer call-1", "Bearer call-2"]


# ---------------------------------------------------------------------------
# get_version / get_capabilities passthrough
# ---------------------------------------------------------------------------


async def test_async_get_version_returns_typed_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "version": "1.5.0",
                    "buildSha": "deadbeef",
                    "buildTime": "2026-04-01T00:00:00Z",
                    "metadataApiVersion": "1.0",
                    "serverTime": "2026-04-01T00:00:00Z",
                }
            ),
        )

    async with _async_admin_client(handler) as client:
        version = await client.get_version()

    assert version.version == "1.5.0"


async def test_async_check_compatibility_runs_through() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "version": "1.2.3",
                    "buildSha": "abc",
                    "buildTime": "2026-03-01T00:00:00Z",
                    "compatibility": {
                        "schemaVersion": 1,
                        "minAdminApiVersion": "1.0.0",
                        "features": {
                            "metadataResources": True,
                            "manifestExport": True,
                            "manifestApply": True,
                            "manifestDryRun": True,
                            "manifestPrune": True,
                        },
                    },
                }
            ),
        )

    async with _async_admin_client(handler) as client:
        result = await client.check_compatibility()

    # Should produce a typed result regardless of supported/unsupported gaps.
    assert result is not None


# ---------------------------------------------------------------------------
# Service settings + protocols
# ---------------------------------------------------------------------------


async def test_async_get_service_settings_returns_typed_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "serviceName": "default",
                    "enabledProtocols": ["FeatureServer"],
                    "availableProtocols": ["FeatureServer", "MapServer"],
                    "accessPolicy": None,
                    "timeInfo": None,
                    "mapServer": None,
                }
            ),
        )

    async with _async_admin_client(handler) as client:
        result = await client.get_service_settings("default")

    assert isinstance(result, ServiceSettingsResponse)
    assert result.service_name == "default"


async def test_async_update_protocols_sends_list_body() -> None:
    import json

    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "serviceName": "default",
                    "enabledProtocols": ["FeatureServer", "OGC"],
                    "availableProtocols": ["FeatureServer", "OGC"],
                    "accessPolicy": None,
                    "timeInfo": None,
                    "mapServer": None,
                }
            ),
        )

    async with _async_admin_client(handler) as client:
        result = await client.update_protocols("default", ["FeatureServer", "OGC"])

    assert seen["method"] == "PUT"
    assert seen["body"] == ["FeatureServer", "OGC"]
    assert isinstance(result, ServiceSettingsResponse)


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


_CONN_SUMMARY: dict[str, Any] = {
    "connectionId": "conn-001",
    "name": "prod-db",
    "description": "Production database",
    "host": "db.example.com",
    "port": 5432,
    "databaseName": "honua",
    "username": "admin",
    "sslRequired": True,
    "sslMode": "require",
    "storageType": "PostgreSQL",
    "isActive": True,
    "healthStatus": "healthy",
    "lastHealthCheck": "2026-03-01T00:00:00Z",
    "createdAt": "2026-01-15T00:00:00Z",
    "createdBy": "system",
}


async def test_async_list_connections_returns_typed_summaries() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response([_CONN_SUMMARY]))

    async with _async_admin_client(handler) as client:
        result = await client.list_connections()

    assert len(result) == 1
    assert isinstance(result[0], SecureConnectionSummary)
    assert result[0].connection_id == "conn-001"


async def test_async_list_connections_empty_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response(None))

    async with _async_admin_client(handler) as client:
        assert await client.list_connections() == []


async def test_async_get_connection_returns_detail() -> None:
    detail = {
        **_CONN_SUMMARY,
        "credentialReference": "vault://secret/db",
        "encryptionVersion": 2,
        "updatedAt": "2026-02-20T00:00:00Z",
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/admin/connections/conn-001"
        return httpx.Response(200, json=make_api_response(detail))

    async with _async_admin_client(handler) as client:
        result = await client.get_connection("conn-001")

    assert isinstance(result, SecureConnectionDetail)
    assert result.credential_reference == "vault://secret/db"


async def test_async_create_connection_sends_body() -> None:
    import json

    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(201, json=make_api_response(_CONN_SUMMARY))

    req = CreateSecureConnectionRequest(
        name="prod-db",
        host="db.example.com",
        port=5432,
        database_name="honua",
        username="admin",
        password="secret",
        ssl_required=True,
    )
    async with _async_admin_client(handler) as client:
        result = await client.create_connection(req)

    assert seen["body"]["name"] == "prod-db"
    assert seen["body"]["password"] == "secret"
    assert isinstance(result, SecureConnectionSummary)


async def test_async_test_draft_connection() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/admin/connections/test"
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "connectionId": None,
                    "connectionName": "draft",
                    "isHealthy": True,
                    "testedAt": "2026-03-01T00:00:00Z",
                    "message": "ok",
                }
            ),
        )

    req = CreateSecureConnectionRequest(
        name="draft",
        host="db.example.com",
        port=5432,
        database_name="honua",
        username="admin",
        password="secret",
    )
    async with _async_admin_client(handler) as client:
        result = await client.test_draft_connection(req)

    assert isinstance(result, ConnectionTestResult)
    assert result.is_healthy is True


async def test_async_update_connection() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/admin/connections/conn-001"
        return httpx.Response(200, json=make_api_response(_CONN_SUMMARY))

    req = UpdateSecureConnectionRequest(description="updated", port=5433)
    async with _async_admin_client(handler) as client:
        result = await client.update_connection("conn-001", req)
    assert isinstance(result, SecureConnectionSummary)


async def test_async_test_connection_by_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/admin/connections/conn-001/test"
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "connectionId": "conn-001",
                    "connectionName": "prod-db",
                    "isHealthy": True,
                    "testedAt": "2026-03-01T00:00:00Z",
                    "message": "OK",
                }
            ),
        )

    async with _async_admin_client(handler) as client:
        result = await client.test_connection("conn-001")
    assert result.connection_id == "conn-001"


async def test_async_delete_connection() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(204)

    async with _async_admin_client(handler) as client:
        await client.delete_connection("conn-001")

    assert seen["method"] == "DELETE"
    assert seen["path"] == "/api/v1/admin/connections/conn-001"


async def test_async_validate_encryption() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "isValid": True,
                    "currentKeyVersion": 3,
                    "validatedAt": "2026-03-01T00:00:00Z",
                    "message": "All keys valid",
                }
            ),
        )

    async with _async_admin_client(handler) as client:
        result = await client.validate_encryption()

    assert isinstance(result, EncryptionValidationResult)
    assert result.is_valid is True
    assert result.current_key_version == 3


async def test_async_rotate_encryption_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "previousKeyVersion": 3,
                    "newKeyVersion": 4,
                    "rotatedAt": "2026-03-01T00:00:00Z",
                    "message": "Key rotated successfully",
                }
            ),
        )

    async with _async_admin_client(handler) as client:
        result = await client.rotate_encryption_key()

    assert isinstance(result, KeyRotationResult)
    assert result.new_key_version == 4


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


_LAYER_SUMMARY: dict[str, Any] = {
    "layerId": 1,
    "layerName": "parcels",
    "schema": "public",
    "table": "parcels",
    "description": "Parcel boundaries",
    "geometryType": "Polygon",
    "srid": 4326,
    "primaryKey": "gid",
    "fieldCount": 12,
    "enabled": True,
    "serviceName": "default",
}


async def test_async_list_layers_with_filter() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json=make_api_response([_LAYER_SUMMARY]))

    async with _async_admin_client(handler) as client:
        result = await client.list_layers("conn-001", service_name="default")

    assert seen["path"] == "/api/v1/admin/connections/conn-001/layers"
    assert seen["query"]["serviceName"] == "default"
    assert isinstance(result[0], PublishedLayerSummary)


async def test_async_list_layers_empty_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response(None))

    async with _async_admin_client(handler) as client:
        assert await client.list_layers("conn-001") == []


async def test_async_publish_layer() -> None:
    import json

    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(201, json=make_api_response(_LAYER_SUMMARY))

    req = PublishLayerRequest(schema="public", table="parcels", layer_name="parcels")
    async with _async_admin_client(handler) as client:
        result = await client.publish_layer("conn-001", req)

    assert seen["body"]["table"] == "parcels"
    assert isinstance(result, PublishedLayerSummary)


async def test_async_set_layer_enabled() -> None:
    import json

    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        seen["path"] = request.url.path
        return httpx.Response(200, json=make_api_response(_LAYER_SUMMARY))

    async with _async_admin_client(handler) as client:
        result = await client.set_layer_enabled("conn-001", 1, False)

    assert seen["body"] == {"enabled": False}
    assert "/layers/1/enabled" in seen["path"]
    assert isinstance(result, PublishedLayerSummary)


async def test_async_set_service_layers_enabled() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response([_LAYER_SUMMARY]))

    async with _async_admin_client(handler) as client:
        result = await client.set_service_layers_enabled(
            "conn-001", True, service_name="default"
        )

    assert len(result) == 1


async def test_async_set_service_layers_enabled_empty_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response(None))

    async with _async_admin_client(handler) as client:
        result = await client.set_service_layers_enabled("conn-001", False)

    assert result == []


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


async def test_async_discover_tables() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "tables": [
                        {
                            "schema": "public",
                            "table": "parcels",
                            "geometryColumn": "geom",
                            "geometryType": "Polygon",
                            "srid": 4326,
                            "estimatedRows": 100,
                            "columns": [],
                        }
                    ],
                }
            ),
        )

    async with _async_admin_client(handler) as client:
        result = await client.discover_tables("conn-001")

    assert isinstance(result, TableDiscoveryResponse)
    assert len(result.tables) == 1


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------


async def test_async_get_layer_style() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/admin/metadata/layers/42/style"
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "layerId": 42,
                    "mapLibreStyle": {"version": 8},
                    "drawingInfo": None,
                }
            ),
        )

    async with _async_admin_client(handler) as client:
        result = await client.get_layer_style(42)

    assert isinstance(result, LayerStyleResponse)


async def test_async_update_layer_style() -> None:
    import json

    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "layerId": 42,
                    "mapLibreStyle": {"version": 8},
                    "drawingInfo": None,
                }
            ),
        )

    req = LayerStyleUpdateRequest(map_libre_style={"version": 8})
    async with _async_admin_client(handler) as client:
        result = await client.update_layer_style(42, req)

    assert seen["body"]["mapLibreStyle"] == {"version": 8}
    assert isinstance(result, LayerStyleResponse)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


async def test_async_get_config_returns_dict() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response({"key": "value"}))

    async with _async_admin_client(handler) as client:
        result = await client.get_config()

    assert result == {"key": "value"}


async def test_async_get_config_returns_empty_dict_for_non_mapping() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response([1, 2, 3]))

    async with _async_admin_client(handler) as client:
        result = await client.get_config()

    assert result == {}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


async def test_async_get_manifest_with_namespace_filter() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "apiVersion": "v1",
                    "generatedAt": "2026-03-01T00:00:00Z",
                    "resources": [],
                    "driftedResources": [],
                    "manifestHash": "sha256:abc",
                }
            ),
        )

    async with _async_admin_client(handler) as client:
        result = await client.get_manifest(namespace="public")

    assert seen["query"]["namespace"] == "public"
    assert isinstance(result, MetadataManifest)


async def test_async_apply_manifest_includes_idempotency_key() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["idempotency"] = request.headers.get("idempotency-key", "")
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "dryRun": False,
                    "summary": {
                        "created": 1,
                        "updated": 0,
                        "deleted": 0,
                        "skipped": 0,
                    },
                    "entries": [],
                }
            ),
        )

    req = ManifestApplyRequest(resources=[], dry_run=False, prune=False)
    async with _async_admin_client(handler) as client:
        result = await client.apply_manifest(req, idempotency_key="user-supplied-key")

    assert seen["idempotency"] == "user-supplied-key"
    assert isinstance(result, ManifestApplyResult)


# ---------------------------------------------------------------------------
# Metadata resources
# ---------------------------------------------------------------------------


async def test_async_list_metadata_resources_with_filters() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json=make_api_response([]))

    async with _async_admin_client(handler) as client:
        result = await client.list_metadata_resources(kind="Service", namespace="public")

    assert seen["query"]["kind"] == "Service"
    assert seen["query"]["namespace"] == "public"
    assert result == []


async def test_async_list_metadata_resources_non_list_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response(None))

    async with _async_admin_client(handler) as client:
        assert await client.list_metadata_resources() == []


async def test_async_get_metadata_resource_returns_etag() -> None:
    resource_payload = {
        "apiVersion": "honua/v1",
        "kind": "Service",
        "metadata": {"name": "default", "namespace": "public"},
        "spec": {},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_api_response(resource_payload),
            headers={"ETag": "abc123"},
        )

    async with _async_admin_client(handler) as client:
        resource, etag = await client.get_metadata_resource("Service", "public", "default")

    assert isinstance(resource, MetadataResource)
    assert etag == "abc123"


async def test_async_create_metadata_resource() -> None:
    resource = MetadataResource.from_dict(
        {
            "apiVersion": "honua/v1",
            "kind": "Service",
            "metadata": {"name": "default", "namespace": "public"},
            "spec": {},
        }
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=make_api_response(resource.to_dict()))

    async with _async_admin_client(handler) as client:
        result = await client.create_metadata_resource(resource)

    assert isinstance(result, MetadataResource)


async def test_async_update_metadata_resource_with_if_match_header() -> None:
    resource = MetadataResource.from_dict(
        {
            "apiVersion": "honua/v1",
            "kind": "Service",
            "metadata": {"name": "default", "namespace": "public"},
            "spec": {"updated": True},
        }
    )

    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["if_match"] = request.headers.get("if-match", "")
        return httpx.Response(200, json=make_api_response(resource.to_dict()))

    async with _async_admin_client(handler) as client:
        result = await client.update_metadata_resource(
            "Service", "public", "default", resource, if_match="prev-etag"
        )

    assert seen["if_match"] == "prev-etag"
    assert isinstance(result, MetadataResource)


async def test_async_delete_metadata_resource_with_if_match() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["if_match"] = request.headers.get("if-match", "")
        return httpx.Response(204)

    async with _async_admin_client(handler) as client:
        await client.delete_metadata_resource(
            "Service", "public", "default", if_match="prev-etag"
        )

    assert seen["method"] == "DELETE"
    assert seen["if_match"] == "prev-etag"
