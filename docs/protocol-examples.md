# Protocol Examples

These examples cover the public protocol wrappers exposed by `honua_sdk`.
HTTP protocol wrappers return protocol-native payloads:

| Surface | Wrapper | Return shape |
| --- | --- | --- |
| OGC API Features | `client.ogc_features()` | JSON `dict` GeoJSON documents, or `list[dict]` from `items_all()` |
| OGC API Maps | `client.ogc_maps()` | JSON `dict` metadata and `bytes` map images |
| OGC API Tiles | `client.ogc_tiles()` | JSON `dict` metadata and `bytes` tiles |
| OGC API Coverages | `client.ogc_coverages()` | JSON `dict` metadata and `bytes` coverage payloads |
| OGC API Processes | `client.ogc_processes()` | JSON `dict`; `dismiss_job()` returns `None` |
| STAC | `client.stac()` | JSON `dict` STAC Catalog, Collection, Item, and search payloads |
| WFS | `client.wfs()` | XML `str` |
| WMS | `client.wms(service_id)` | XML `str` capabilities and `bytes` map or feature-info payloads |
| WMTS | `client.wmts(service_id)` | XML `str` capabilities and `bytes` tiles |
| OData | `client.odata()` | JSON `dict` resources and XML `str` metadata |
| Geocoding | `client.geocoder()`, `HonuaGeocodingClient` | SDK dataclass models |
| gRPC | `HonuaGrpcClient` | SDK dataclass models |

HTTP protocol wrappers, geocoding, and gRPC also have async clients. Async HTTP
wrappers use the same factory and method names; await methods that issue
requests.

The snippets use these placeholders:

```python
SERVER = "https://your-honua-server.com"
GRPC_TARGET = "your-honua-server.com:50051"
COLLECTION_ID = "parcels"
STAC_COLLECTION_ID = "imagery"
SERVICE_ID = "basemap"
LAYER_ID = 0
BBOX = [-180, -90, 180, 90]
```

## OGC API Features

`ogc_features()` returns GeoJSON-style JSON dictionaries. `items_all()` pages
through item results and returns a list of feature dictionaries.

```python
from honua_sdk import HonuaClient

with HonuaClient(SERVER) as client:
    ogc = client.ogc_features()

    landing = ogc.landing()                         # dict JSON
    collections = ogc.collections()                 # dict JSON
    queryables = ogc.queryables(COLLECTION_ID)      # dict JSON

    parcels = ogc.collection(COLLECTION_ID)
    items = parcels.items(limit=100, bbox=BBOX)     # dict GeoJSON FeatureCollection
    all_items = parcels.items_all(page_size=500, limit=1000)  # list[dict]
    feature = parcels.item("123")                   # dict GeoJSON Feature
```

With `geopandas` installed, OGC FeatureCollection JSON can be converted to a
GeoDataFrame through the SDK helper:

```python
from honua_sdk.geopandas import ogc_features_to_geodataframe

gdf = ogc_features_to_geodataframe(items)
```

Async OGC API Features uses `AsyncHonuaClient`:

```python
from honua_sdk import AsyncHonuaClient

async with AsyncHonuaClient(SERVER) as client:
    parcels = client.ogc_features().collection(COLLECTION_ID)
    items = await parcels.items(limit=100)           # dict GeoJSON FeatureCollection
    all_items = await parcels.items_all(page_size=500, limit=1000)
```

## OGC API Maps

Map metadata is JSON. Rendered maps are returned as raw image bytes.

```python
from honua_sdk import HonuaClient

with HonuaClient(SERVER) as client:
    maps = client.ogc_maps()

    landing = maps.landing()                        # dict JSON
    openapi = maps.openapi()                        # dict JSON
    map_png = maps.collection_map(COLLECTION_ID, bbox=BBOX)
    styled_png = maps.styled_collection_map(COLLECTION_ID, "default", bbox=BBOX)
    tilesets = maps.collection_tilesets(COLLECTION_ID)

print(len(map_png), len(styled_png))                # bytes
```

## OGC API Tiles

Tileset discovery returns JSON. Tile requests return bytes.

```python
from honua_sdk import HonuaClient

with HonuaClient(SERVER) as client:
    tiles = client.ogc_tiles()

    collections = tiles.collections()               # dict JSON
    matrix_sets = tiles.tile_matrix_sets()          # dict JSON
    collection_tilesets = tiles.collection_tilesets(COLLECTION_ID)
    tile_png = tiles.tile(
        "WebMercatorQuad",
        "0",
        0,
        0,
        collection_id=COLLECTION_ID,
    )

print(len(tile_png))                                # bytes
```

## OGC API Coverages

