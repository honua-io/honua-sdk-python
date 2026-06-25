# Changelog

This monorepo uses [release-please](https://github.com/googleapis/release-please) with per-package changelogs:

- [honua-sdk](packages/honua-sdk/CHANGELOG.md)
- [honua-admin](packages/honua-admin/CHANGELOG.md)

Auto-managed by release-please; do not hand-edit per-package files.

## What's new across the platform

The 0.1.x line introduces a unified, type-safe query facade -- `client.source(SourceDescriptor(...)).query(Query(...))` -- that returns a single typed `Result[QueryFeature]` shape across FeatureServer, OGC Features, STAC, and OData. Protocol-specific clients (`client.feature_server`, `client.stac`, `client.ogc_features`, ...) remain available as escape hatches. The control plane (`honua-admin`) ships sync + async clients in lockstep with the data plane, sharing the same auth, retry, and error machinery via the public `honua_sdk.http` surface.

## Unreleased

Track in-flight changes in the open release-please PR:
- [honua-sdk](https://github.com/honua-io/honua-sdk-python/pulls?q=is%3Apr+is%3Aopen+label%3A%22autorelease%3A+pending%22+%22python-sdk%22)
- [honua-admin](https://github.com/honua-io/honua-sdk-python/pulls?q=is%3Apr+is%3Aopen+label%3A%22autorelease%3A+pending%22+%22python-admin%22)

Breaking changes in this line are gated by the public-API compatibility snapshot in [compatibility/public-api.json](compatibility/public-api.json) and surface in the per-package CHANGELOGs below.

## Migration timeline

- **0.0.x baseline** — Initial public alpha. Protocol-specific clients
  (`client.query_features`, `client.feature_server`) and raw-dict response
  shapes. No `Source` facade; protocol selection was per-method.
- **0.0.x → 0.1.x** — Introduced the unified `Source` / `Query` / `Result` facade.
  Protocol-specific calls (`client.query_features`, `client.query_feature_set`,
  `client.feature_server(...).query_pages`) still work but are documented as
  "legacy / compact form" in code examples; new code should prefer
  `client.source(SourceDescriptor(...)).query(Query(...))` which returns a
  typed `Result[QueryFeature]` across every protocol. The `Query.where` field
  no longer routes silently to CQL `filter` on OGC/STAC endpoints — pass
  `cql_filter=` or set `where_as_cql=True` to opt in.
- **0.1.x → 0.2.x (planned)** — Sync/async client modules continue to converge
  around the shared `_endpoints.py` / `_retry_core.py` machinery. The
  `bearer_token=` constructor kwarg (deprecated in 0.1.x, see below) is
  scheduled for removal. No other public-API removals are scheduled; new
  helpers will be additive.

### Before / after — breaking-change migrations

Each migration below pairs the old call shape with the supported replacement.
The legacy forms still work where noted, but new code should prefer the
right-hand column.

**1. Raw GeoServices `.attributes` → canonical GeoJSON `.properties`**

The protocol-specific `query_features` path returns raw GeoServices features
whose field bag lives under `.attributes`. The canonical `Source` facade
returns `Result[QueryFeature]`, where each feature exposes GeoJSON-shaped
`.properties` (and `.geometry`) uniformly across every protocol.

```python
# Before -- raw GeoServices feature, fields under ``attributes``
raw = client.query_features("svc", 0, where="status = 'active'")
for feature in raw["features"]:
    name = feature["attributes"]["name"]
    geom = feature.get("geometry")

# After -- canonical QueryFeature, fields under ``properties``
from honua_sdk import Query, SourceDescriptor, SourceLocator

descriptor = SourceDescriptor(
    id="svc",
    protocol="geoservices-feature-service",
    locator=SourceLocator(service_id="svc", layer_id=0),
)
result = client.source(descriptor).query(Query(where="status = 'active'"))
for feature in result.features:
    name = feature.properties["name"]
    geom = feature.geometry  # GeoJSON-shaped, may be ``None``
```

**2. `client.query_features(...)` → `client.source(...).query(...)`**

`query_features` is a FeatureServer-only call returning a raw `dict`. The
`Source` facade is protocol-agnostic and returns a typed `Result[QueryFeature]`
the same way for FeatureServer, OGC Features, STAC, and OData. The
protocol-specific call still works as a legacy escape hatch.

```python
# Before -- protocol-specific, FeatureServer-only, raw dict
raw = client.query_features(
    "svc", 0, where="1=1", out_fields=["id", "name"], return_geometry=True
)

# After -- canonical facade, typed Result across every protocol
from honua_sdk import Query, SourceDescriptor, SourceLocator

descriptor = SourceDescriptor(
    id="svc",
    protocol="geoservices-feature-service",
    locator=SourceLocator(service_id="svc", layer_id=0),
)
result = client.source(descriptor).query(
    Query(where="1=1", out_fields=["id", "name"], return_geometry=True)
)
# Or iterate lazily across pages instead of materializing one response:
for feature in client.source(descriptor).iter_query(Query(where="1=1")):
    ...
```

**3. `bearer_token=` → `auth_provider=StaticAuthProvider(...)`**

The `bearer_token=` constructor kwarg is deprecated in 0.1.x (emits a
`DeprecationWarning`) and removed in 0.2.x, collapsing auth onto the single
`auth_provider=` parameter (mirroring stripe-python / openai-python). Wrap the
token in `StaticAuthProvider`, which is exported from `honua_sdk.auth`.

```python
# Before -- deprecated, emits DeprecationWarning (removed in 0.2.x)
from honua_sdk import HonuaClient

client = HonuaClient("https://your-honua-server.com", bearer_token=token)

# After -- single auth parameter, no warning
from honua_sdk import HonuaClient
from honua_sdk.auth import StaticAuthProvider

client = HonuaClient(
    "https://your-honua-server.com",
    auth_provider=StaticAuthProvider({"Authorization": f"Bearer {token}"}),
)
```

Per-release notes live in [packages/honua-sdk/CHANGELOG.md](packages/honua-sdk/CHANGELOG.md) and [packages/honua-admin/CHANGELOG.md](packages/honua-admin/CHANGELOG.md), maintained by release-please.
