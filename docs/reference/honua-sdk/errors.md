# honua-sdk › Errors

The SDK raises a focused hierarchy rooted at
[`HonuaError`][honua_sdk.errors.HonuaError]. HTTP-shaped failures derive
from [`HonuaHttpError`][honua_sdk.errors.HonuaHttpError], with
[`HonuaAuthError`][honua_sdk.errors.HonuaAuthError] (401/403) and
[`HonuaRateLimitError`][honua_sdk.errors.HonuaRateLimitError] (429) as
the two specialized HTTP subclasses worth catching individually.
Transport-level failures derive from
[`HonuaTransportError`][honua_sdk.errors.HonuaTransportError], with
[`HonuaTimeoutError`][honua_sdk.errors.HonuaTimeoutError] for explicit
deadline misses.

Catch ``HonuaError`` to handle any SDK failure; catch the narrower
subclasses when you want retry or surfacing logic tuned to a specific
failure mode. See
[Quickstart › Common errors](../../quickstart.md#common-errors) for
worked examples.

```python
from honua_sdk import HonuaRateLimitError, HonuaTimeoutError

try:
    result = client.query_features("svc", 0)
except HonuaRateLimitError as exc:
    retry_after = exc.retry_after
```

**See also**: [Quickstart › Common errors](../../quickstart.md#common-errors)
for retry recipes, and [Clients](clients.md) for how `timeout=` and
`with_options(timeout=...)` interact with `HonuaTimeoutError`.

::: honua_sdk.errors.HonuaError
::: honua_sdk.errors.HonuaHttpError
::: honua_sdk.errors.HonuaAuthError
::: honua_sdk.errors.HonuaRateLimitError
::: honua_sdk.errors.HonuaTransportError
::: honua_sdk.errors.HonuaTimeoutError
