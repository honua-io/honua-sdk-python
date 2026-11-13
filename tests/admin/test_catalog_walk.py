"""The full-list walk stops for a reason, and a bad page is rejected before HTTP."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from honua_admin import (
    AsyncHonuaAdminClient,
    HonuaAdminClient,
    LayerListQuery,
    PublishedLayerPage,
    ServiceListPage,
    ServiceListQuery,
)

from .conftest import layer_page, make_api_response, service_page

_SERVICE = {
    "serviceName": "parks",
    "description": None,
    "layerCount": 1,
    "enabledProtocols": [],
}
_LAYER = {
    "storageLayerId": 1,
    "layerName": "parcels",
    "schema": "public",
    "table": "parcels",
    "description": None,
    "geometryType": "Polygon",
    "srid": 4326,
    "primaryKey": "gid",
    "fieldCount": 1,
    "enabled": True,
    "serviceName": "roads",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _item(catalog: str, index: int) -> dict[str, Any]:
    if catalog == "services":
        return {**_SERVICE, "serviceName": f"s{index}"}
    return {**_LAYER, "storageLayerId": index, "layerName": f"layer-{index}"}


def _pages(catalog: str, case: str) -> dict[int, dict[str, Any]]:
    build = service_page if catalog == "services" else layer_page
    if case == "empty":
        return {1: build([], total=10)}
    if case == "short":
        return {1: build([_item(catalog, 1)], total=10)}
    if case == "total":
        return {1: build([_item(catalog, i) for i in range(1, 101)], total=100)}
    return {
        1: build([_item(catalog, i) for i in range(1, 101)], total=101),
        2: build([_item(catalog, 101)], total=101, page=2),
    }


def _expected_count(case: str) -> int:
    return {"empty": 0, "short": 1, "total": 100, "next": 101}[case]


async def _read(catalog: str, async_client: bool, handler: Any) -> list[Any]:
    transport = httpx.MockTransport(handler)
    options = {"timeout": 1.5, "extra_headers": {"X-Trace-Id": "walk"}}
    if catalog == "services" and async_client:
        async with AsyncHonuaAdminClient("http://test.honua.io", transport=transport) as client:
            return await client.list_services(**options)
    if catalog == "services":
        with HonuaAdminClient("http://test.honua.io", transport=transport) as client:
            return client.list_services(**options)
    if async_client:
        async with AsyncHonuaAdminClient("http://test.honua.io", transport=transport) as client:
            return await client.list_layers("conn-001", service_name="roads", **options)
    with HonuaAdminClient("http://test.honua.io", transport=transport) as client:
        return client.list_layers("conn-001", service_name="roads", **options)


@pytest.mark.anyio
@pytest.mark.parametrize("async_client", [False, True])
@pytest.mark.parametrize("catalog", ["services", "layers"])
@pytest.mark.parametrize("case", ["empty", "short", "total", "next"])
async def test_full_list_stops_for_a_reason(async_client: bool, catalog: str, case: str) -> None:
    calls: list[httpx.Request] = []
    pages = _pages(catalog, case)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        page_number = int(request.url.params["page"])
        return httpx.Response(200, json=make_api_response(pages[page_number]))

    result = await _read(catalog, async_client, handler)

    assert [int(request.url.params["page"]) for request in calls] == ([1, 2] if case == "next" else [1])
    assert {request.url.params["pageSize"] for request in calls} == {"100"}
    assert len(result) == _expected_count(case)
    for request in calls:
        assert request.headers["x-trace-id"] == "walk"
        assert request.extensions["timeout"]["connect"] == 1.5
        if catalog == "layers":
            assert request.url.params["serviceName"] == "roads"


@pytest.mark.parametrize("parse", [ServiceListPage.from_dict, PublishedLayerPage.from_dict])
@pytest.mark.parametrize("payload", [[], "rows", 3])
def test_page_object_rejects_a_non_object(parse: Any, payload: Any) -> None:
    with pytest.raises(ValueError, match="page object"):
        parse(payload)


@pytest.mark.parametrize(
    ("parse", "kind"),
    [(ServiceListPage.from_dict, "Service list"), (PublishedLayerPage.from_dict, "Layer list")],
)
def test_page_items_must_be_objects(parse: Any, kind: str) -> None:
    with pytest.raises(ValueError, match=f"{kind} items"):
        parse({"items": ["row"]})


_REJECTED_QUERIES = [
    ("services", ServiceListQuery(page=0), "page must be at least 1"),
    ("layers", LayerListQuery(page=0), "page must be at least 1"),
    ("services", ServiceListQuery(page_size=0), "page_size"),
    ("layers", LayerListQuery(page_size=0), "page_size"),
    ("services", ServiceListQuery(page_size=101), "page_size"),
    ("layers", LayerListQuery(page_size=101), "page_size"),
    ("services", ServiceListQuery(name_query="q" * 201), "name query"),
    ("layers", LayerListQuery(name_query="q" * 201), "name query"),
]


def _read_one_page(client: Any, catalog: str, query: Any = None) -> Any:
    if catalog == "services":
        return client.list_services_page(query)
    return client.list_layers_page("conn-001", query)


@pytest.mark.parametrize(("catalog", "query", "match"), _REJECTED_QUERIES)
def test_page_query_makes_no_request(make_client: Any, catalog: str, query: Any, match: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(request.url)

    with make_client(handler) as client:
        with pytest.raises(ValueError, match=match):
            _read_one_page(client, catalog, query)


@pytest.mark.parametrize("catalog", ["services", "layers"])
def test_page_rejects_a_json_list_from_the_server(make_client: Any, catalog: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response([]))

    with make_client(handler) as client:
        with pytest.raises(ValueError, match="page object"):
            _read_one_page(client, catalog)
