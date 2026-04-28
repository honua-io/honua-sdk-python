"""Protocol client examples for Honua Server.

Replace the constants below with IDs from your deployment. HTTP protocol
wrappers return JSON dicts, XML strings, or raw bytes. Geocoding and gRPC return
SDK dataclass models. Async HTTP wrappers use the same factory and method names.
"""

from __future__ import annotations

from typing import Any

from honua_sdk import (
    AsyncHonuaClient,
    AsyncHonuaGeocodingClient,
    HonuaClient,
    HonuaGeocodingClient,
)

SERVER = "https://your-honua-server.com"
GRPC_TARGET = "your-honua-server.com:50051"
COLLECTION_ID = "parcels"
STAC_COLLECTION_ID = "imagery"
SERVICE_ID = "basemap"
FEATURE_SERVICE_ID = "natural-earth"
LAYER_ID = 0
BBOX = [-180, -90, 180, 90]


def sync_http_protocol_examples() -> None:
    """Show the sync HTTP protocol wrappers and their response shapes."""
    with HonuaClient(SERVER) as client:
        capabilities = client.capabilities()
        print(f"Server version: {capabilities.server_version or 'unknown'}")
        print(f"STAC advertised: {capabilities.supports('stac')}")

        ogc_features = client.ogc_features().collection(COLLECTION_ID)
        items: dict[str, Any] = ogc_features.items(limit=100, bbox=BBOX)
        all_items: list[dict[str, Any]] = ogc_features.items_all(page_size=500, limit=1000)
        feature: dict[str, Any] = ogc_features.item("123")

        ogc_maps = client.ogc_maps()
        maps_landing: dict[str, Any] = ogc_maps.landing()
        map_png: bytes = ogc_maps.collection_map(COLLECTION_ID, bbox=BBOX)
        map_tilesets: dict[str, Any] = ogc_maps.collection_tilesets(COLLECTION_ID)

        ogc_tiles = client.ogc_tiles()
        tile_matrix_sets: dict[str, Any] = ogc_tiles.tile_matrix_sets()
        tile_png: bytes = ogc_tiles.tile(
            "WebMercatorQuad",
            "0",
            0,
            0,
            collection_id=COLLECTION_ID,
        )

        coverages = client.ogc_coverages()
        coverage_collections: dict[str, Any] = coverages.collections()
        coverage_tiff: bytes = coverages.coverage("elevation", response_format="tiff")

        processes = client.ogc_processes()
        process_list: dict[str, Any] = processes.processes()
        process_description: dict[str, Any] = processes.process("buffer")

        stac = client.stac()
        stac_catalog: dict[str, Any] = stac.catalog()
        stac_items: dict[str, Any] = stac.items(STAC_COLLECTION_ID, extra_params={"limit": 10})
        stac_search: dict[str, Any] = stac.search(json_body={"collections": [STAC_COLLECTION_ID], "limit": 10})

        wfs = client.wfs()
        wfs_capabilities_xml: str = wfs.capabilities()
        wfs_feature_xml: str = wfs.get_feature(type_names=COLLECTION_ID, extra_params={"count": 10})

        wms = client.wms(SERVICE_ID)
        wms_capabilities_xml: str = wms.capabilities()
        wms_map_png: bytes = wms.map(layers=COLLECTION_ID, bbox=BBOX, width=512, height=512)

        wmts = client.wmts(SERVICE_ID)
        wmts_capabilities_xml: str = wmts.capabilities()
        wmts_tile_png: bytes = wmts.tile(
            layer=COLLECTION_ID,
            tile_matrix_set="WebMercatorQuad",
            tile_matrix="0",
            tile_row=0,
            tile_col=0,
        )

        odata = client.odata()
        odata_service: dict[str, Any] = odata.service_document()
        odata_metadata_xml: str = odata.metadata()
        odata_features: dict[str, Any] = odata.features(layer_id=LAYER_ID)

        print(f"OGC Features JSON items: {len(items.get('features', []))}")
        print(f"OGC Features paged feature dicts: {len(all_items)}; item keys: {sorted(feature)}")
        print(f"OGC Maps JSON keys: {sorted(maps_landing)}; tilesets keys: {sorted(map_tilesets)}")
        print(f"OGC map bytes: {len(map_png)}")
        print(f"OGC Tiles JSON keys: {sorted(tile_matrix_sets)}; tile bytes: {len(tile_png)}")
        print(f"OGC Coverage collections keys: {sorted(coverage_collections)}; bytes: {len(coverage_tiff)}")
        print(f"OGC Processes keys: {sorted(process_list)}; process keys: {sorted(process_description)}")
        print(f"STAC catalog keys: {sorted(stac_catalog)}; items: {len(stac_items.get('features', []))}")
        print(f"STAC search items: {len(stac_search.get('features', []))}")
        print(f"WFS XML chars: {len(wfs_capabilities_xml)}; feature XML chars: {len(wfs_feature_xml)}")
        print(f"WMS XML chars: {len(wms_capabilities_xml)}; map bytes: {len(wms_map_png)}")
        print(f"WMTS XML chars: {len(wmts_capabilities_xml)}; tile bytes: {len(wmts_tile_png)}")
        print(f"OData JSON keys: {sorted(odata_service)}; metadata XML chars: {len(odata_metadata_xml)}")
        print(f"OData feature rows: {len(odata_features.get('value', []))}")


