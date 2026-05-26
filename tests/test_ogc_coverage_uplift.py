"""Coverage uplift tests for ``honua_sdk.ogc``.

Targets sync paging edge cases (next-link traversal, max_pages cutoff,
short final page break), the sync helper methods that are not exercised
elsewhere (conformance/queryables/get_collection/iter_items/items_pages),
the full asynchronous surface (landing/conformance/collections/get_collection/
queryables/items/items_pages/items_all/iter_items/item/create/replace/patch/
delete), and the small private helpers.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import HonuaClient
from honua_sdk.async_client import AsyncHonuaClient
from honua_sdk.ogc import (
    _features_from_collection,
    _next_link,
    _normalize_max_pages,
    _normalize_offset,
    _normalize_page_size,
    _normalize_total_limit,
    _path_and_params_from_href,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


class TestPrivateHelpers:
    def test_features_from_collection_handles_missing_or_malformed(self) -> None:
        assert _features_from_collection({}) == []
        assert _features_from_collection({"features": None}) == []
        assert _features_from_collection({"features": "not-a-list"}) == []
        assert _features_from_collection(
            {"features": [{"type": "Feature"}, "junk", 3]}
        ) == [{"type": "Feature"}]

    def test_next_link_returns_none_when_links_missing_or_bad(self) -> None:
        assert _next_link({}) is None
        assert _next_link({"links": None}) is None
        assert _next_link({"links": "string-is-sequence-but-rejected"}) is None
        # links contains non-mapping entries and self-link only
        assert (
            _next_link({"links": ["bad", {"rel": "self", "href": "/x"}]}) is None
        )
        # next link with non-string href
        assert _next_link({"links": [{"rel": "next", "href": 42}]}) is None

    def test_next_link_returns_href(self) -> None:
        assert (
            _next_link({"links": [{"rel": "next", "href": "/items?page=2"}]})
            == "/items?page=2"
        )

    def test_path_and_params_from_href(self) -> None:
        path, params = _path_and_params_from_href("/items?a=1&b=2")
        assert path == "/items"
        assert params == {"a": "1", "b": "2"}
        # Bare path (no query) still returns the path with empty params
        bare_path, bare_params = _path_and_params_from_href("/just-a-path")
        assert bare_path == "/just-a-path"
        assert bare_params == {}

    def test_normalize_page_size_falls_back(self) -> None:
        assert _normalize_page_size(50, None) == 50
        assert _normalize_page_size(None, 25) == 25
        assert _normalize_page_size(None, None) == 100
        # Zero or negative values fall through to the default
        assert _normalize_page_size(0, None) == 100
        assert _normalize_page_size(-5, None) == 100

    def test_normalize_max_pages(self) -> None:
        assert _normalize_max_pages(7) == 7
        assert _normalize_max_pages(None) == 100
        assert _normalize_max_pages(0) == 100

    def test_normalize_offset(self) -> None:
        assert _normalize_offset(None) == 0
        assert _normalize_offset(-3) == 0
        assert _normalize_offset(12) == 12

    def test_normalize_total_limit(self) -> None:
        assert _normalize_total_limit(None) is None
        assert _normalize_total_limit(0) == 0
        assert _normalize_total_limit(-1) == 0
        assert _normalize_total_limit(7) == 7


# ---------------------------------------------------------------------------
# Sync HonuaOgcFeatures coverage
# ---------------------------------------------------------------------------


def _ogc_routes() -> dict[str, Any]:
    """Reusable per-route response map for the sync coverage tests."""

    return {
        "/ogc/features": {"title": "Honua"},
        "/ogc/features/conformance": {"conformsTo": ["x"]},
        "/ogc/features/collections": {"collections": []},
        "/ogc/features/collections/parcels": {"id": "parcels"},
        "/ogc/features/collections/parcels/queryables": {"properties": {}},
    }


def test_sync_landing_conformance_collections_get_collection_queryables() -> None:
    seen: list[str] = []
    routes = _ogc_routes()

    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append(raw_path)
        return httpx.Response(200, json=routes[raw_path])

    with HonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        ogc = client.ogc_features()
        assert ogc.landing()["title"] == "Honua"
        assert ogc.conformance()["conformsTo"] == ["x"]
        assert ogc.collections() == {"collections": []}
        assert ogc.get_collection("parcels") == {"id": "parcels"}
        assert ogc.queryables("parcels")["properties"] == {}

    assert seen == [
        "/ogc/features",
        "/ogc/features/conformance",
        "/ogc/features/collections",
        "/ogc/features/collections/parcels",
        "/ogc/features/collections/parcels/queryables",
    ]


def test_sync_items_pages_follows_next_link() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii")
        seen_paths.append(path)
        if "page=2" in path:
            # Final page; no next link, short page count terminates loop
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [{"id": 3}],
                    "links": [],
                },
            )
        # First page advertises a next link
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"id": 1}, {"id": 2}],
                "links": [
                    {
                        "rel": "next",
                        "href": "/ogc/features/collections/parcels/items?page=2",
                    }
                ],
            },
        )

    with HonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        pages = list(
            client.ogc_features().collection("parcels").items_pages(page_size=2)
        )

    assert [page["features"][0]["id"] for page in pages] == [1, 3]
    # First call sends limit=2; second call comes from the next-link href
    assert "limit=2" in seen_paths[0]
    assert "page=2" in seen_paths[1]
    assert len(seen_paths) == 2


def test_sync_items_pages_breaks_on_short_final_page_without_next_link() -> None:
    """When a page returns fewer features than requested and has no next
    link, iteration should stop without issuing further requests."""

    request_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"id": 1}],  # short page
                "links": [],
            },
        )

    with HonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        features = (
            client.ogc_features().collection("parcels").items_all(page_size=5)
        )

    assert features == [{"id": 1}]
    assert request_count["n"] == 1


def test_sync_iter_items_stops_at_user_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"id": i} for i in range(10)],
                "links": [],
            },
        )

    with HonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        emitted = list(
            client.ogc_features().collection("parcels").iter_items(
                page_size=10, limit=3
            )
        )

    assert [item["id"] for item in emitted] == [0, 1, 2]


def test_sync_items_pages_facade_delegates_through_features_class() -> None:
    """``HonuaOgcFeatures.items_pages`` and ``iter_items`` are thin
    facades. Exercising them ensures their bodies are hit."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"id": 1}],
                "links": [],
            },
        )

    with HonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        pages = list(client.ogc_features().items_pages("parcels", page_size=5))
        items = list(client.ogc_features().iter_items("parcels", page_size=5))
        items_all = client.ogc_features().items_all("parcels", page_size=5)

    assert pages and items == [{"id": 1}] and items_all == [{"id": 1}]


