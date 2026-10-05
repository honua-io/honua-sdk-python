"""Regression for #259: sync/async unary/stream calls must reach geospatial.v1."""
from __future__ import annotations

import asyncio

import pytest

from honua_sdk.grpc import HonuaGrpcAsyncClient, HonuaGrpcClient, QueryFeaturesRequest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("stream", [False, True], ids=["unary", "stream"])
def test_sync_query_reaches_candidate(grpc_target: str, stream: bool) -> None:
    request = QueryFeaturesRequest(service_id="test_service", layer_id=0, result_record_count=1)
    with HonuaGrpcClient(grpc_target, insecure=True) as client:
        if stream:
            pages = list(client.query_features_stream(request))
            assert pages[-1].is_last_page
            features = [feature for page in pages for feature in page.features]
            assert pages[0].object_id_field_name
        else:
            response = client.query_features(request)
            assert response.object_id_field_name
            features = response.features
    assert len(features) == 1
    assert features[0].attributes
    assert features[0].geometry


@pytest.mark.parametrize("stream", [False, True], ids=["unary", "stream"])
def test_async_query_reaches_candidate(grpc_target: str, stream: bool) -> None:
    async def query() -> None:
        request = QueryFeaturesRequest(service_id="test_service", layer_id=0, result_record_count=1)
        async with HonuaGrpcAsyncClient(grpc_target, insecure=True) as client:
            if stream:
                pages = [page async for page in client.query_features_stream(request)]
                assert pages[-1].is_last_page
                features = [feature for page in pages for feature in page.features]
                assert pages[0].object_id_field_name
            else:
                response = await client.query_features(request)
                assert response.object_id_field_name
                features = response.features
        assert len(features) == 1
        assert features[0].attributes
        assert features[0].geometry

    asyncio.run(query())