def geocoding_examples() -> None:
    """Show geocoding dataclass responses."""
    with HonuaClient(SERVER) as client:
        suggestions = client.geocoder().suggest("1600 Pennsylvania")

    with HonuaGeocodingClient(SERVER) as geocoder:
        matches = geocoder.forward_geocode("1600 Pennsylvania Ave NW, Washington, DC")
        reverse = geocoder.reverse_geocode(38.8977, -77.0365)

    print(f"GeocodeResult models: {len(matches)}")
    print(f"GeocodeSuggestion models: {len(suggestions)}")
    if reverse is not None:
        print(f"ReverseGeocodeResult model: {reverse.address}")


def geopandas_shape_example() -> None:
    """Convert protocol JSON to GeoDataFrames when geopandas is installed."""
    from honua_sdk.geopandas import (
        features_to_geodataframe,
        ogc_features_to_geodataframe,
        stac_items_to_geodataframe,
    )

    with HonuaClient(SERVER) as client:
        feature_server_response = client.query_features(FEATURE_SERVICE_ID, LAYER_ID)
        ogc_response = client.ogc_features().collection(COLLECTION_ID).items(limit=100)
        stac_response = client.stac().items(STAC_COLLECTION_ID, extra_params={"limit": 10})

    feature_server_gdf = features_to_geodataframe(feature_server_response)
    ogc_gdf = ogc_features_to_geodataframe(ogc_response)
    stac_gdf = stac_items_to_geodataframe(stac_response)
    print(f"FeatureServer GeoDataFrame rows: {len(feature_server_gdf)}")
    print(f"OGC GeoDataFrame rows: {len(ogc_gdf)}")
    print(f"STAC GeoDataFrame rows: {len(stac_gdf)}")


def grpc_examples() -> None:
    """Show gRPC model responses. Requires `pip install honua-sdk[grpc]`."""
    from honua_sdk.grpc import HonuaGrpcClient, QueryFeaturesRequest, build_grpc_metadata

    request = QueryFeaturesRequest(
        service_id=FEATURE_SERVICE_ID,
        layer_id=LAYER_ID,
        out_fields=["objectid", "name"],
        return_geometry=True,
    )

    metadata = build_grpc_metadata(bearer_token="replace-with-token")

    with HonuaGrpcClient(GRPC_TARGET, insecure=True, metadata=metadata) as grpc_client:
        response = grpc_client.query_features(request)
        print(f"QueryFeaturesResponse model features: {len(response.features)}")

        for page in grpc_client.query_features_stream(request):
            print(f"FeaturePage model features: {len(page.features)}")


async def async_supported_protocol_examples() -> None:
    """Show async examples for HTTP protocols, geocoding, and gRPC."""
    async with AsyncHonuaClient(SERVER) as client:
        parcels = client.ogc_features().collection(COLLECTION_ID)
        items = await parcels.items(limit=100)
        all_items = await parcels.items_all(page_size=500, limit=1000)

        map_png = await client.ogc_maps().collection_map(COLLECTION_ID, bbox=BBOX)
        tile_png = await client.ogc_tiles().tile("WebMercatorQuad", "0", 0, 0, collection_id=COLLECTION_ID)
        coverage_tiff = await client.ogc_coverages().coverage("elevation", response_format="tiff")
        processes = await client.ogc_processes().processes()
        stac_items = await client.stac().items(STAC_COLLECTION_ID, extra_params={"limit": 10})
        wfs_xml = await client.wfs().get_feature(type_names=COLLECTION_ID, extra_params={"count": 10})
        wms_map = await client.wms(SERVICE_ID).map(layers=COLLECTION_ID, bbox=BBOX, width=512, height=512)
        wmts_tile = await client.wmts(SERVICE_ID).tile(
            layer=COLLECTION_ID,
            tile_matrix_set="WebMercatorQuad",
            tile_matrix="0",
            tile_row=0,
            tile_col=0,
        )
        odata_features = await client.odata().features(layer_id=LAYER_ID)
        suggestions = await client.geocoder().suggest("1600 Pennsylvania")

        print(f"Async OGC Features JSON items: {len(items.get('features', []))}")
        print(f"Async OGC Features paged feature dicts: {len(all_items)}")
        print(f"Async OGC map bytes: {len(map_png)}; tile bytes: {len(tile_png)}")
        print(f"Async coverage bytes: {len(coverage_tiff)}; process keys: {sorted(processes)}")
        print(f"Async STAC items: {len(stac_items.get('features', []))}")
        print(f"Async WFS XML chars: {len(wfs_xml)}; WMS bytes: {len(wms_map)}; WMTS bytes: {len(wmts_tile)}")
        print(f"Async OData feature rows: {len(odata_features.get('value', []))}")
        print(f"Async geocoder suggestions via client factory: {len(suggestions)}")

    async with AsyncHonuaGeocodingClient(SERVER) as geocoder:
        matches = await geocoder.forward_geocode("1600 Pennsylvania Ave NW")
        reverse = await geocoder.reverse_geocode(38.8977, -77.0365)
        print(f"Async GeocodeResult models: {len(matches)}")
        if reverse is not None:
            print(f"Async ReverseGeocodeResult model: {reverse.address}")

    from honua_sdk.grpc import HonuaGrpcAsyncClient, QueryFeaturesRequest

    request = QueryFeaturesRequest(service_id=FEATURE_SERVICE_ID, layer_id=LAYER_ID)
    async with HonuaGrpcAsyncClient(GRPC_TARGET, insecure=True) as grpc_client:
        response = await grpc_client.query_features(request)
        print(f"Async QueryFeaturesResponse model features: {len(response.features)}")

        async for page in grpc_client.query_features_stream(request):
            print(f"Async FeaturePage model features: {len(page.features)}")


def main() -> None:
    sync_http_protocol_examples()
    geocoding_examples()


if __name__ == "__main__":
    main()