def test_sync_items_pages_max_pages_cutoff() -> None:
    """``max_pages`` should bound the number of pages even when next links
    keep arriving."""

    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"id": counter["n"]}, {"id": counter["n"] + 100}],
                "links": [{"rel": "next", "href": "/ogc/features/collections/parcels/items?cont"}],
            },
        )

    with HonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        pages = list(
            client.ogc_features()
            .collection("parcels")
            .items_pages(page_size=2, max_pages=2)
        )

    assert len(pages) == 2
    assert counter["n"] == 2


def test_sync_item_get_uses_crs_parameter() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["raw_path"] = request.url.raw_path.decode("ascii").split("?")[0]
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json={"type": "Feature", "id": "p/1"})

    with HonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        client.ogc_features().collection("parcels").item("p/1", crs="EPSG:4326")

    assert seen["raw_path"] == "/ogc/features/collections/parcels/items/p%2F1"
    assert seen["query"]["crs"] == "EPSG:4326"


# ---------------------------------------------------------------------------
# Async coverage
# ---------------------------------------------------------------------------


pytestmark = pytest.mark.anyio


async def test_async_landing_conformance_collections_get_collection_queryables() -> None:
    routes = _ogc_routes()
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append(raw_path)
        return httpx.Response(200, json=routes[raw_path])

    async with AsyncHonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        ogc = client.ogc_features()
        assert (await ogc.landing())["title"] == "Honua"
        assert (await ogc.conformance())["conformsTo"] == ["x"]
        assert await ogc.collections() == {"collections": []}
        assert await ogc.get_collection("parcels") == {"id": "parcels"}
        assert (await ogc.queryables("parcels"))["properties"] == {}

    assert seen == list(routes)


