"""Public catalog paths round-trip through the shared GeoServices adapters."""

from __future__ import annotations

import inspect

import httpx
import pytest

import honua_sdk
from honua_sdk import AsyncHonuaClient, HonuaClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("public_path", ["Parcels", "Survey/Parcels"])
@pytest.mark.parametrize("operation", ["query", "metadata", "edit", "export"])
@pytest.mark.parametrize(("mount", "absolute"), [("", True), ("/mounted", False)])
async def test_geoservices_uses_public_path_at_each_adapter(asynchronous: bool, public_path: str, operation: str, mount: str, absolute: bool) -> None:
    suffixes = {"query": "FeatureServer/0/query", "metadata": "FeatureServer", "edit": "FeatureServer/0/applyEdits", "export": "MapServer/export"}

    def handler(request: httpx.Request) -> httpx.Response:
        expected = f"{mount}/rest/services/{public_path}/{suffixes[operation]}".encode()
        assert request.url.raw_path.split(b"?")[0] == expected
        if operation == "edit":
            return httpx.Response(200, json={"addResults": [{"objectId": 1, "success": True}]})
        return httpx.Response(200, json={"features": [], "layers": [], "href": "https://example.invalid/map.png"})

    client_type = AsyncHonuaClient if asynchronous else HonuaClient
    client = client_type("http://test.honua.io" + mount, transport=httpx.MockTransport(handler))
    try:
        service_type = "MapServer" if operation == "export" else "FeatureServer"
        service = public_path if "/" not in public_path else honua_sdk.ServiceAddress(
            ("http://test.honua.io" if absolute else "") + f"{mount}/rest/services/{public_path}/{service_type}"
        )
        if operation == "query":
            result = client.query_features(service, 0)
        elif operation == "metadata":
            result = client.feature_server(service).metadata()
        elif operation == "edit":
            result = client.apply_edits(service, 0, adds=[{"attributes": {"name": "Parcel"}}])
        else:
            result = client.export_map(service, [0, 0, 1, 1])
        if inspect.isawaitable(result):
            await result
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("typed", [False, True])
@pytest.mark.parametrize(("folder_name", "encoded_name"), [("Survey", "Survey"), ("Field Survey", "Field%20Survey")])
async def test_folder_catalog_returns_public_service_paths(asynchronous: bool, typed: bool, folder_name: str, encoded_name: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path.split(b"?")[0] == f"/rest/services/{encoded_name}".encode()
        return httpx.Response(200, json={"services": [{"name": f"{folder_name}/Parcels", "type": "FeatureServer"}]})

    client_type = AsyncHonuaClient if asynchronous else HonuaClient
    client = client_type("http://test.honua.io", transport=httpx.MockTransport(handler))
    try:
        result = client.list_service_summaries(folder_name=folder_name) if typed else client.list_services(folder_name=folder_name)
        if inspect.isawaitable(result):
            result = await result
        assert (result[0].name if typed else result["services"][0]["name"]) == f"{folder_name}/Parcels"
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("operation", ["query", "metadata", "edit"])
@pytest.mark.parametrize("absolute", [False, True])
async def test_source_locator_uses_returned_service_url_and_keeps_logical_identity(asynchronous: bool, operation: str, absolute: bool) -> None:
    suffixes = {"query": "/0/query", "metadata": "", "edit": "/0/applyEdits"}

    def handler(request: httpx.Request) -> httpx.Response:
        expected = "/mounted/rest/services/Survey/Parcels/FeatureServer" + suffixes[operation]
        assert request.url.raw_path.split(b"?")[0] == expected.encode()
        if operation == "edit":
            return httpx.Response(200, json={"addResults": [{"objectId": 1, "success": True}]})
        return httpx.Response(200, json={"features": [{"attributes": {"OBJECTID": 1}}], "layers": []})

    client_type = AsyncHonuaClient if asynchronous else HonuaClient
    client = client_type("http://test.honua.io/mounted", transport=httpx.MockTransport(handler))
    source = client.source({"id": "logical-parcels", "protocol": "geoservices-feature-service", "locator": {
        "serviceId": "logical-parcels", "layerId": 0,
        "url": ("http://test.honua.io" if absolute else "") + "/mounted/rest/services/Survey/Parcels/FeatureServer",
    }})
    try:
        if operation == "query":
            result = source.query()
        elif operation == "metadata":
            result = source.protocol().metadata()
        else:
            result = source.apply_edits(adds=[{"attributes": {"name": "Parcel"}}])
        if inspect.isawaitable(result):
            result = await result
        assert source.descriptor.id == "logical-parcels"
        if operation == "query":
            assert result.source_id == "logical-parcels"
            assert result.features[0].source == "logical-parcels"
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()


@pytest.mark.parametrize("url", [
    "//another.honua.io/rest/services/Parcels/FeatureServer", "file:///FeatureServer",
    "https://user:password@test.honua.io/rest/services/Parcels/FeatureServer",
    "https://test.honua.io/rest/services/Parcels/FeatureServer?token=fixture",
    "https://test.honua.io/rest/services/Parcels/FeatureServer#fragment",
    "https://test.honua.io:0/rest/services/Parcels/FeatureServer",
])
def test_service_address_rejects_ambiguous_or_credential_bearing_urls(url: str) -> None:
    with pytest.raises(ValueError):
        honua_sdk.ServiceAddress(url)


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("url", [
    "https://another.honua.io/rest/services/Survey/Parcels/FeatureServer",
    "http://test.honua.io/rest/services/Survey/Parcels/FeatureServer",
    "https://test.honua.io:9443/rest/services/Survey/Parcels/FeatureServer",
])
async def test_explicit_service_address_keeps_shared_origin_guard(asynchronous: bool, url: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("An out-of-origin Service link must fail before an HTTP send")

    client_type = AsyncHonuaClient if asynchronous else HonuaClient
    client = client_type("https://test.honua.io", api_key="unit-fixture", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(honua_sdk.HonuaError, match="outside the client's configured origin"):
            result = client.feature_server(honua_sdk.ServiceAddress(url)).metadata()
            if inspect.isawaitable(result):
                await result
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_explicit_service_address_preserves_encoded_path_and_base(asynchronous: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path.split(b"?")[0] == b"/mounted/rest/services/S%C3%BArvey/P%C3%A1rcels/FeatureServer"
        return httpx.Response(200, json={"layers": []})

    client_type = AsyncHonuaClient if asynchronous else HonuaClient
    client = client_type("https://test.honua.io/mounted", transport=httpx.MockTransport(handler))
    try:
        result = client.feature_server(honua_sdk.ServiceAddress(
            "https://test.honua.io/mounted/rest/services/S%C3%BArvey/P%C3%A1rcels/FeatureServer",
        )).metadata()
        if inspect.isawaitable(result):
            await result
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()


def test_service_address_refuses_wrong_protocol_before_http_send() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("A mismatched protocol link must fail before an HTTP send")

    with HonuaClient("https://test.honua.io", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="MapServer"):
            client.export_map(honua_sdk.ServiceAddress("https://test.honua.io/rest/services/Survey/Parcels/FeatureServer"), [0, 0, 1, 1])


def test_feature_query_refuses_service_url_for_other_protocol() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("A Service link cannot be silently ignored for another protocol")

    with HonuaClient("https://test.honua.io", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="only for FeatureServer"):
            client.query(honua_sdk.FeatureQuery(source="parcels", protocol="ogc-features", service_url="https://test.honua.io/rest/services/Parcels/FeatureServer"))


@pytest.mark.parametrize("suffix", ["?", "#"])
def test_service_address_rejects_empty_query_or_fragment(suffix: str) -> None:
    with pytest.raises(ValueError):
        honua_sdk.ServiceAddress("https://test.honua.io/rest/services/Parcels/FeatureServer" + suffix)


@pytest.mark.parametrize("folder_name", ["", " ", ".", ".."])
def test_folder_discovery_cannot_normalize_an_invalid_folder_to_root(folder_name: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("An invalid Folder selection cannot silently read Root")

    with HonuaClient("https://test.honua.io", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            client.list_services(folder_name=folder_name)


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(("protocol", "action"), [
    ("ogc-features", "query"), ("stac", "query"), ("odata", "query"),
    ("ogc-features", "native"), ("stac", "native"), ("odata", "native"),
    ("wms", "native"), ("wmts", "native"), ("geoservices-geometry-service", "native"),
])
async def test_source_link_cannot_be_ignored_for_another_protocol(asynchronous: bool, protocol: str, action: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("An incompatible explicit Service link must fail before sending")

    client_type = AsyncHonuaClient if asynchronous else HonuaClient
    client = client_type("https://test.honua.io", transport=httpx.MockTransport(handler))
    source = client.source({"id": "logical", "protocol": protocol, "locator": {
        "serviceId": "logical", "collectionId": "collection", "entitySet": "Features",
        "url": "/rest/services/Survey/Parcels/FeatureServer",
    }})
    try:
        with pytest.raises(ValueError, match="Service"):
            result = source.query() if action == "query" else source.protocol()
            if inspect.isawaitable(result):
                await result
    finally:
        closed = client.close()
        if inspect.isawaitable(closed):
            await closed


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(("factory", "service_type"), [
    ("feature_server", "FeatureServer"), ("map_server", "MapServer"), ("image_server", "ImageServer"),
])
async def test_protocol_wrappers_keep_supplied_link_and_resolve_at_request(asynchronous: bool, factory: str, service_type: str) -> None:
    path = f"/mounted/rest/services/Survey/Parcels/{service_type}"
    address = honua_sdk.ServiceAddress(path)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path.split(b"?")[0] == path.encode()
        return httpx.Response(200, json={"layers": []})

    client_type = AsyncHonuaClient if asynchronous else HonuaClient
    client = client_type("https://test.honua.io/mounted", transport=httpx.MockTransport(handler))
    wrapper = getattr(client, factory)(address)
    try:
        assert wrapper.service_id is address
        result = wrapper.metadata()
        if inspect.isawaitable(result):
            await result
    finally:
        closed = client.close()
        if inspect.isawaitable(closed):
            await closed


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("facade", ["source", "client"])
async def test_streaming_preserves_advertised_folder_link_and_logical_identity(asynchronous: bool, facade: str) -> None:
    path = "/mounted/rest/services/Survey/Parcels/FeatureServer"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path.split(b"?")[0] == (path + "/0/query").encode()
        return httpx.Response(200, json={"features": [{"attributes": {"OBJECTID": 7}}]})

    client_type = AsyncHonuaClient if asynchronous else HonuaClient
    client = client_type("https://test.honua.io/mounted", transport=httpx.MockTransport(handler))
    try:
        source = client.source({"id": "logical", "protocol": "geoservices-feature-service", "locator": {
            "serviceId": "internal", "layerId": 0, "url": path,
        }})
        stream = source.stream() if facade == "source" else client.iter_query(
            honua_sdk.FeatureQuery(source="logical", layer_id=0, service_url=path)
        )
        features = [item async for item in stream] if asynchronous else list(stream)
        assert len(features) == 1
        assert features[0].id == 7
        assert features[0].source == "logical"
    finally:
        closed = client.close()
        if inspect.isawaitable(closed):
            await closed


def test_service_path_resolves_relative_link_without_caller_preparation() -> None:
    from honua_sdk.protocols._base import _service_path

    path = "/mounted/rest/services/Survey/Parcels/FeatureServer"
    assert _service_path(honua_sdk.ServiceAddress(path), "FeatureServer", "https://test.honua.io/mounted") == "https://test.honua.io" + path
