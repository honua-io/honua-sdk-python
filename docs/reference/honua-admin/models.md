# honua-admin › Models

The model surface is grouped by admin domain — service catalog and
capabilities, the metadata manifest apply/diff flow, published-layer
and style payloads, and secure-connection management. Each group mirrors
a coherent slice of the admin REST surface, so you typically only touch
one group per workflow.

## Services and capabilities

These types describe what an admin tenant exposes — the catalog of
services, the resolved capability set, the running server version, and
the per-tenant compatibility feature flags that gate optional admin
endpoints.

::: honua_admin.AdminServiceSummary
::: honua_admin.AdminCapabilitiesResponse
::: honua_admin.AdminVersionResponse
::: honua_admin.AdminCompatibilityFeatureFlags

## Metadata manifests

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

## Published layers and styles

These types describe layers exposed by the tenant and the styles
attached to them — useful when reconciling rendering metadata or
auditing the published surface.

::: honua_admin.PublishedLayerSummary
::: honua_admin.LayerStyleResponse

## Secure connections

The secure-connection types cover the lifecycle of upstream credentials:
listing and inspecting connections, testing connectivity, validating
encryption at rest, and rotating tenant keys.

::: honua_admin.SecureConnectionSummary
::: honua_admin.SecureConnectionDetail
::: honua_admin.ConnectionTestResult
::: honua_admin.EncryptionValidationResult
::: honua_admin.KeyRotationResult
