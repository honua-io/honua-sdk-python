# SDK Capability Coverage Snapshot

`compatibility/sdk-coverage.v1.json` is this SDK's producer snapshot for
honua-io/honua-server's cross-product capability matrix
(honua-server#2892 / #2893, honua-sdk-python#182). It maps this SDK's
client source to the canonical, server-owned capability key vocabulary so
[honua-evidence](https://github.com/honua-io/honua-evidence) can join every
producer's coverage into one aggregate view.

This document is the schema reference required by the repo's compatibility
docs convention (see [Compatibility](compatibility.md)); the generator that
produces and validates the snapshot is
[`scripts/gen_sdk_coverage.py`](https://github.com/honua-io/honua-sdk-python/blob/trunk/scripts/gen_sdk_coverage.py).

## Rules

These mirror the "no padding, no invented claims" rules used for the
site claims ledger and other producer snapshots in this ecosystem:

- **Consume, never copy.** The canonical capability key vocabulary is
  owned by honua-server
  ([`docs/gis/data/capability-keys.v1.json`](https://github.com/honua-io/honua-server/blob/trunk/docs/gis/data/capability-keys.v1.json)).
  This repository never redefines or forks that vocabulary -- it only
  validates that every key in its own snapshot exists in the upstream
  list.
- **`partial` requires a note.** Any capability marked `partial` must
  carry a `note` explaining exactly where SDK coverage stops.
- **Never pad.** A capability this SDK's client source does not touch is
  omitted from the snapshot entirely -- there is no `status: "none"`
  entry to skim past.
- **Honest `sinceVersion`.** This SDK is a source preview: neither
  `honua-sdk` nor `honua-admin` has been published to PyPI yet (see the
  repo README/AGENTS.md "Status: alpha"). Every entry's `sinceVersion` is
  the literal string `"unreleased (source preview; not yet published to
  PyPI)"` rather than an invented release number.

## Schema

```json
{
  "schemaVersion": "sdk-coverage.v1",
  "package": "honua-sdk-python (packages/honua-sdk + packages/honua-admin)",
  "generator": "scripts/gen_sdk_coverage.py",
  "keyListPolicy": "<prose describing the consume-never-copy policy>",
  "capabilities": [
    {
      "key": "serve.geoservices-featureserver",
      "status": "covered",
      "sinceVersion": "unreleased (source preview; not yet published to PyPI)",
      "entrypoints": [
        "honua_sdk.protocols.GeoServicesFeatureServerClient",
        "honua_sdk.protocols.AsyncGeoServicesFeatureServerClient",
        "honua_sdk.AsyncHonuaClient.feature_server"
      ]
    },
    {
      "key": "serve.odata",
      "status": "partial",
      "sinceVersion": "unreleased (source preview; not yet published to PyPI)",
      "entrypoints": ["honua_sdk.protocols.ODataClient", "honua_sdk.protocols.AsyncODataClient"],
      "note": "Read/query only ...; no create/update/delete entity-set operations are implemented."
    }
  ]
}
```

| Field | Type | Meaning |
|---|---|---|
| `key` | string | A canonical capability key from honua-server's published key list. |
| `status` | `"covered"` \| `"partial"` | `covered`: the SDK implements a full client surface for this capability. `partial`: implemented but incomplete -- see `note`. |
| `sinceVersion` | string | Honest release marker (see above). |
| `entrypoints` | string[] | Dotted paths to the main classes/functions/methods that implement the capability, e.g. `honua_sdk.protocols.StacClient`. Verified to actually resolve against the installed packages every time the gate runs (see below). |
| `note` | string | Required when `status` is `"partial"`; explains exactly where coverage stops. Absent for `"covered"` entries. |

## How coverage is decided

This is a *client* SDK, so "covered" means the SDK has a client surface
that talks to the corresponding server capability -- not that the
capability is implemented server-side. The mapping in
`scripts/gen_sdk_coverage.py::COVERAGE` was built by reading the SDK
source (`packages/honua-sdk`, `packages/honua-admin`) against every one of
honua-server's published capability keys, one at a time, during
honua-sdk-python#182. Server-side-only capabilities this SDK's clients
have no surface for at all (identity/SSO protocols, alert/channel
delivery, disaster recovery, printing/staticmap rendering, most
`analytics.*` named processes, plugin SDKs, data import jobs, etc.) are
omitted rather than marked `none`.

## Drift protection

Three independent checks run every time the gate executes
(`python scripts/gen_sdk_coverage.py`), and all three are exercised by
`tests/test_sdk_coverage_gate.py`:

1. **Key validation.** Every key in `COVERAGE` must exist in the
   canonical key list. An unknown key (typo, or a key renamed/removed
   upstream) fails the gate.
2. **Entrypoint resolution.** Every dotted path in every entry's
   `entrypoints` is resolved via `importlib` + `getattr` against the
   *installed* `honua_sdk` / `honua_admin` packages. If a referenced
   class, function, or method is renamed or removed, the gate fails until
   `COVERAGE` is updated in the same PR -- this is the real "coverage
   changed without a snapshot update" drift signal from #182's
   acceptance criteria.
3. **Snapshot currency.** The committed `compatibility/sdk-coverage.v1.json`
   must match `collect_snapshot()`'s current output byte-for-byte.

```bash
# Run the gate (used in CI; also runnable locally, offline by default)
python scripts/gen_sdk_coverage.py

# Rewrite the snapshot after an intentional coverage change
python scripts/gen_sdk_coverage.py --update-snapshot

# Re-pin the offline key-list fixture after an upstream vocabulary change
python scripts/gen_sdk_coverage.py --refresh-key-list-fixture
```

## Key-list resolution (fixture vs. live)

`scripts/gen_sdk_coverage.py` resolves the canonical key list in this
order, mirroring the `KEY_LIST_URL` pattern used by
[honua-samples' `validate-manifests.mjs`](https://github.com/honua-io/honua-samples/blob/trunk/scripts/validate-manifests.mjs):

1. `HONUA_CAPABILITY_KEY_LIST_URL` env var, if set -- fetched live. CI
   sets this on every run (PR and trunk push) so the gate always
   validates against honua-server's current published vocabulary, not a
   potentially-stale local copy.
2. `compatibility/capability-keys.fixture.json` -- a pinned,
   point-in-time offline copy, used whenever the env var is unset (local
   dev, offline work, or the unit test suite). This keeps
   `tests/test_sdk_coverage_gate.py` network-free and deterministic.

The generated snapshot itself never embeds which source validated it --
`collect_snapshot()` is a pure function of `COVERAGE` plus live
introspection, so the committed file is identical either way.

## CI and release blocking

Pull request and trunk-push CI run the coverage gate as part of the
`compatibility` job, with `HONUA_CAPABILITY_KEY_LIST_URL` set to
honua-server's published raw URL. On `trunk` pushes only, the validated
`compatibility/sdk-coverage.v1.json` is also uploaded as a build artifact
for honua-evidence's aggregate run to consume.
