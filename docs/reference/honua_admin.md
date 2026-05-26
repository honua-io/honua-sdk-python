# honua-admin Reference

## Clients

The admin SDK ships sync and async clients with parity to the data-plane
SDK: pick [`HonuaAdminClient`][honua_admin.HonuaAdminClient] for scripts
and CLIs, and
[`AsyncHonuaAdminClient`][honua_admin.AsyncHonuaAdminClient] for async
services. Both clients share the data-plane configuration model
(auth, retries, timeouts, ``with_options(...)``); see the
[honua-sdk core client model](../core-client.md) for the conceptual
overview that applies to both packages.

```python
from honua_admin import HonuaAdminClient

with HonuaAdminClient("https://admin.your-honua-server.com", api_key="...") as admin:
    services = admin.list_services()
```

**See also**: [honua-sdk Clients](honua_sdk.md#clients) for the data-plane
counterpart that shares the same configuration model, and
[Core client model](../core-client.md) for cross-package `with_options(...)`
semantics.

::: honua_admin.HonuaAdminClient
::: honua_admin.AsyncHonuaAdminClient

## Models

The model surface is grouped by admin domain — service catalog and
capabilities, the metadata manifest apply/diff flow, published-layer
and style payloads, and secure-connection management. Each group mirrors
a coherent slice of the admin REST surface, so you typically only touch
one group per workflow.

### Services and capabilities

These types describe what an admin tenant exposes — the catalog of
services, the resolved capability set, the running server version, and
the per-tenant compatibility feature flags that gate optional admin
endpoints.

::: honua_admin.AdminServiceSummary
::: honua_admin.AdminCapabilitiesResponse
::: honua_admin.AdminVersionResponse
::: honua_admin.AdminCompatibilityFeatureFlags

### Metadata manifests

The manifest types power the declarative apply/diff workflow:
[`MetadataManifest`][honua_admin.MetadataManifest] is the input bundle,
[`ManifestApplyResult`][honua_admin.ManifestApplyResult] (with its
per-resource [`ManifestApplyEntry`][honua_admin.ManifestApplyEntry] rows
and aggregate [`ManifestApplySummary`][honua_admin.ManifestApplySummary])
captures the server's reconciliation outcome. The
[`MetadataResource`][honua_admin.MetadataResource] /
[`MetadataResourceIdentifier`][honua_admin.MetadataResourceIdentifier] /
[`ResourceMetadata`][honua_admin.ResourceMetadata] triple is the
canonical resource shape consumed and emitted by the apply API.

::: honua_admin.MetadataManifest
::: honua_admin.ManifestApplyResult
::: honua_admin.ManifestApplyEntry
::: honua_admin.ManifestApplySummary
::: honua_admin.MetadataResource
::: honua_admin.MetadataResourceIdentifier
::: honua_admin.ResourceMetadata

### Published layers and styles

These types describe layers exposed by the tenant and the styles
attached to them — useful when reconciling rendering metadata or
auditing the published surface.

::: honua_admin.PublishedLayerSummary
::: honua_admin.LayerStyleResponse

### Secure connections

The secure-connection types cover the lifecycle of upstream credentials:
listing and inspecting connections, testing connectivity, validating
encryption at rest, and rotating tenant keys.

::: honua_admin.SecureConnectionSummary
::: honua_admin.SecureConnectionDetail
::: honua_admin.ConnectionTestResult
::: honua_admin.EncryptionValidationResult
::: honua_admin.KeyRotationResult

## Errors

The admin client raises the same exception hierarchy as the data-plane
SDK — there is no admin-specific exception surface. Catch
``HonuaError`` for any failure, or one of its subclasses
(``HonuaHttpError``/``HonuaAuthError``/``HonuaRateLimitError`` for HTTP
failures; ``HonuaTransportError``/``HonuaTimeoutError`` for transport
failures) when you need finer-grained handling. See the
[honua-sdk error reference](honua_sdk.md#errors) for the full
documentation of:

- [`HonuaError`](honua_sdk.md#honua_sdk.errors.HonuaError)
- [`HonuaHttpError`](honua_sdk.md#honua_sdk.errors.HonuaHttpError)
- [`HonuaAuthError`](honua_sdk.md#honua_sdk.errors.HonuaAuthError)
- [`HonuaRateLimitError`](honua_sdk.md#honua_sdk.errors.HonuaRateLimitError)
- [`HonuaTransportError`](honua_sdk.md#honua_sdk.errors.HonuaTransportError)
- [`HonuaTimeoutError`](honua_sdk.md#honua_sdk.errors.HonuaTimeoutError)
