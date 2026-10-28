---
type: guide
title: "Develop and test the Python SDKs"
description: "Contributor reference: optional test lanes, code layout rules, lint and type settings, the live-server conformance lane, and the release declarations."
resource: "https://github.com/honua-io/honua-sdk-python/blob/trunk/.github/workflows/ci.yml"
tags: [python, development, testing, contributor]
---
# Develop and test the Python SDKs

The everyday commands (install, lint, type-check, test, coverage gate,
compatibility gate, sync-client regeneration) are at the top of the repository
`AGENTS.md`. This page holds the rest: the opt-in lanes, the layout rules, and
the policies behind the gates.

## Packages

Three independently installable packages live under `packages/`:

| Package | PyPI name | License | Role |
|---------|-----------|---------|------|
| `packages/honua-sdk` | `honua-sdk` | Apache-2.0 | Data-plane client: feature queries, geocoding, multi-protocol clients, gRPC streaming, GeoPandas integration. Optional extras `grpc` and `geopandas`. |
| `packages/honua-admin` | `honua-admin` | Apache-2.0 | Control-plane client: services, connections, layers, styles, metadata, manifests, compatibility checks. Depends on `honua-sdk`. |
| `packages/honua-gp` | `honua-gp` | Proprietary (do-not-upload) | Closed-source geoprocessing compatibility layer for teams migrating from ArcGIS `arcpy`. Import `honua_gp`. It has its own lenient lint/test gate, not the workspace-root strict rules. |

The packages build with Hatchling and release through release-please
(`python-sdk-v*` / `python-admin-v*` tags publish to PyPI). Docs are
mkdocs-material (`mkdocs.yml`, `docs/`).

## Opt-in and secondary lanes

```bash
# Build a package wheel + sdist the way CI does (run inside the package dir)
python -m build --no-isolation      # in packages/honua-sdk or packages/honua-admin
twine check dist/*

# Security audit
python -m pip_audit --strict

# Staging smoke suite (needs HONUA_BASE_URL; HONUA_ENABLE_WRITE_SMOKE=true adds the write roundtrip)
python3 -m pytest tests/integration -q --run-integration \
  -m "integration and staging and smoke"

# Release smoke against an installed build (needs HONUA_BASE_URL)
python3 scripts/release_smoke.py

# honua-gp lane (.github/workflows/honua-gp-eval.yml)
python -m pytest packages/honua-gp/tests -q
python -m honua_gp._cli --help
```

Integration tests are opt-in: they need `--run-integration`, the markers
`integration`/`staging`/`smoke`, and `HONUA_BASE_URL`. The same flag gates
`tests/conformance` (marker `conformance`).

## Code layout rules

- `honua_sdk/async_client.py` is the hand-written source of truth;
  `honua_sdk/client.py` is generated from it by `scripts/gen_sync.py`. The
  same holds for `honua_admin/_async_client.py` and `_client.py`. Edit the
  async module, run `python scripts/gen_sync.py` (needs ruff on `PATH`), and
  commit both. CI's lint job runs `--check` and fails on drift.
- The canonical query path is `client.source(SourceDescriptor(...))`, which
  returns a `Source` facade (`source.py`) with `query`, `query_all`, `stream`,
  `apply_edits` and `protocol`, returning normalized `Result`/`QueryFeature`
  (`models/`). `client.query(...)` and `query_features(...)` remain for
  one-liners.
- `honua_sdk/grpc/_generated/` holds generated protobuf shims, excluded from
  lint, type-check and coverage. `honua_sdk/geopandas.py` sits behind the
  `geopandas` extra and is omitted from the coverage gate.
- Use the canonical cross-SDK protocol ids (`geoservices-feature-service`,
  `ogc-features`, `stac`, `odata`). Aliases are normalized at runtime by
  `honua_sdk.normalize_protocol` / `PROTOCOL_ALIASES`.

## Lint, type and coverage settings

- ruff: line length 120, target py311, rule set `E,F,I,UP,B,SIM,RUF,TID,PL,S`.
  Generated gRPC code and `packages/honua-gp` are excluded. Many narrow
  per-file ignores exist; match the existing pattern rather than widening a
  rule globally.
- UP037 (quoted forward references) stays on in package source so the
  compatibility-gate public-API snapshot is stable. Do not strip the quotes.
- mypy runs with `strict = true` workspace-wide (`[tool.mypy]` in the root
  `pyproject.toml`). Every def in `honua_sdk` and `honua_admin` is annotated.
  A narrow override exempts the generated protobuf stubs
  (`honua_sdk.grpc._generated.*`) from `disallow_untyped_defs`,
  `disallow_untyped_calls`, `disallow_any_generics` and
  `disallow_subclassing_any`, because regeneration would erase any added
  annotations.
- Coverage: combined `--cov-fail-under=94`, plus per-package floors of 93
  (`honua_sdk` across `tests/`, `honua_admin` across `tests/admin`).

## Live-server conformance lane