Coverage discovery returns JSON. The coverage payload is returned as bytes, even
when `response_format="json"` is requested, because deployments may return JSON,
TIFF, or another advertised coverage encoding.

```python
from honua_sdk import HonuaClient

with HonuaClient(SERVER) as client:
    coverages = client.ogc_coverages()

    collections = coverages.collections()           # dict JSON
    metadata = coverages.collection("elevation")    # dict JSON
    coverage_json_bytes = coverages.coverage("elevation")
    coverage_tiff = coverages.coverage("elevation", response_format="tiff")

print(len(coverage_json_bytes), len(coverage_tiff)) # bytes
```

## OGC API Processes

Process discovery, execution, job status, and job results return JSON
dictionaries. `dismiss_job()` sends the delete request and returns `None`.

```python
from honua_sdk import HonuaClient

with HonuaClient(SERVER) as client:
    processes = client.ogc_processes()

    available = processes.processes()               # dict JSON
    description = processes.process("buffer")       # dict JSON
    execution = processes.execute("buffer", {"inputs": {"distance": 10}})
    jobs = processes.jobs()                         # dict JSON
    job = processes.job("job-id")                   # dict JSON
    results = processes.job_results("job-id")       # dict JSON
    processes.dismiss_job("job-id")                 # None
```

## STAC

STAC helpers return STAC JSON dictionaries. Item collection and search responses
are GeoJSON-like STAC ItemCollection payloads.

```python
from honua_sdk import HonuaClient

with HonuaClient(SERVER) as client:
    stac = client.stac()

    catalog = stac.catalog()                        # dict STAC Catalog
    collections = stac.collections()                # dict JSON
    collection = stac.collection(STAC_COLLECTION_ID)
    items = stac.items(STAC_COLLECTION_ID, extra_params={"limit": 10})
    item = stac.item(STAC_COLLECTION_ID, "scene-001")
    search = stac.search(json_body={"collections": [STAC_COLLECTION_ID], "limit": 10})
```

With `geopandas` installed, STAC ItemCollection/search JSON can be converted to
a GeoDataFrame:

```python
from honua_sdk.geopandas import stac_items_to_geodataframe

gdf = stac_items_to_geodataframe(search)
```

## WFS

WFS helpers return XML text.

```python
from honua_sdk import HonuaClient

with HonuaClient(SERVER) as client:
    wfs = client.wfs()

    capabilities_xml = wfs.capabilities()           # str XML
    schema_xml = wfs.describe_feature_type(COLLECTION_ID)
    feature_xml = wfs.get_feature(
        type_names=COLLECTION_ID,
        extra_params={"count": 10},
    )
    transaction_body = (
        '<wfs:Transaction service="WFS" version="2.0.0" '
        'xmlns:wfs="http://www.opengis.net/wfs/2.0">...</wfs:Transaction>'
    )
    transaction_xml = wfs.transaction(transaction_body)  # str XML
```

## WMS

WMS capabilities are decoded to XML text. Map and feature-info requests return
bytes because servers can return images, XML, HTML, or another requested format.

```python
from honua_sdk import HonuaClient

with HonuaClient(SERVER) as client:
    wms = client.wms(SERVICE_ID)

    capabilities_xml = wms.capabilities()           # str XML
    map_png = wms.map(
        layers=COLLECTION_ID,
        bbox=BBOX,
        width=512,
        height=512,
        crs="EPSG:4326",
    )
    info = wms.feature_info(
        layers=COLLECTION_ID,
        query_layers=COLLECTION_ID,
        i=256,
        j=256,
        bbox=BBOX,
        width=512,
        height=512,
    )

print(len(map_png), len(info))                      # bytes
```

## WMTS

WMTS capabilities are XML text. Tile requests return bytes.

```python
from honua_sdk import HonuaClient

with HonuaClient(SERVER) as client:
    wmts = client.wmts(SERVICE_ID)

    capabilities_xml = wmts.capabilities()          # str XML
    tile_png = wmts.tile(
        layer=COLLECTION_ID,
        tile_matrix_set="WebMercatorQuad",
        tile_matrix="0",
        tile_row=0,
        tile_col=0,
    )

print(len(tile_png))                                # bytes
```

## OData

OData service, layer, and feature resources return JSON dictionaries. The
`$metadata` endpoint returns XML text.

```python
from honua_sdk import HonuaClient

with HonuaClient(SERVER) as client:
    odata = client.odata()

    service_document = odata.service_document()     # dict JSON
    metadata_xml = odata.metadata()                 # str XML
    layers = odata.layers()                         # dict JSON
    layer = odata.layer(LAYER_ID)                   # dict JSON
    features = odata.features(layer_id=LAYER_ID)    # dict JSON
    feature = odata.feature(LAYER_ID, 123)          # dict JSON
```

