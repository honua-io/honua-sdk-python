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

## Migration Source Scans

The migration toolkit starts with `POST /api/v1/admin/import/scan`, which
returns a raw `MigrationSourceInventoryArtifact` rather than the usual admin
`success/data` response envelope.

```python
from honua_admin import HonuaAdminClient, MigrationInventoryScanRequest

request = MigrationInventoryScanRequest(
    source_kind="geoserver",
    source_url="https://example.com/geoserver/rest",
    username="operator",
    password="secret",
    include_style_content=True,
)

with HonuaAdminClient("https://your-honua-server.com", api_key="key") as admin:
    inventory = admin.scan_migration_source(request)

if inventory.scan_completeness.status == "failed":
    raise RuntimeError("; ".join(inventory.scan_completeness.warnings))
```

Use `export_json=True` to request the server's indented JSON attachment form
while still receiving a typed `MigrationSourceInventoryArtifact`. A `200 OK`
response means the server produced an inventory artifact; callers should use
`scan_completeness.status` and `overall_compatibility.level` as the planning
gate before import or cutover decisions.

### ArcPy Script Scans

The local ArcPy scanner produces a deterministic inventory artifact without
executing the script:

```python
from honua_admin import scan_arcpy_script

inventory = scan_arcpy_script("legacy_gp_tool.py")
payload = inventory.to_dict()
```

The `honua-arcpy-scan legacy_gp_tool.py` console command emits the same artifact
as JSON for manifest planning and later runner work.

## License

Apache-2.0