async def test_async_items_pages_follows_next_link() -> None:
    seen_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii")
        seen_paths.append(path)
        if "page=2" in path:
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [{"id": 3}],
                    "links": [],
                },
            )
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"id": 1}, {"id": 2}],
                "links": [
                    {
                        "rel": "next",
                        "href": "/ogc/features/collections/parcels/items?page=2",
                    }
                ],
            },
        )

    async with AsyncHonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        pages = [
            page
            async for page in client.ogc_features()
            .collection("parcels")
            .items_pages(page_size=2)
        ]

    assert [page["features"][0]["id"] for page in pages] == [1, 3]
    assert "limit=2" in seen_paths[0]
    assert "page=2" in seen_paths[1]
    assert len(seen_paths) == 2


async def test_async_iter_items_stops_at_user_limit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"id": i} for i in range(10)],
                "links": [],
            },
        )

    async with AsyncHonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        emitted = [
            item
            async for item in client.ogc_features()
            .collection("parcels")
            .iter_items(page_size=10, limit=3)
        ]

    assert [item["id"] for item in emitted] == [0, 1, 2]


async def test_async_items_pages_facade_delegates() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"id": 1}],
                "links": [],
            },
        )

    async with AsyncHonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        pages = [
            page
            async for page in client.ogc_features().items_pages(
                "parcels", page_size=5
            )
        ]
        items = [
            item
            async for item in client.ogc_features().iter_items(
                "parcels", page_size=5
            )
        ]
        all_items = await client.ogc_features().items_all("parcels", page_size=5)

    assert pages and items == [{"id": 1}] and all_items == [{"id": 1}]


async def test_async_item_crud_full_surface() -> None:
    seen: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        seen.append(
            {
                "method": request.method,
                "path": request.url.raw_path.decode("ascii").split("?")[0],
                "content_type": request.headers.get("content-type", ""),
                "body": body,
                "query": dict(request.url.params.multi_items()),
            }
        )
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"type": "Feature", "id": "p/1"})

    feature = {"type": "Feature", "geometry": None, "properties": {"a": 1}}
    async with AsyncHonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        ogc = client.ogc_features()
        parcels = ogc.collection("parcels")
        assert (await parcels.item("p/1", crs="EPSG:4326"))["id"] == "p/1"
        assert (await parcels.create_item(feature))["id"] == "p/1"
        assert (await parcels.replace_item("p/1", feature, crs="EPSG:4326"))[
            "id"
        ] == "p/1"
        assert (
            await parcels.patch_item(
                "p/1", {"properties": {"a": 2}}, crs="EPSG:4326"
            )
        )["id"] == "p/1"
        await parcels.delete_item("p/1", crs="EPSG:4326")

    assert [(entry["method"], entry["path"]) for entry in seen] == [
        ("GET", "/ogc/features/collections/parcels/items/p%2F1"),
        ("POST", "/ogc/features/collections/parcels/items"),
        ("PUT", "/ogc/features/collections/parcels/items/p%2F1"),
        ("PATCH", "/ogc/features/collections/parcels/items/p%2F1"),
        ("DELETE", "/ogc/features/collections/parcels/items/p%2F1"),
    ]
    assert seen[1]["content_type"].startswith("application/geo+json")
    assert seen[3]["content_type"].startswith("application/merge-patch+json")
    assert seen[4]["query"]["crs"] == "EPSG:4326"


async def test_async_items_all_zero_limit_skips_requests() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("limit=0 should not issue any requests")

    async with AsyncHonuaClient(
        "http://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        assert (
            await client.ogc_features().collection("parcels").items_all(limit=0)
        ) == []
