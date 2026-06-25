# honua-sdk › Clients

Two top-level clients share the same surface area and configuration model.
Use [`HonuaClient`][honua_sdk.HonuaClient] for synchronous scripts, notebooks,
and tools backed by ``httpx`` — and reach for
[`AsyncHonuaClient`][honua_sdk.AsyncHonuaClient] in async services
(FastAPI, ``asyncio`` workers) where you need concurrent I/O. Both clients
expose the same canonical ``query``/``iter_query`` dispatcher and the same
protocol-specific escape hatches; see
[Core client model](../../core-client.md) for the conceptual map of options,
retries, and ``with_options(...)`` semantics that apply to both.

The geocoding clients ([`HonuaGeocodingClient`][honua_sdk.HonuaGeocodingClient]
and [`AsyncHonuaGeocodingClient`][honua_sdk.AsyncHonuaGeocodingClient]) are
dedicated thin wrappers for the geocoding endpoint and keep the same
configuration knobs.

```python
from honua_sdk import HonuaClient

with HonuaClient("https://your-honua-server.com", timeout=30.0) as client:
    services = client.list_services()
```

**See also**: [Source facade](source-facade.md) for the canonical query path,
[Core client model](../../core-client.md) for `with_options(...)` semantics,
and [Retries and timeouts](../../retries-and-timeouts.md) for the retry policy,
`Retry-After` handling, and per-call / `with_options(...)` timeout behaviour.

::: honua_sdk.HonuaClient
::: honua_sdk.AsyncHonuaClient
::: honua_sdk.HonuaGeocodingClient
::: honua_sdk.AsyncHonuaGeocodingClient
