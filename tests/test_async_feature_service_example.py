"""Tests for the async FastAPI feature-service example.

The framework-free helpers are exercised directly against a fake client. The
ASGI routes are driven through ``httpx.ASGITransport`` with a stubbed
``AsyncHonuaClient`` injected into ``app.state``, so no live Honua server is
needed. The route tests skip cleanly when ``fastapi`` is not installed.
"""

from __future__ import annotations

from typing import Any

import pytest

from examples.async_feature_service import service


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes shared across the helper and route tests.
# ---------------------------------------------------------------------------


class FakeFeature:
    def __init__(self, status: str, geometry: dict[str, Any] | None = None) -> None:
        self.properties = {"status": status}
        self.geometry = geometry


class FakeResult:
    def __init__(self, features: list[FakeFeature]) -> None:
        self.features = features


class FakeServiceSummary:
    def __init__(self, name: str, type_: str | None, url: str | None) -> None:
        self.name = name
        self.type = type_
        self.url = url


class FakeAsyncSource:
    def __init__(self, seen: dict[str, Any]) -> None:
        self._seen = seen

    async def query(self, query: Any, **kwargs: Any) -> FakeResult:
        self._seen["where"] = query.where
        self._seen["bbox"] = query.bbox
        self._seen["limit"] = kwargs.get("limit")
        return FakeResult(
            [FakeFeature("active", {"x": -157.0, "y": 21.0}), FakeFeature("closed")]
        )


class FakeClient:
    def __init__(self) -> None:
        self.seen: dict[str, Any] = {}

    def source(self, descriptor: Any) -> FakeAsyncSource:
        self.seen["service_id"] = descriptor.locator.service_id
        self.seen["layer_id"] = descriptor.locator.layer_id
        return FakeAsyncSource(self.seen)

    async def list_service_summaries(self) -> list[FakeServiceSummary]:
        return [
            FakeServiceSummary("test_service", "FeatureServer", "https://h/test_service"),
            FakeServiceSummary("imagery", "ImageServer", None),
        ]


# ---------------------------------------------------------------------------
# Helper-level tests (framework-free).
# ---------------------------------------------------------------------------


async def test_fetch_features_drives_typed_source_query() -> None:
    client = FakeClient()
    settings = service.ServiceSettings(service_id="incidents", layer_id=3)

    result = await service.fetch_features(
        client,
        settings,
        bbox=(-158.0, 21.0, -157.0, 22.0),
        where="status <> 'closed'",
        limit=25,
    )

    assert client.seen["service_id"] == "incidents"
    assert client.seen["layer_id"] == 3
    assert client.seen["where"] == "status <> 'closed'"
    assert client.seen["bbox"] == [-158.0, 21.0, -157.0, 22.0]
    assert client.seen["limit"] == 25
    assert service.serialize_features(result) == {
        "feature_count": 2,
        "features": [
            {"properties": {"status": "active"}, "geometry": {"x": -157.0, "y": 21.0}},
            {"properties": {"status": "closed"}, "geometry": None},
        ],
    }


async def test_list_services_serializes_typed_summaries() -> None:
    client = FakeClient()

    summaries = await service.list_services(client)
    payload = service.serialize_services(summaries)

    assert payload == {
        "service_count": 2,
        "services": [
            {"name": "test_service", "type": "FeatureServer", "url": "https://h/test_service"},
            {"name": "imagery", "type": "ImageServer", "url": None},
        ],
    }


def test_bbox_parser_validates_shape() -> None:
    assert service._parse_bbox("-158,21,-157,22") == (-158.0, 21.0, -157.0, 22.0)
    with pytest.raises(ValueError, match="four comma-separated"):
        service._parse_bbox("-158,21,-157")
    with pytest.raises(ValueError, match="minimums must be less than"):
        service._parse_bbox("0,0,0,0")


# ---------------------------------------------------------------------------
# ASGI route tests via httpx.ASGITransport (no live server, no real client).
# ---------------------------------------------------------------------------


async def test_routes_serve_features_and_services_via_asgi() -> None:
    pytest.importorskip("fastapi")
    import httpx

    app = service.create_app(service.ServiceSettings(service_id="test_service", layer_id=0))
    # Inject the fake client that the lifespan would otherwise create, and skip
    # lifespan startup so no real AsyncHonuaClient / network client is built.
    app.state.honua_client = FakeClient()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        health = await http.get("/healthz")
        services = await http.get("/services")
        features = await http.get("/features", params={"where": "1=1", "limit": 5})
        bad_bbox = await http.get("/features", params={"bbox": "0,0,0,0"})

    assert health.status_code == 200
    assert services.status_code == 200
    assert services.json()["service_count"] == 2
    assert services.json()["services"][0]["name"] == "test_service"

    assert features.status_code == 200
    body = features.json()
    assert body["feature_count"] == 2
    assert body["features"][0]["properties"]["status"] == "active"

    assert bad_bbox.status_code == 422
