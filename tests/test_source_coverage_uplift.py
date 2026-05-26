"""Coverage uplift tests for ``honua_sdk.source``.

These tests exercise the facade helpers, query coercion edge cases, and
``_protocol_client`` dispatch for every protocol arm. They complement the
narrower behavioral coverage already in ``test_sdk_contract.py`` and
``test_source_filter_routing.py``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from honua_sdk import (
    AsyncHonuaClient,
    HonuaClient,
    Pagination,
    Query,
    SourceDescriptor,
    SourceLocator,
)
from honua_sdk.errors import HonuaCapabilityNotSupportedError
from honua_sdk.source import (
    AsyncSource,
    _coerce_descriptor,
    _coerce_query,
    _csv,
    _extra_params_for_query,
    _feature_query_for_source,
    _layer_id,
    _protocol_client,
    _query_source,
    _unsupported_facade_reason,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# --- _coerce_descriptor ---------------------------------------------------


def test_coerce_descriptor_passes_through_descriptor_instance() -> None:
    descriptor = SourceDescriptor(
        id="x",
        protocol="ogc-features",
        locator=SourceLocator(collection_id="x"),
    )
    assert _coerce_descriptor(descriptor) is descriptor


def test_coerce_descriptor_from_mapping() -> None:
    descriptor = _coerce_descriptor(
        {"id": "x", "protocol": "ogc-features", "locator": {"collectionId": "x"}}
    )
    assert isinstance(descriptor, SourceDescriptor)
    assert descriptor.id == "x"
    assert descriptor.locator.collection_id == "x"


def test_coerce_descriptor_rejects_invalid_type() -> None:
    with pytest.raises(TypeError, match="descriptor must be a SourceDescriptor"):
        _coerce_descriptor(42)  # type: ignore[arg-type]


# --- _coerce_query --------------------------------------------------------


def test_coerce_query_none_returns_default_query() -> None:
    query = _coerce_query(None)
    assert isinstance(query, Query)
    assert query.where is None


def test_coerce_query_from_query_passthrough() -> None:
    original = Query(where="STATE='CA'")
    assert _coerce_query(original) is original


def test_coerce_query_from_mapping() -> None:
    query = _coerce_query({"where": "STATE='CA'"})
    assert query.where == "STATE='CA'"


def test_coerce_query_rejects_invalid_type() -> None:
    with pytest.raises(TypeError, match="query must be a Query"):
        _coerce_query(42)  # type: ignore[arg-type]


def test_coerce_query_applies_fields_alias_with_deprecation() -> None:
    with pytest.warns(DeprecationWarning, match="out_fields"):
        query = _coerce_query(None, fields=["a", "b"])
    assert query.out_fields == ["a", "b"]


def test_coerce_query_applies_filter_alias_with_deprecation() -> None:
    with pytest.warns(DeprecationWarning, match="where"):
        query = _coerce_query(None, filter="STATE='CA'")
    assert query.where == "STATE='CA'"


def test_coerce_query_pagination_updates_propagate() -> None:
    query = _coerce_query(None, limit=5, page_size=2, max_pages=7)
    assert query.pagination.limit == 5
    assert query.pagination.page_size == 2
    assert query.pagination.max_pages == 7


def test_coerce_query_accepts_pagination_via_mapping() -> None:
    query = _coerce_query({"pagination": {"limit": 9}})
    assert isinstance(query.pagination, Pagination)
    assert query.pagination.limit == 9


# --- _unsupported_facade_reason ------------------------------------------


def test_unsupported_facade_reason_none_when_capability_not_advertised() -> None:
    descriptor = SourceDescriptor(id="x", protocol="wms", locator=SourceLocator(service_id="x"))
    # WMS does not advertise applyEdits in its default capability set.
    assert _unsupported_facade_reason(descriptor, "applyEdits") is None


def test_unsupported_facade_reason_messages_when_capability_advertised() -> None:
    descriptor = SourceDescriptor.from_dict(
        {"id": "x", "protocol": "ogc-features", "locator": {"collectionId": "x"}}
    )
    msg = _unsupported_facade_reason(descriptor, "applyEdits")
    assert msg is not None
    assert "ogc-features" in msg
    assert "applyEdits" in msg


# --- _query_source / _layer_id / _extra_params_for_query / _csv ----------


def test_query_source_for_stac_collection() -> None:
    descriptor = SourceDescriptor(
        id="landsat-id",
        protocol="stac",
        locator=SourceLocator(collection_id="landsat"),
    )
    assert _query_source(descriptor) == "landsat"


def test_query_source_for_stac_falls_back_to_descriptor_id() -> None:
    descriptor = SourceDescriptor(id="landsat", protocol="stac")
    assert _query_source(descriptor) == "landsat"


def test_query_source_for_odata_prefers_layer_id() -> None:
    descriptor = SourceDescriptor(
        id="orders",
        protocol="odata",
        locator=SourceLocator(entity_set="Orders", layer_id=42),
    )
    assert _query_source(descriptor) == "42"


def test_query_source_for_odata_falls_back_to_entity_set() -> None:
    descriptor = SourceDescriptor(
        id="orders",
        protocol="odata",
        locator=SourceLocator(entity_set="Orders"),
    )
    assert _query_source(descriptor) == "Orders"


def test_layer_id_defaults_to_zero_for_featureserver_without_layer() -> None:
    descriptor = SourceDescriptor(
        id="x",
        protocol="geoservices-feature-service",
        locator=SourceLocator(service_id="x"),
    )
    assert _layer_id(descriptor) == 0


def test_layer_id_returns_locator_value() -> None:
    descriptor = SourceDescriptor(
        id="x",
        protocol="geoservices-feature-service",
        locator=SourceLocator(service_id="x", layer_id=7),
    )
    assert _layer_id(descriptor) == 7


def test_extra_params_for_query_featureserver_offset_and_order_by_and_out_sr() -> None:
    descriptor = SourceDescriptor(
        id="x",
        protocol="geoservices-feature-service",
        locator=SourceLocator(service_id="x", layer_id=0),
    )
    query = Query(
        pagination=Pagination(offset=10),
        order_by=["NAME", "STATE"],
        out_sr=4326,
    )
    params = _extra_params_for_query(descriptor.protocol, query)
    assert params["resultOffset"] == 10
    assert params["orderByFields"] == "NAME,STATE"
    assert params["outSR"] == 4326


def test_extra_params_for_query_odata_uses_skip_and_orderby() -> None:
    query = Query(pagination=Pagination(offset=4), order_by="Name")
    params = _extra_params_for_query("odata", query)
    assert params["$skip"] == 4
    assert params["$orderby"] == "Name"


def test_extra_params_for_query_ogc_uses_offset_and_sortby() -> None:
    query = Query(pagination=Pagination(offset=2), order_by=["a", "b"])
    params = _extra_params_for_query("ogc-features", query)
    assert params["offset"] == 2
    assert params["sortby"] == "a,b"


def test_csv_handles_string_and_sequence() -> None:
    assert _csv("a,b") == "a,b"
    assert _csv(["a", "b"]) == "a,b"


def test_feature_query_for_unsupported_protocol_raises() -> None:
    descriptor = SourceDescriptor(id="x", protocol="wms", locator=SourceLocator(service_id="x"))
    with pytest.raises(HonuaCapabilityNotSupportedError):
        _feature_query_for_source(descriptor, Query())


# --- _protocol_client dispatch -------------------------------------------


def _client() -> HonuaClient:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    return HonuaClient("http://example.test", transport=transport)


def test_protocol_client_geoservices_feature_service() -> None:
    descriptor = SourceDescriptor(
        id="x",
        protocol="geoservices-feature-service",
        locator=SourceLocator(service_id="Parcels", layer_id=0),
    )
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        assert native.service_id == "Parcels"


def test_protocol_client_geoservices_map_service() -> None:
    descriptor = SourceDescriptor(
        id="x",
        protocol="geoservices-map-service",
        locator=SourceLocator(service_id="basemap"),
    )
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        assert native.service_id == "basemap"


def test_protocol_client_geoservices_image_service() -> None:
    descriptor = SourceDescriptor(
        id="x",
        protocol="geoservices-image-service",
        locator=SourceLocator(service_id="imagery"),
    )
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        assert native.service_id == "imagery"


def test_protocol_client_geoservices_geometry_service() -> None:
    descriptor = SourceDescriptor(id="x", protocol="geoservices-geometry-service")
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        assert native.path.endswith("/GeometryServer")


def test_protocol_client_ogc_features_returns_collection_when_set() -> None:
    descriptor = SourceDescriptor(
        id="x",
        protocol="ogc-features",
        locator=SourceLocator(collection_id="parcels"),
    )
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        # Returned object is a single-collection accessor.
        assert hasattr(native, "items") or hasattr(native, "iter_items")


def test_protocol_client_ogc_features_returns_facade_without_collection() -> None:
    descriptor = SourceDescriptor(id="x", protocol="ogc-features")
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        assert hasattr(native, "collection")


def test_protocol_client_ogc_tiles() -> None:
    descriptor = SourceDescriptor(id="x", protocol="ogc-tiles")
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        assert hasattr(native, "tile_matrix_sets")


def test_protocol_client_ogc_maps() -> None:
    descriptor = SourceDescriptor(id="x", protocol="ogc-maps")
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        assert hasattr(native, "map")


def test_protocol_client_stac() -> None:
    descriptor = SourceDescriptor(id="x", protocol="stac")
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        assert hasattr(native, "catalog")


def test_protocol_client_wfs() -> None:
    descriptor = SourceDescriptor(id="x", protocol="wfs")
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        assert hasattr(native, "capabilities")


def test_protocol_client_wms() -> None:
    descriptor = SourceDescriptor(
        id="x", protocol="wms", locator=SourceLocator(service_id="basemap")
    )
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        assert native.service_id == "basemap"


def test_protocol_client_wmts() -> None:
    descriptor = SourceDescriptor(
        id="x", protocol="wmts", locator=SourceLocator(service_id="basemap")
    )
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        assert native.service_id == "basemap"


def test_protocol_client_odata() -> None:
    descriptor = SourceDescriptor(id="x", protocol="odata")
    with _client() as client:
        native = _protocol_client(client, descriptor, None)
        assert hasattr(native, "service_document")


def test_protocol_client_kind_override_respected() -> None:
    # Passing ``kind`` overrides the descriptor protocol.
    descriptor = SourceDescriptor(
        id="x", protocol="wms", locator=SourceLocator(service_id="basemap")
    )
    with _client() as client:
        native = _protocol_client(client, descriptor, "wmts")
        assert native.service_id == "basemap"
        assert hasattr(native, "path")


# --- Source / AsyncSource façade ------------------------------------------


def _ogc_descriptor() -> SourceDescriptor:
    return SourceDescriptor.from_dict(
        {
            "id": "parcels",
            "protocol": "ogc-features",
            "locator": {"collectionId": "parcels"},
            "capabilities": ["query", "stream"],
        }
    )


def _featureserver_descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        id="parcels-fs",
        protocol="geoservices-feature-service",
        locator=SourceLocator(service_id="Parcels", layer_id=0),
        capabilities=frozenset(("query", "stream", "applyEdits")),
    )


def test_source_id_and_protocol_id_properties() -> None:
    descriptor = _featureserver_descriptor()
    with _client() as client:
        source = client.source(descriptor)
        assert source.id == "parcels-fs"
        assert source.protocol_id == "geoservices-feature-service"


def test_source_query_all_returns_features_tuple() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "features": [
                    {"attributes": {"OBJECTID": 1, "NAME": "A"}, "geometry": {"x": 0, "y": 0}}
                ],
                "exceededTransferLimit": False,
            },
        )

    descriptor = _featureserver_descriptor()
    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        features = client.source(descriptor).query_all(Query(pagination=Pagination(limit=1)))

    assert features[0].id == 1
    assert features[0].properties["NAME"] == "A"


def test_source_stream_yields_features_with_protocol_and_source() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "features": [
                    {"attributes": {"OBJECTID": 1, "NAME": "A"}, "geometry": {"x": 0, "y": 0}}
                ],
                "exceededTransferLimit": False,
            },
        )

    descriptor = _featureserver_descriptor()
    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        source = client.source(descriptor)
        streamed = list(source.stream(Query(pagination=Pagination(limit=1))))

    assert streamed[0].protocol == "geoservices-feature-service"
    assert streamed[0].source == "parcels-fs"


def test_source_iter_features_alias_matches_stream() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "features": [
                    {"attributes": {"OBJECTID": 1, "NAME": "A"}, "geometry": None}
                ],
                "exceededTransferLimit": False,
            },
        )

    descriptor = _featureserver_descriptor()
    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        source = client.source(descriptor)
        items = list(source.iter_features(Query(pagination=Pagination(limit=1))))

    assert items[0].id == 1


def test_source_apply_edits_round_trips_to_featureserver() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(
            200,
            json={"addResults": [{"objectId": 99, "success": True}]},
        )

    descriptor = _featureserver_descriptor()
    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        result = client.source(descriptor).apply_edits(adds=[{"attributes": {"NAME": "X"}}])

    assert seen["method"] == "POST"
    assert seen["path"].endswith("/applyEdits")
    assert result.add_results[0].object_id == 99


def test_source_protocol_escape_hatch_returns_native_client() -> None:
    descriptor = _featureserver_descriptor()
    with _client() as client:
        native = client.source(descriptor).protocol()
        assert native.service_id == "Parcels"


def test_source_supports_returns_false_for_unsupported_protocol() -> None:
    descriptor = SourceDescriptor(
        id="map",
        protocol="wms",
        locator=SourceLocator(service_id="basemap"),
    )
    with _client() as client:
        source = client.source(descriptor)
        assert source.supports("query") is False
        # supports() short-circuits when the descriptor doesn't advertise.
        assert source.supports("stream") is False


# --- AsyncSource ---------------------------------------------------------


@pytest.mark.anyio
async def test_async_source_id_and_protocol_id_properties() -> None:
    descriptor = _featureserver_descriptor()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        source = client.source(descriptor)
        assert isinstance(source, AsyncSource)
        assert source.id == "parcels-fs"
        assert source.protocol_id == "geoservices-feature-service"


@pytest.mark.anyio
async def test_async_source_query_all_and_stream_and_iter_features() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "features": [
                    {"attributes": {"OBJECTID": 1, "NAME": "A"}, "geometry": None}
                ],
                "exceededTransferLimit": False,
            },
        )

    descriptor = _featureserver_descriptor()
    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        source = client.source(descriptor)
        features = await source.query_all(Query(pagination=Pagination(limit=1)))
        streamed = [f async for f in source.stream(Query(pagination=Pagination(limit=1)))]
        iterated = [f async for f in source.iter_features(Query(pagination=Pagination(limit=1)))]

    assert features[0].id == 1
    assert streamed[0].source == "parcels-fs"
    assert iterated[0].properties["NAME"] == "A"


@pytest.mark.anyio
async def test_async_source_apply_edits_round_trips() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(
            200,
            json={"updateResults": [{"objectId": 5, "success": True}]},
        )

    descriptor = _featureserver_descriptor()
    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        result = await client.source(descriptor).apply_edits(
            updates=[{"attributes": {"OBJECTID": 5}}]
        )

    assert seen["method"] == "POST"
    assert seen["path"].endswith("/applyEdits")
    assert result.update_results[0].object_id == 5


@pytest.mark.anyio
async def test_async_source_protocol_escape_hatch() -> None:
    descriptor = _featureserver_descriptor()
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        native = client.source(descriptor).protocol()
        assert native.service_id == "Parcels"


@pytest.mark.anyio
async def test_async_source_unsupported_capability_raises() -> None:
    descriptor = SourceDescriptor(
        id="map", protocol="wms", locator=SourceLocator(service_id="basemap")
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        source = client.source(descriptor)
        with pytest.raises(HonuaCapabilityNotSupportedError):
            await source.query()


# --- Source via OGC: exercise stream() on non-FeatureServer protocol ----


def test_source_query_populates_raw_legacy_with_underlying_result() -> None:
    from honua_sdk.models import FeatureQueryResult

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "features": [
                    {"attributes": {"OBJECTID": 1, "NAME": "A"}, "geometry": None}
                ],
                "exceededTransferLimit": False,
            },
        )

    descriptor = _featureserver_descriptor()
    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        result = client.source(descriptor).query(Query(pagination=Pagination(limit=1)))

    assert result.raw == {}
    assert isinstance(result.raw_legacy, FeatureQueryResult)
    # raw_legacy preserves the underlying (un-renormalized) protocol response.
    assert len(result.raw_legacy.features) == len(result.features)
    assert result.raw_legacy.features[0].id == result.features[0].id


def test_source_client_protocol_recognized_structurally() -> None:
    from honua_sdk.source import AsyncSourceClientProtocol, SourceClientProtocol

    with _client() as client:
        assert isinstance(client, SourceClientProtocol)

    # Plain object missing the surface is rejected.
    class NotAClient:
        pass

    assert not isinstance(NotAClient(), SourceClientProtocol)
    assert not isinstance(NotAClient(), AsyncSourceClientProtocol)


def test_source_stream_routes_through_ogc_features() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "id": "p1", "properties": {"name": "Parcel 1"}}],
            },
        )

    descriptor = _ogc_descriptor()
    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        source = client.source(descriptor)
        items = list(source.stream(Query(pagination=Pagination(limit=1))))

    assert items[0].id == "p1"
    assert items[0].source == "parcels"
    assert items[0].protocol == "ogc-features"
    assert any("/collections/parcels/items" in p for p in seen)


