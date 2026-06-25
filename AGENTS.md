# AGENTS.md

## Overview

Monorepo for the **Honua Python client libraries** — clients for a Honua
geospatial server. Three independently installable packages live under
`packages/`:

| Package | PyPI name | License | Description |
|---------|-----------|---------|-------------|
| `packages/honua-sdk` | `honua-sdk` | Apache-2.0 | Data-plane client: feature queries, geocoding, multi-protocol clients (GeoServices/OGC/STAC/OData/WFS/WMS/WMTS/scenes), gRPC streaming, GeoPandas integration. |
| `packages/honua-admin` | `honua-admin` | Apache-2.0 | Control-plane client: services, connections, layers, styles, metadata, manifests, compatibility checks. Depends on `honua-sdk`. |
| `packages/honua-arcpy` | `honua-arcpy` | Proprietary (do-not-upload) | Closed-source arcpy compatibility shim. Linted/tested under its own lenient gate, not the workspace-root strict rules. |

Status: alpha (`0.x`); APIs may change before 1.0.

## Tech Stack

- **Language:** Python, **requires 3.11+**. CI matrix tests 3.11, 3.12, 3.13.
- **Build backend:** Hatchling (`hatch build`) per package.
- **Core runtime dep:** `httpx>=0.27`. Optional extras on `honua-sdk`:
  `grpc` (`grpcio`, `protobuf`), `geopandas` (`geopandas`, `shapely`).
- **Tooling:** ruff (lint + import sort), mypy (type-check), pytest +
  pytest-cov (test + coverage), pip-audit (security), twine (dist check).
- **Docs:** mkdocs-material (`mkdocs.yml`, `docs/`).
- **Release:** release-please (`python-sdk-v*` / `python-admin-v*` tags → PyPI).

## Setup

The repo root `pyproject.toml` is **NOT installable** — it only holds shared
tool config (ruff/mypy/pytest/coverage). Install the per-package directories:

```bash
# Editable install of both packages with all extras (typical dev setup)
pip install -e "packages/honua-sdk[grpc,geopandas]"
pip install -e "packages/honua-admin"

# Test/dev tooling
pip install pytest pytest-cov ruff mypy
```

## Commands

All commands run from the repo root unless noted. These are copied from CI
(`.github/workflows/ci.yml`) and README; do not invent variants.

```bash
# Lint (workspace-root strict ruleset; honua-arcpy is excluded)
ruff check .

# Type-check
python -m mypy packages/honua-sdk/honua_sdk packages/honua-admin/honua_admin

# Full deterministic local test suite
python3 -m pytest tests/ -q

# Tests with the combined coverage gate (mirrors CI; fails under 94%)
python -m pytest tests/ -q --tb=short \
  --cov=honua_sdk --cov=honua_admin \
  --cov-report=term-missing --cov-fail-under=94

# Compatibility / public-API snapshot gate
python scripts/compatibility_gate.py

# Regenerate the synchronous clients from their async source-of-truth.
# honua_sdk/client.py and honua_admin/_client.py are GENERATED from
# async_client.py / _async_client.py by this script and committed; never
# hand-edit them. Edit the async module, then regenerate. `--check` (run in
# CI's lint job) fails if a committed sync file is stale. Requires ruff on PATH.
python scripts/gen_sync.py            # rewrite the committed sync files
python scripts/gen_sync.py --check    # verify they are up to date

# Build a package wheel + sdist (run inside the package dir)
hatch build                         # in packages/honua-sdk or packages/honua-admin
twine check dist/*

# Security audit
python -m pip_audit --strict

# Opt-in staging smoke suite (needs HONUA_BASE_URL)
python3 -m pytest tests/integration -q --run-integration \
  -m "integration and staging and smoke"

# Live-server conformance lane: shared geospatial-grpc fixtures vs a pinned
# honua-server:nightly via the httpx clients (blocking on PR/push to trunk).
# Fetch the pinned shared fixtures, point a live target at the seeded server,
# then run the suite (needs HONUA_BASE_URL; opt-in via --run-integration).
conformance/fetch-fixtures.sh --version "$(cat conformance/FIXTURES_VERSION)" \
  --repo honua-io/geospatial-grpc \
  --dest "./conformance-fixtures-$(cat conformance/FIXTURES_VERSION)"
HONUA_CONFORMANCE_FIXTURES_DIR="./conformance-fixtures-$(cat conformance/FIXTURES_VERSION)" \
  python3 -m pytest tests/conformance -q --run-integration \
  -m "integration and conformance" -rsxX

# Release smoke against an installed build (needs HONUA_BASE_URL)
python3 scripts/release_smoke.py
```

