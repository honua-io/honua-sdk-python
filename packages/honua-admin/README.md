# honua-admin

Admin / control-plane client for [Honua Server](https://github.com/honua-io) --
manage services, connections, layers, styles, metadata resources, and manifests.
Sync and async clients included.

See the [monorepo README](https://github.com/honua-io/honua-sdk-python) for
full documentation.

## Install

```bash
pip install honua-admin
```

This automatically installs `honua-sdk` as a dependency (shared HTTP utilities
and error types).

Requires Python 3.11+.

The server compatibility baseline and release gate policy are documented in the
monorepo [compatibility guide](../../docs/compatibility.md).

## Quick Example

```python
from honua_admin import HonuaAdminClient

with HonuaAdminClient("https://your-honua-server.com", api_key="key") as admin:
    compatibility = admin.check_compatibility()
    if not compatibility.supported:
        raise RuntimeError("; ".join(compatibility.reasons))

    services = admin.list_services()
    for svc in services:
        print(f"{svc.service_name}: {svc.layer_count} layers")
```

Refreshable SDK auth providers are also accepted:

```python
from honua_admin import HonuaAdminClient
from honua_sdk import RefreshableBearerTokenProvider

auth = RefreshableBearerTokenProvider(lambda: {"access_token": "token", "expires_in": 3600})

with HonuaAdminClient("https://your-honua-server.com", auth_provider=auth) as admin:
    services = admin.list_services()
```

## License

Apache-2.0
