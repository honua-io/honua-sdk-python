# honua-admin

Admin / control-plane client for
[Honua Server](https://github.com/honua-io/honua-server), the multi-protocol
geospatial server behind [Honua](https://honua.io) -- inspect and configure
services, connections, layers, styles, and metadata resources from Python,
and manage server state declaratively through manifests. Sync
(`HonuaAdminClient`) and async (`AsyncHonuaAdminClient`) clients included.

> **Status: Alpha (`0.x`).** APIs may change before 1.0. Breaking changes to
> the public API are gated by a
> [compatibility snapshot](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/compatibility.md),
> and the client checks server compatibility at runtime via
> `check_compatibility()`.

## What it does

- **Compatibility-first**: `check_compatibility()` and
  `get_capability_flags()` read the server's `/api/v1/admin/capabilities`
  contract, so callers can gate control-plane calls on what the connected
  server actually supports (`manifest_apply`, `manifest_dry_run`,
  `metadata_resources`, ...).
- **Services**: `list_services()`, `get_service_settings()`,
  `update_protocols()`, `update_mapserver_settings()`.
- **Layers and data**: `list_layers()`, `publish_layer()`,
  `set_layer_enabled()` / `set_service_layers_enabled()`, and
  `discover_tables()` for source-database table discovery.
- **Connections**: typed CRUD plus `test_connection()` /
  `test_draft_connection()`, `validate_encryption()`, and
  `rotate_encryption_key()`.
- **Styles**: OGC Styles API (`list_styles()`, `get_stylesheet()`,
  `update_style()`) and per-layer styles (`get_layer_style()`,
  `update_layer_style()`).
- **Metadata resources**: typed CRUD over the server's metadata catalog.
- **Manifests as declarative state**: `get_manifest()` exports the server's
  metadata state; `apply_manifest()` applies a manifest with dry-run and
  prune options and idempotency-key support.
- **ArcGIS migration tooling**: `scan_migration_source()` drives the
  server-side migration inventory scanner
  (`POST /api/v1/admin/import/scan`), and the offline
  `scan_arcpy_script()` / `scan_arcpy_source()` helpers inventory ArcPy
  scripts without a server or an `arcpy` install.
- Reuses `honua-sdk`'s retry transport, auth providers, and
  `HonuaHttpError` envelopes, so data-plane and control-plane code share one
  error-handling surface.

## Install

```bash
pip install honua-admin
```

Installs a compatible `honua-sdk` automatically (shared HTTP, auth, and
error utilities). Requires Python 3.11+.

The supported server baseline and release gate policy are documented in the
monorepo
[compatibility guide](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/compatibility.md).

## Minimal Example

```python
from honua_admin import HonuaAdminClient

with HonuaAdminClient("https://your-honua-server.com", api_key="honua-api-key") as admin:
    compatibility = admin.check_compatibility()
    if not compatibility.supported:
        raise RuntimeError("; ".join(compatibility.reasons))

    services = admin.list_services()
    for svc in services:
        print(f"{svc.service_name}: {svc.layer_count} layers")
```

Always use the `with HonuaAdminClient(...) as admin:` form -- it guarantees
the underlying `httpx` connections are returned to the pool on exit, even when
a request raises. The same `auth_provider=` argument the data-plane client
accepts (e.g. `RefreshableBearerTokenProvider`) works here unchanged.

### Async

```python
from honua_admin import AsyncHonuaAdminClient

async with AsyncHonuaAdminClient(
    "https://your-honua-server.com",
    api_key="honua-api-key",
) as admin:
    compatibility = await admin.check_compatibility()
    if not compatibility.supported:
        raise RuntimeError("; ".join(compatibility.reasons))

    services = await admin.list_services()
    for svc in services:
        print(f"{svc.service_name}: {svc.layer_count} layers")
```

The async client mirrors the sync method surface (CRUD helpers, manifest
operations, migration scans, capability checks) and shares the same retry
transport, auth providers, and `HonuaHttpError` envelopes.

## Documentation

Rendered docs site:
[honua-io.github.io/honua-sdk-python](https://honua-io.github.io/honua-sdk-python/latest/).
Platform docs: [honua.io](https://honua.io) and
[honua.gitbook.io/honuaio](https://honua.gitbook.io/honuaio/).

- [Compatibility policy](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/compatibility.md)
- [Authentication](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/auth.md)
- [Monorepo README](https://github.com/honua-io/honua-sdk-python) -- install matrix and package overview

Related: [honua-sdk](https://github.com/honua-io/honua-sdk-python/tree/trunk/packages/honua-sdk)
(the data-plane client this package builds on),
[honua-sdk-js](https://github.com/honua-io/honua-sdk-js) (JS/TS SDKs + MCP server),
[honua-sdk-dotnet](https://github.com/honua-io/honua-sdk-dotnet) (.NET SDKs).

## License

Apache-2.0