`.github/workflows/conformance.yml`, `tests/conformance` and
`scripts/_conformance.py` form a lane that blocks PRs and pushes to trunk. It
runs the shared geospatial-grpc conformance fixtures against a pinned
honua-server image through the `httpx` clients.

- The server image is pinned by digest in `HONUA_SERVER_IMAGE` in the
  workflow; the job summary records the resolved digest and revision.
- The fixture version is pinned in `conformance/FIXTURES_VERSION` (1:1 with a
  `geospatial.v1` schema release) and must equal the workflow's
  `CONFORMANCE_FIXTURES_VERSION`.
- Trunk pushes and ad-hoc dispatches certify the published wheel pinned in the
  workflow's `HONUA_SDK_PUBLIC_*` env. A governed nightly dispatch
  (`nightly_dispatch_id`) instead runs the trunk harness against the package it
  names: `sdk_package`, `sdk_package_version`, `sdk_package_digest` and
  `sdk_source_sha` are then required with `requirements_ref` and
  `requirements_revision`, the downloaded wheel must match the digest, and each
  receipt identity records `harness_commit` (the run's `GITHUB_SHA`) beside
  `producer_source_sha` (the published source).
- The seeded server must run with `ASPNETCORE_ENVIRONMENT=Development`. The
  client-compat seed activates the metadata-v2 snapshot for
  `default`/`Development`/`Test`, not `Production`.

Run it locally against a seeded server:

```bash
conformance/fetch-fixtures.sh --version "$(cat conformance/FIXTURES_VERSION)" \
  --repo honua-io/geospatial-grpc \
  --dest "./conformance-fixtures-$(cat conformance/FIXTURES_VERSION)"
HONUA_CONFORMANCE_FIXTURES_DIR="./conformance-fixtures-$(cat conformance/FIXTURES_VERSION)" \
  python3 -m pytest tests/conformance -q --run-integration \
  -m "integration and conformance" -rsxX
```

### Known gaps

`build_cases()` in `scripts/_conformance.py` is the case registry. A case tied
to a tracked nightly server gap carries `known_gap_issue` and runs as
`xfail(strict=False)`; the reasons live in `KNOWN_SERVER_GAPS`. Today:

- `temporal_query` (honua-server#2643): the client-compat seed does not set
  `timeInfo` on `test_service` layer 0, so `time=` queries return 400 as
  non-time-aware (by design, honua-server#1444) instead of filtering. A seed
  gap, not a query-engine bug.
- `replica_sync_surface` (honua-server#2645): the seed hardcodes an empty
  Metadata-V2 `options` object for `test_service`, so the Sync capability
  can never surface for the seeded layer. Also a seed gap.

When a fix lands, clear the case's `known_gap_issue` to make it required. The
earlier references honua-server#1166 and #1167 were re-verified on 2026-07-10
and were never the cause of these failures; #1237 and #1238 were re-verified
the same day and their cases now pass.

An `xfail` case is non-enforcing for its whole body, so a `known_gap` case
must never also carry unrelated required assertions.
`feature_query_envelope` and `ogc_features_items` therefore hold only the core
read contract and are always required. The JSONB attribute projection check
(the honua-server#1238 class of regression) lives in its own cases,
`feature_query_jsonb_projection` and `ogc_features_items_jsonb_projection`.
New drift in a required case must fail the lane; never add a blanket
`continue-on-error`.

## No custom-code submission or backend selection

The SDK exposes no way to submit custom (operator-authored) geoprocessing code
and no way to select an execution backend; backend selection is server
configuration. Per honua-server ADR-0063, untrusted custom GP code runs only
in an isolated AWS Batch container, never on-host. The ArcPy/ModelBuilder
codemod (`honua_sdk.migration`) translates recognized tools only to built-in
server processes (`EXECUTABLE_PROCESS_IDS`) and emits anything else as
`manual-review`. `honua gp inspect` and `honua gp logs` read the canonical job
diagnostics projection in this SDK; every other `honua gp` command delegates
to a separately installed trusted local devkit and never changes server
submission or workload routing. `tests/test_custom_code_batch_only_policy.py`
fails if such a surface appears.

## Release declarations

- `release/component-versions.json` is read by the honua-release nightly
  resolver at the published source commit. Update it in the same PR as any
  contract or schema version bump; it takes effect with the next
  release-please publication.
- `release/sdk-capability-baseline.json` (`honua.sdk-capability-baseline/v1`,
  defined by honua-release `schemas/sdk-capability-baseline.v1.schema.json`
  and `docs/SDK-SERVER-BASELINE-RULE.md`) declares the honua-server
  capabilities this repository requires and the `minimumServerVersion`
  derived from them. The resolver reads it at the source revision of every
  published PyPI package (`honua-sdk` and `honua-admin`) and refuses the
  component when it is missing, invalid, or when those revisions disagree on
  `minimumServerVersion`. It takes effect only after a release-please
  publication contains it. Every required capability must be a key in
  honua-server `docs/gis/data/capability-keys.v1.json`, and `capabilities`
  must hold exactly one introduction entry per required capability. Add or
  remove a required capability in the same PR that starts or stops depending
  on it.
