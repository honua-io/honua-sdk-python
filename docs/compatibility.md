# SDK Compatibility Policy

The Python SDK compatibility gate protects two contracts:

- The supported Honua Server compatibility contract returned by
  `/api/v1/admin/capabilities`.
- The public Python API exported by `honua_sdk`, `honua_sdk.grpc`, and
  `honua_admin`.

## Server Compatibility Baseline

Release builds support Honua Server versions that meet all of these conditions:

- `serverVersion` parses to at least `2026.3.0`.
- `releaseChannel` is `preview` or a later channel (`beta`, `rc`, `stable`, or
  `lts`).
- `controlPlaneApi.major` is `1`.
- `controlPlaneApi.basePath` is `/api/v1/admin`.
- The server returns the nested `compatibility` object from
  `/api/v1/admin/capabilities`.

Matching control-plane APIs marked `deprecated` remain supported, but
`check_compatibility()` returns a warning so applications can plan migrations
before the API major is removed.

The machine-readable matrix lives in
[`compatibility/server-matrix.json`](../compatibility/server-matrix.json). It
contains supported and unsupported server examples and is validated in CI by:

```bash
python scripts/compatibility_gate.py
```

Update the matrix in the same PR as any SDK baseline change. The gate also
checks that the JSON baseline matches the constants exported by `honua_admin`.

## Public API Snapshot

The compatibility gate snapshots exported names, constructor and method
signatures, enum members, and dataclass fields for the public SDK modules. This
catches accidental breaking changes such as removed exports, renamed methods,
or changed required parameters before they merge.

When a public API change is intentional:

1. Review whether it is additive, deprecating, or breaking.
2. Document the behavior in the PR and changelog entry for the affected package.
3. Regenerate the snapshot:

   ```bash
   python scripts/compatibility_gate.py --update-api-snapshot
   ```

4. Commit the updated `compatibility/public-api.json` with the code change.

## First-Party Internal Utility Boundary

`honua_sdk._shared` is the semipublic import boundary for first-party packages
that need SDK HTTP/auth/error/retry behavior. `honua-admin` imports shared
request helpers, auth types, HTTP errors, and retry transports from this module
instead of depending on lower-level implementation modules such as
`honua_sdk._http`, `honua_sdk._retry`, or `honua_sdk._async_retry`.

This boundary is intentionally excluded from the root public API snapshot, but
changes to exports used by `honua-admin` should be treated as cross-package
compatibility changes and covered by targeted admin tests.

## CI And Release Blocking

Pull request CI runs the compatibility gate as its own job. The publish workflow
also runs the same gate before package build/upload steps, so a failed server
matrix or public API drift blocks release tags and manual publish runs.
