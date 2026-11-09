"""Preserve the object-id field declared by a FeatureServer query response."""

from typing import Any

import httpx
import pytest

from honua_sdk import AsyncHonuaClient, HonuaClient, Query, SourceDescriptor, SourceLocator
from honua_sdk.models import FeatureSet


DESCRIPTOR = SourceDescriptor(
    id="sample",
    protocol="geoservices-feature-service",
    locator=SourceLocator(service_id="sample", layer_id=1),
)


def query_response(object_id: int) -> dict[str, Any]:
    return {
        "objectIdFieldName": "gid",
        "geometryType": "esriGeometryPoint",
        "fields": [{"name": "gid", "type": "esriFieldTypeOID"}],
        "features": [{
            "attributes": {"gid": object_id, "OBJECTID": 999},
            "geometry": {"x": -157.8, "y": 21.3},
        }],
        "exceededTransferLimit": False,
    }


@pytest.mark.parametrize("object_id", [0, 1, 2147483648])
def test_source_query_preserves_the_declared_object_id(object_id: int) -> None:
    payload = query_response(object_id)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with HonuaClient("https://example.test", transport=transport) as client:
        result = client.source(DESCRIPTOR).query(Query(where="1=1", out_fields=["*"]))
    feature = result.features[0]
    assert feature.id == object_id
    assert feature.properties["gid"] == object_id
    assert feature.raw == payload["features"][0]


@pytest.mark.asyncio
async def test_async_source_query_and_stream_keep_the_declared_id() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=query_response(7)))
    async with AsyncHonuaClient("https://example.test", transport=transport) as client:
        source = client.source(DESCRIPTOR)
        result = await source.query(Query(where="1=1"))
        streamed = [feature async for feature in source.stream(Query(where="1=1"))]
    assert result.features[0].id == 7
    assert streamed[0].id == 7


def test_feature_set_keeps_legacy_objectid_and_empty_results() -> None:
    legacy = FeatureSet.from_dict({"features": [{"attributes": {"OBJECTID": 3}}]})
    assert legacy.features[0].object_id == 3
    assert FeatureSet.from_dict({"objectIdFieldName": "gid", "features": []}).features == ()


def test_missing_declared_field_does_not_pick_an_unrelated_objectid() -> None:
    page = FeatureSet.from_dict({
        "objectIdFieldName": "gid", "features": [{"attributes": {"OBJECTID": 999}}],
    })
    assert page.features[0].object_id is None