## Async HTTP Protocols

`AsyncHonuaClient` exposes the same HTTP protocol factories as `HonuaClient`.
Factory methods are synchronous; methods that issue requests are awaited:

```python
from honua_sdk import AsyncHonuaClient

async with AsyncHonuaClient(SERVER) as client:
    items = await client.ogc_features().collection(COLLECTION_ID).items(limit=100)
    map_png = await client.ogc_maps().collection_map(COLLECTION_ID, bbox=BBOX)
    tile_png = await client.ogc_tiles().tile("WebMercatorQuad", "0", 0, 0, collection_id=COLLECTION_ID)
    coverage = await client.ogc_coverages().coverage("elevation", response_format="tiff")
    processes = await client.ogc_processes().processes()
    stac_items = await client.stac().items(STAC_COLLECTION_ID, extra_params={"limit": 10})
    wfs_xml = await client.wfs().get_feature(type_names=COLLECTION_ID)
    wms_png = await client.wms(SERVICE_ID).map(layers=COLLECTION_ID, bbox=BBOX, width=512, height=512)
    wmts_tile = await client.wmts(SERVICE_ID).tile(
        layer=COLLECTION_ID,
        tile_matrix_set="WebMercatorQuad",
        tile_matrix="0",
        tile_row=0,
        tile_col=0,
    )
    odata_features = await client.odata().features(layer_id=LAYER_ID)
```

## Geocoding

Geocoding returns SDK dataclasses rather than raw dictionaries.

```python
from honua_sdk import HonuaClient, HonuaGeocodingClient

with HonuaClient(SERVER) as client:
    geocoder = client.geocoder()
    suggestions = geocoder.suggest("1600 Pennsylvania")

with HonuaGeocodingClient(SERVER) as geocoder:
    matches = geocoder.forward_geocode("1600 Pennsylvania Ave NW, Washington, DC")
    suggestions = geocoder.suggest("1600 Pennsylvania")
    reverse = geocoder.reverse_geocode(38.8977, -77.0365)

for match in matches:
    print(match.address, match.latitude, match.longitude, match.score)

if reverse is not None:
    print(reverse.address)
```

Async geocoding uses the same method names and can also be reached from
`AsyncHonuaClient.geocoder()`:

```python
from honua_sdk import AsyncHonuaClient, AsyncHonuaGeocodingClient

async with AsyncHonuaClient(SERVER) as client:
    suggestions = await client.geocoder().suggest("1600 Pennsylvania")

async with AsyncHonuaGeocodingClient(SERVER) as geocoder:
    matches = await geocoder.forward_geocode("1600 Pennsylvania Ave NW")
    reverse = await geocoder.reverse_geocode(38.8977, -77.0365)
```

## gRPC

The gRPC client requires the `grpc` extra:

```bash
pip install honua-sdk[grpc]
```

Unary calls return `QueryFeaturesResponse` dataclasses. Streaming calls yield
`FeaturePage` dataclasses.

```python
from honua_sdk.grpc import HonuaGrpcClient, QueryFeaturesRequest, build_grpc_metadata

request = QueryFeaturesRequest(
    service_id="natural-earth",
    layer_id=0,
    out_fields=["objectid", "name"],
    return_geometry=True,
)

metadata = build_grpc_metadata(bearer_token="token")

with HonuaGrpcClient(GRPC_TARGET, insecure=True, metadata=metadata) as grpc_client:
    response = grpc_client.query_features(request)
    print(response.count, len(response.features))   # QueryFeaturesResponse

    for page in grpc_client.query_features_stream(request):
        print(page.is_last_page, len(page.features))  # FeaturePage
```

Async gRPC uses `HonuaGrpcAsyncClient`:

```python
from honua_sdk.grpc import HonuaGrpcAsyncClient, QueryFeaturesRequest

request = QueryFeaturesRequest(service_id="natural-earth", layer_id=0)

async with HonuaGrpcAsyncClient(GRPC_TARGET, insecure=True) as grpc_client:
    response = await grpc_client.query_features(request)

    async for page in grpc_client.query_features_stream(request):
        print(len(page.features))
```

## FeatureServer JSON To GeoDataFrame

The protocol wrappers keep native protocol response shapes. When you query a
GeoServices FeatureServer layer and want an SDK-supported GeoDataFrame
conversion, use `honua_sdk.geopandas`:

```python
from honua_sdk import HonuaClient
from honua_sdk.geopandas import features_to_geodataframe

with HonuaClient(SERVER) as client:
    response = client.query_features("natural-earth", LAYER_ID)

gdf = features_to_geodataframe(response)            # geopandas.GeoDataFrame
```
