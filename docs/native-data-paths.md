---
type: guide
title: "Start with gRPC and cloud-native files"
description: "Use gRPC for authenticated live data and edits, and PMTiles, GeoParquet and COG through the CDN for public and read-heavy data."
---
# Start with gRPC and cloud-native files

Build new Honua applications and finish customer migrations on the native path:
**gRPC for authenticated, live and edited data**, plus **cloud-native files for
public and read-heavy data**. The shared protobuf contract lives in
[geospatial-grpc](https://github.com/honua-io/geospatial-grpc).
This follows the founder direction recorded in [ADR-0087](https://github.com/honua-io/honua-server/pull/7555).

## Live feature queries in Python

Install the published SDK with its gRPC extra:

```bash
pip install "honua-sdk[grpc]"
```

Set `HONUA_GRPC_TARGET` to the deployment's native gRPC host and port (for
example `grpc.example.com:443`, without an `https://` prefix). Set
`HONUA_ACCESS_TOKEN`, `HONUA_SERVICE_ID` and `HONUA_LAYER_ID` for your authorized
layer. This uses TLS; `insecure=True` is only appropriate for explicit local h2c
development, not a remote authenticated deployment.

```python
import os
import grpc
from honua_sdk.grpc import HonuaGrpcClient, QueryFeaturesRequest, build_grpc_metadata

with HonuaGrpcClient(
    os.environ["HONUA_GRPC_TARGET"],
    credentials=grpc.ssl_channel_credentials(),
    metadata=build_grpc_metadata(bearer_token=os.environ["HONUA_ACCESS_TOKEN"]),
) as client:
    page = client.query_features(QueryFeaturesRequest(
        service_id=os.environ["HONUA_SERVICE_ID"],
        layer_id=int(os.environ["HONUA_LAYER_ID"]),
        result_record_count=10,
        return_geometry=True,
    ))
    print(page.features)
```

`HonuaGrpcAsyncClient` provides async queries and streaming. For long-running
sessions pass a refreshable `auth_provider` to the client; the metadata above is
a static token snapshot. The public gRPC wrappers **do not yet expose native
feature edits**. REST `apply_edits` remains a compatibility workflow, not a
native implementation; track the rc.3 gap in
[#400](https://github.com/honua-io/honua-sdk-python/issues/400).

## Browser setup: gRPC-Web

Browsers use gRPC-Web rather than a native HTTP/2 gRPC channel. The JavaScript
SDK uses the Connect libraries with the **gRPC-Web transport**; this does not
require or imply support for the separate Connect protocol.

```bash
npm install @honua/sdk-js @bufbuild/protobuf@^2 @connectrpc/connect@^2 @connectrpc/connect-web@^2
```

**Current browser packaging limitation:** the JS SDK loads its optional Connect
peers and internal gRPC modules dynamically with variable imports. Installing the
peers alone is insufficient in ordinary Vite browser bundles: those imports are
left for runtime resolution. The configuration below describes the client API,
not a verified drop-in Vite application. Before deploying, verify that your build
and module loader resolve those modules in the browser; otherwise use a backend
with the native SDK until browser packaging is supported.

Configure the deployment's HTTPS gRPC-Web endpoint and allow the application's
origin, authorization headers and gRPC-Web response headers in its CORS policy.
Use a short-lived user access token from your sign-in flow; never ship an admin
key in a browser bundle. Replace these deployment-specific values before running:

```ts doc-test=compile
import { HonuaClient } from "@honua/sdk-js/honua";

const client = new HonuaClient({
  baseUrl: "https://your-honua-server.example",
  transport: "grpc-web",
  bearerToken: "<short-lived-user-access-token>",
});
const page = await client.queryFeatures({
  serviceId: "parcels",
  layerId: 0,
  where: "1=1",
  outFields: ["*"],
  returnGeometry: true,
  resultRecordCount: 10,
});
console.log(page.features);
```

The endpoint must actually expose gRPC-Web; an ordinary REST endpoint or an
HTTP/2-only native gRPC listener is insufficient. Configure token renewal through
the SDK's auth provider for a long-running session. Setting `transport` explicitly
matters: the JavaScript client's default remains REST for existing applications.

## Public files and private snapshots

Ordinary gRPC calls are POST requests and are not CDN-cacheable. Publish public,
read-heavy data as versioned files, then use a format-aware reader that requests
only the needed byte ranges through the CDN:

| Data | Native file | Reader |
| --- | --- | --- |
| Map tiles | PMTiles | PMTiles-capable map renderer |
| Vector extracts and analytics | GeoParquet | GeoParquet / Arrow tooling |
| Raster imagery | Cloud Optimized GeoTIFF (COG) | COG-aware raster reader |

Configure object storage and the CDN to support HTTP range requests (including
`206 Partial Content` and `Content-Range`), preserve the file bytes, and allow
browser CORS access where needed. A plain full-file download is still possible;
partial reads depend on the reader and the file's layout.

For private files, authorize the user first and return a short-lived **signed
URL** scoped to the permitted object. The reader uses that URL for its range
requests. Keep private responses out of shared public caches unless the CDN
enforces the same authorization; configure signing, cache keys and expiry with
the deployment operator. Refresh the signed URL when it expires, including
during multi-request reads, and do not put it in logs or source control.

**Reader limitation:** the current JS SDK COG integration rejects URLs containing
query parameters, including typical presigned URLs. Its COG example therefore
cannot read those private objects directly. Choose a COG reader that supports
your signed URLs; do not remove their signatures or make private data public to
work around this restriction.

After edits, regenerate the affected files and publish a new immutable version
(for example a generation-specific object key). Update the application's catalog
or manifest only after publication succeeds; acquire a new signed URL for that
version. A signed URL controls access, not freshness. An old file does not change
when the live layer changes. Keep gRPC as the source for current authorized
reads and writes while a new snapshot is being built.

Use GeoParquet-capable analytics tools such as GeoPandas for vectors and
COG-aware tools such as Rasterio for imagery; use a PMTiles-capable viewer for
tiles. These are format readers, not additional methods on `HonuaGrpcClient`.
The SDK's GeoPandas and raster extras do not imply that every operation performs
bounded HTTP range reads; choose and configure a reader for that workload.

## Compatibility during coexistence

OGC API and GeoServices REST clients remain supported for third-party tools and
existing Esri clients that cannot yet migrate. Their examples demonstrate
**compatibility**, not the target architecture for a new Honua application.
Keep them during coexistence, then move application data access to gRPC and
cloud-native files. Control-plane administration and capabilities outside the
feature data path retain their own documented contracts.
