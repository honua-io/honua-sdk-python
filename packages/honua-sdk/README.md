# honua-sdk

Python data-plane client for [Honua Server](https://github.com/honua-io) --
query geospatial features, geocode addresses, stream data over gRPC, and
convert results to GeoDataFrames. Sync and async clients included.

See the [monorepo README](https://github.com/honua-io/honua-sdk-python) for
full documentation.

## Install

```bash
pip install honua-sdk

# With gRPC support
pip install honua-sdk[grpc]

# With GeoPandas integration
pip install honua-sdk[geopandas]
```

Requires Python 3.11+.

## Quick Example

```python
from honua_sdk import HonuaClient

with HonuaClient("https://your-honua-server.com") as client:
    result = client.query_features("natural-earth", layer_id=0)
    print(f"Found {len(result.get('features', []))} features")
```

## License

Apache-2.0
