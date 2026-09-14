---
type: reference
title: "SDK compatibility policy"
description: "The two contracts the compatibility gate protects, and what counts as a breaking change to either."
resource: "https://github.com/honua-io/honua-sdk-python/blob/trunk/compatibility/sdk-coverage.v1.json"
tags: [compatibility, versioning, policy]
---
# SDK Compatibility Policy

The Python SDK compatibility gate protects two contracts:

- The supported Honua Server compatibility contract returned by
  `/api/v1/admin/capabilities`.
- The public Python API exported by `honua_sdk`, `honua_sdk.grpc`, and
  `honua_admin`.

## Server Compatibility Baseline

Release builds support Honua Server versions that meet all of these conditions:

- `serverVersion` parses to at least `1.0.0`. Honua Server versions are
  `<year>.<release>.<patch>` SemVer triples (the 2026.1 release reports
  `2026.1.1`), may carry a prerelease suffix (`-rc.1`, `-nightly.N`) or build
  metadata (`+<sha>`), and older builds reported `1.0.0+<sha>`. The major tracks
  the year rather than compatibility, so there is one floor for every release
  line, the same `1.0.0` the JS SDK uses; the control-plane API major below is
  the breaking-change signal.
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
[`compatibility/server-matrix.json`](https://github.com/honua-io/honua-sdk-python/blob/trunk/compatibility/server-matrix.json). It
contains supported and unsupported server examples and is validated in CI by:

```bash
python scripts/compatibility_gate.py
```

Update the matrix in the same PR as any SDK baseline change. The gate also
checks that the JSON baseline matches the constants exported by `honua_admin`.

The matrix includes the exact stable `1.0.0+32809f114c36c951b00beb5fe07a3c7082867909`
identity reported in [#219](https://github.com/honua-io/honua-sdk-python/issues/219)
and the `2026.1.1` compatibility contract a 2026.1 server image returns. Both
synchronous and asynchronous admin clients test those identities through the
capabilities response parser, with independent rejection cases for an incompatible
API major, base path, or release channel. These deterministic transport fixtures
protect the runtime policy; they do not certify a deployed release candidate.

`tests/conformance/test_live_admin_contract.py` runs the same check against a
live server when `HONUA_CONTRACT_LIVE_URL` and an admin
`HONUA_CONTRACT_LIVE_API_KEY` are set:

```bash
HONUA_CONTRACT_LIVE_URL=http://localhost:8080 HONUA_CONTRACT_LIVE_API_KEY=<admin key> \
  python3 -m pytest tests/conformance/test_live_admin_contract.py --run-integration -q
```

Published `honua-admin` 0.1.8 predates this correction and rejects both
identities. The corrected baseline must be included in the admin package selected
by the release train; source-level compatibility does not update an installed wheel.

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

## Capability Coverage Snapshot

A separate artifact, [`compatibility/sdk-coverage.v1.json`](https://github.com/honua-io/honua-sdk-python/blob/trunk/compatibility/sdk-coverage.v1.json),
tracks this SDK's per-capability coverage against honua-server's canonical
capability key vocabulary for the cross-product capability matrix. See
[SDK Capability Coverage](sdk-coverage.md) for its schema, the honesty
rules it enforces, and how the drift gate works.