honua-arcpy has a separate lane (`.github/workflows/honua-arcpy-eval.yml`):
`python -m pytest packages/honua-arcpy/tests -q` and a CLI
(`python -m honua_arcpy._cli ...`).

## Architecture

- **`honua_sdk`** — data plane. Public entry points: `HonuaClient` /
  `AsyncHonuaClient` (`client.py`, `async_client.py`). **`async_client.py` is the
  hand-written source of truth; `client.py` is GENERATED from it** by
  `scripts/gen_sync.py` (same for `honua_admin._async_client` → `_client`). Edit
  the async module and run `python scripts/gen_sync.py`; never hand-edit the
  generated sync file (its header says so, and CI's `--check` step fails on
  drift). The canonical query path
  is `client.source(SourceDescriptor(...))` → a `Source` facade
  (`source.py`) exposing `query`/`query_all`/`stream`/`apply_edits`/`protocol`,
  returning normalized `Result` / `QueryFeature` (`models.py`). Compact helpers
  `client.query(...)` / `query_features(...)` remain for one-liners.
  - `protocols/` — per-protocol clients (geoservices, ogc_extras, stac, odata,
    wfs, wms, wmts, scenes) over a shared `_base.py`.
  - `ogc.py` — OGC API Features facade. `geocoding.py` / `async_geocoding.py`.
  - `grpc/` — `HonuaGrpcClient` for streaming; `_generated/` holds codegen'd
    protobuf shims (excluded from lint/type/coverage).
  - `geopandas.py` — `features_to_geodataframe` / `geodataframe_to_features`
    (behind the optional `geopandas` extra; omitted from coverage gate).
  - `_http.py`, `_retry*.py` — transport + automatic retry on 429/502/503 with
    exponential backoff and `Retry-After` support.
  - `auth.py`, `errors.py`, `migration/arcpy.py`, `_endpoints.py`.
- **`honua_admin`** — control plane: `HonuaAdminClient` /
  `_async_client.py`, `_models.py`, `_endpoints.py`, `_arcpy_scanner.py`
  (AST-walking inventory scanner).
- **`scripts/`** — `compatibility_gate.py`, `gen_sync.py` (async→sync client
  codegen), `release_smoke.py`, `backlog_review.py`, `validate_publish_tag.py`,
  `generate_proto.sh`.

## Directory Layout

```
packages/honua-sdk/honua_sdk/    # data-plane package source
packages/honua-admin/honua_admin/# control-plane package source
packages/honua-arcpy/            # proprietary arcpy shim (own gate)
tests/                           # shared test suite (admin/, grpc_sdk/,
                                 #   integration/, fixtures/, conftest.py)
scripts/                         # gates, smoke, release helpers
docs/                            # mkdocs sources
examples/                        # runnable examples (ETL, FastAPI, demos)
.github/workflows/               # ci.yml, release-please, publish, staging, docs
pyproject.toml                   # shared tool config ONLY (not installable)
.coveragerc                      # coverage omit/exclude rules
```

## Conventions & Gotchas

- **Do not run `pip install .` / `-e .` at the repo root** — root has no
  `[build-system]`/`[project]`; install per-package dirs instead.
- **Coverage gates are real**: combined `--cov-fail-under=94`, plus per-package
  floors of 93 (`honua_sdk` across `tests/`, `honua_admin` across `tests/admin`).
- **ruff**: line-length 120, target py311, selects `E,F,I,UP,B,SIM,RUF,TID,PL,S`.
  Generated grpc code and `packages/honua-arcpy` are excluded. Many narrow
  per-file ignores exist — match the existing pattern, don't widen globally.
