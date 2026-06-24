# honua-admin › Errors

The admin client raises the same exception hierarchy as the data-plane
SDK — there is no admin-specific exception surface. Catch
``HonuaError`` for any failure, or one of its subclasses
(``HonuaHttpError``/``HonuaAuthError``/``HonuaRateLimitError`` for HTTP
failures; ``HonuaTransportError``/``HonuaTimeoutError`` for transport
failures) when you need finer-grained handling. See the
[honua-sdk error reference](../honua-sdk/errors.md) for the full
documentation of:

- [`HonuaError`](../honua-sdk/errors.md#honua_sdk.errors.HonuaError)
- [`HonuaHttpError`](../honua-sdk/errors.md#honua_sdk.errors.HonuaHttpError)
- [`HonuaAuthError`](../honua-sdk/errors.md#honua_sdk.errors.HonuaAuthError)
- [`HonuaRateLimitError`](../honua-sdk/errors.md#honua_sdk.errors.HonuaRateLimitError)
- [`HonuaTransportError`](../honua-sdk/errors.md#honua_sdk.errors.HonuaTransportError)
- [`HonuaTimeoutError`](../honua-sdk/errors.md#honua_sdk.errors.HonuaTimeoutError)
