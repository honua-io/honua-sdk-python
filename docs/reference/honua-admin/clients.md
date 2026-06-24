# honua-admin › Clients

The admin SDK ships sync and async clients with parity to the data-plane
SDK: pick [`HonuaAdminClient`][honua_admin.HonuaAdminClient] for scripts
and CLIs, and
[`AsyncHonuaAdminClient`][honua_admin.AsyncHonuaAdminClient] for async
services. Both clients share the data-plane configuration model
(auth, retries, timeouts, ``with_options(...)``); see the
[honua-sdk core client model](../../core-client.md) for the conceptual
overview that applies to both packages.

```python
from honua_admin import HonuaAdminClient

with HonuaAdminClient("https://admin.your-honua-server.com", api_key="...") as admin:
    services = admin.list_services()
```

**See also**: [honua-sdk Clients](../honua-sdk/clients.md) for the data-plane
counterpart that shares the same configuration model, and
[Core client model](../../core-client.md) for cross-package `with_options(...)`
semantics.

::: honua_admin.HonuaAdminClient
::: honua_admin.AsyncHonuaAdminClient
