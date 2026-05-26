# Authentication

Honua SDK clients support static API keys, static bearer tokens, and refreshable
auth providers.

Static credentials are still available for simple service accounts:

```python
from honua_sdk import HonuaClient

with HonuaClient("https://honua.example", api_key="honua-api-key") as client:
    services = client.list_services()
```

For user or workload tokens that expire, use
`RefreshableBearerTokenProvider`. The SDK calls the provider before each request
and refreshes when the cached token is missing or within the configured refresh
window.

```python
from honua_sdk import BearerToken, HonuaClient, RefreshableBearerTokenProvider


def refresh_token() -> BearerToken:
    # Call your identity provider here.
    payload = issue_token()
    return BearerToken.from_expires_in(
        payload["access_token"],
        payload["expires_in"],
    )


auth = RefreshableBearerTokenProvider(
    refresh_token,
    refresh_window_seconds=120,
)

with HonuaClient("https://honua.example", auth_provider=auth) as client:
    services = client.list_services()
```

The same `auth_provider` argument is accepted by:

- `HonuaClient`
- `AsyncHonuaClient`
- `HonuaGeocodingClient`
- `AsyncHonuaGeocodingClient`
- `HonuaAdminClient`
- `AsyncHonuaAdminClient`

Do not pass both `bearer_token` and `auth_provider`; the SDK rejects that
combination so the source of the `Authorization` header stays unambiguous. A
static `api_key` can be combined with a bearer-token provider only when the
server expects both headers.

## Rotation

`auth_provider` is resolved per request. This lets applications rotate API keys
or bearer tokens without reconstructing the SDK client:

```python
from honua_sdk import CallableAuthProvider, HonuaClient


def current_headers() -> dict[str, str]:
    return {"X-API-Key": current_key_from_secret_manager()}


with HonuaClient("https://honua.example", auth_provider=CallableAuthProvider(current_headers)) as client:
    client.list_services()
```

Auth headers are attached only to the configured base URL authority. When
redirects are enabled, `Authorization` and `X-API-Key` are stripped from
cross-host redirects.

## Revocation

Use `RefreshableBearerTokenProvider.revoke()` when a logout, token revocation,
or incident response flow invalidates the current token. The provider calls the
optional revocation hook with the cached token and clears the token store.

```python
def revoke_token(token: BearerToken) -> None:
    revoke_with_identity_provider(token.access_token)


auth = RefreshableBearerTokenProvider(refresh_token, revoke=revoke_token)
auth.revoke()
```

The next request refreshes a new token through the configured refresh callback.

## Storage

The SDK default token store is in memory only. This avoids writing bearer tokens
to plaintext files and keeps process lifetime explicit.

For persistent tokens, adapt a secure system to the `TokenStore` protocol:

- macOS Keychain, Windows Credential Manager, or libsecret through a package
  such as `keyring`
- a cloud secret manager
- a workload identity cache owned by the deployment platform

Do not store long-lived bearer tokens in source-controlled files, shell history,
or unencrypted dotfiles. Prefer short-lived access tokens plus refresh or
workload identity credentials.

## Failure Modes

- Refresh callback failures propagate before the request is sent. Handle those
  exceptions around SDK calls when the identity provider may be unavailable.
- HTTP `401` or `403` responses are returned as `HonuaHttpError` and are not
  retried by the SDK retry transport.
- Retry remains limited to transient statuses such as `429`, `502`, and `503`.
- If a token is revoked server-side, call `auth.revoke()` or
  `auth.refresh()` before retrying with new credentials.