- **mypy**: `disallow_untyped_defs`, `disallow_any_generics`,
  `disallow_untyped_calls`, `warn_return_any` all on (not full `strict`).
  Every def in `honua_sdk`/`honua_admin` is annotated; keep it that way.
  Generated protobuf modules are exempted.
- **UP037 (quoted forward refs) is intentionally kept** in package source so the
  compatibility-gate public-API snapshot stays stable — don't strip the quotes.
- **Protocol IDs**: use canonical cross-SDK ids (`geoservices-feature-service`,
  `ogc-features`, `stac`, `odata`); aliases are normalized at runtime via
  `honua_sdk.normalize_protocol` / `PROTOCOL_ALIASES`.
- **Integration tests are opt-in** (`--run-integration`, markers
  `integration`/`staging`/`smoke`) and require `HONUA_BASE_URL`. Set
  `HONUA_ENABLE_WRITE_SMOKE=true` to enable the write roundtrip. The same
  `--run-integration` flag gates `tests/conformance` (marker `conformance`).
- **Live-server conformance lane** (`tests/conformance`, `scripts/_conformance.py`,
  `.github/workflows/conformance.yml`): blocking on PR/push to trunk. It pulls a
  **pinned** `honua-server:nightly` (`nightly-20260530`, recorded with its
  resolved digest/revision in the job summary), fetches the **shared
  geospatial-grpc conformance fixtures** with `conformance/fetch-fixtures.sh`
  (version pinned in `conformance/FIXTURES_VERSION`, 1:1 with a `geospatial.v1`
  schema release), and exercises them against the live REST surfaces via the
  `httpx` clients — failing on any drift. The seeded server must run with
  `ASPNETCORE_ENVIRONMENT=Development` (the client-compat seed activates the
  metadata-v2 snapshot for `default`/`Development`/`Test`, not `Production`).
  Known, already-tracked nightly server gaps are marked `xfail` with explicit
  issue references in `scripts/_conformance.py::KNOWN_SERVER_GAPS`
  (honua-server#1238 JSONB-attribute projection is the live-checked one today;
  #1166 temporal, #1167 replica, #1237 analysis list/estimate are reserved);
  when a fix lands, clear the case's `known_gap_issue` to make it required.
  New/untracked drift still fails the lane — never blanket `continue-on-error`.
- CI runs on the `trunk` branch (lint, typecheck, test matrix, compatibility,
  security-audit, package smoke-install of built wheels, and the live-server
  conformance lane).

## Shared dev-environment rules (multi-agent WSL)

This machine runs many agents concurrently (**Codex + Claude**, often via agentflow with multiple tabs/agents). To prevent host lockups and lost work, every agent MUST follow these:

1. **Heavy builds/tests are throttled by a shared lock.** `dotnet` and `npm` are PATH-shimmed, so their build/test/publish/pack and ci/install/test/run-build/run-test subcommands automatically run under a global semaphore (default 1 concurrent, `HONUA_BUILD_SLOTS`). For other heavy tools, call the wrapper explicitly: `with-build-lock pytest ...`, `with-build-lock cargo build`, `with-build-lock make build`. The lock is shared across ALL of this user's processes (every Codex/Claude tab, agentflow children). Do not bypass it for compiles or test suites. Long-running servers (`dotnet run`, `npm run dev`) are intentionally NOT locked — never wrap those.

2. **Commit and push when you finish a task** so your worktree can be reclaimed. An hourly job (`honua-clean`) removes a worktree ONLY when it is clean AND fully pushed (merged, remote-gone, or idle >=2d). Dirty or unpushed worktrees are NEVER touched — but uncommitted/unpushed work blocks reclamation and is at risk if the instance is reset. Build artifacts (bin/obj and untracked node_modules) are reclaimed automatically and safely.

3. **Commit hygiene — no agent attribution.** Author every commit as the repo owner only (git identity: Mike McDougall <mike@honua.io>). Do **NOT** add any agent/tool attribution to commits: no `Co-Authored-By: Claude ...`, no `Co-Authored-By: Codex ...` (or other bot co-authors), and no "Generated with Claude Code" / "Generated with Codex" / "🤖" lines in the message or PR body. Write a plain, descriptive commit message and stop.
