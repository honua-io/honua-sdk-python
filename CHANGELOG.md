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

  *Querying — before/after:*

  ```python
  # Before (0.0.x): per-protocol method, raw-dict response
  fc = client.query_features("parcels", where="state = 'HI'", out_fields="*")
  for feature in fc["features"]:
      name = feature["attributes"]["NAME"]

  # After (0.1.x): unified Source facade, typed Result[QueryFeature]
  result = client.source(SourceDescriptor("parcels")).query(
      Query(where="state = 'HI'", out_fields=["*"])
  )
  for feature in result.features:
      name = feature.properties["NAME"]
  ```

  *Feature attributes — `.attributes` → `.properties`:*

  ```python
  # Before (0.0.x): GeoJSON-style raw dict, ArcGIS `attributes` key
  value = feature["attributes"]["POP2020"]

  # After (0.1.x): normalized QueryFeature, `.properties` everywhere
  value = feature.properties["POP2020"]
  ```

- **0.1.x → 0.2.x (planned)** — Sync/async client modules continue to converge
  around the shared `_endpoints.py` / `_retry_core.py` machinery. The
  `bearer_token=` constructor argument (deprecated in 0.1.x, which emits a
  `DeprecationWarning`) is scheduled for removal; migrate to
  `auth_provider=`:

  ```python
  # Before (0.1.x, deprecated): bearer_token= kwarg
  client = HonuaClient(base_url, bearer_token=token)

  # After (0.2.x): explicit auth provider (works today, 0.1.x onward)
  from honua_sdk.auth import StaticAuthProvider

  client = HonuaClient(
      base_url,
      auth_provider=StaticAuthProvider({"Authorization": f"Bearer {token}"}),
  )
  ```

  No other public-API removals are scheduled; new helpers will be additive.

Per-release notes live in [packages/honua-sdk/CHANGELOG.md](packages/honua-sdk/CHANGELOG.md) and [packages/honua-admin/CHANGELOG.md](packages/honua-admin/CHANGELOG.md), maintained by release-please.
