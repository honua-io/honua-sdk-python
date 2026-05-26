# honua-admin

Admin / control-plane client for [Honua Server](https://github.com/honua-io) --
manage services, connections, layers, styles, metadata resources, and
manifests. Sync (`HonuaAdminClient`) and async (`AsyncHonuaAdminClient`)
clients included.

See the [monorepo README](https://github.com/honua-io/honua-sdk-python) for
the full documentation index and release notes.

## Highlights

- Typed compatibility check (`check_compatibility()`) against the server's
  `/api/v1/admin/capabilities` contract before issuing control-plane calls.
- Capability flag accessor for feature toggles such as `manifest_apply`,
  `manifest_dry_run`, and `metadata_resources`.
- Service/layer/style/connection/metadata-resource CRUD helpers backed by typed
  request and response dataclasses.
- Manifest export/apply/dry-run/prune helpers for declarative server state.
- Reuses `honua-sdk`'s retry transport, auth providers, and `HonuaHttpError`
  envelopes for a single error-handling surface.

## Install

```bash
pip install honua-admin
```

Installs `honua-sdk` automatically (shared HTTP, auth, and error utilities).
Requires Python 3.11+.

The server compatibility baseline and release gate policy are documented in
the monorepo
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
operations, capability checks) and shares the same retry transport, auth
providers, and `HonuaHttpError` envelopes.

## Documentation

- [Compatibility policy](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/compatibility.md)
- [Authentication](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/auth.md)
- [Monorepo README](https://github.com/honua-io/honua-sdk-python) -- install matrix and package overview

## License

Apache-2.0
