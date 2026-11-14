# honua-sdk-python: agent instructions

Python clients for Honua: `honua-sdk` (data plane), `honua-admin` (control plane), and the
`honua-gp` geoprocessing workflow layer, each under `packages/`. Status: alpha
(`0.x`); APIs may change before 1.0. Python 3.11+; CI tests 3.11, 3.12 and 3.13.

## Setup
The root `pyproject.toml` holds shared tool config only and is not installable. Never run
`pip install .` or `pip install -e .` at the root; install the package directories:
```bash
pip install -e "packages/honua-sdk[grpc,geopandas]"
pip install -e "packages/honua-admin"
pip install pytest pytest-cov ruff mypy
```

## Commands (from the repo root; copied from `.github/workflows/ci.yml`)
```bash
ruff check .                                          # lint (honua-gp excluded)
python scripts/check_docs_command_policy.py           # no raw-HTTP examples in docs
python -m mypy packages/honua-sdk/honua_sdk packages/honua-admin/honua_admin
python3 -m pytest tests/ -q                           # deterministic local suite
python -m pytest tests/ -q --tb=short --cov=honua_sdk --cov=honua_admin \
  --cov-report=term-missing --cov-fail-under=94       # coverage gate
python scripts/compatibility_gate.py                  # public-API snapshot gate
python scripts/gen_sync.py --check                    # generated sync clients are fresh
python3 scripts/check-okf-bundle.py && python3 scripts/generate-summary.py --check   # docs/
```
Opt-in lanes (staging smoke, live-server conformance, release smoke, wheel build,
pip-audit, honua-gp): `docs/contributor/development.md`.

## Rules
- `honua_sdk/client.py` and `honua_admin/_client.py` are generated from `async_client.py` /
  `_async_client.py`. Edit the async module, run `python scripts/gen_sync.py`, commit both.
- mypy is `strict` workspace-wide; annotate every def in `honua_sdk` and `honua_admin`.
  Coverage floors: 94 combined, 93 per package. Keep ruff per-file ignores narrow and keep
  UP037 quoted forward refs (the API snapshot depends on them).
- Use canonical cross-SDK protocol ids (`geoservices-feature-service`, `ogc-features`,
  `stac`, `odata`); aliases go through `normalize_protocol`.
- Integration and conformance tests are opt-in (`--run-integration`, `HONUA_BASE_URL`).
- Never add custom-code submission or execution-backend selection (honua-server ADR-0063);
  `tests/test_custom_code_batch_only_policy.py` enforces it.
- A contract or schema version bump updates `release/component-versions.json` in the same PR.
  Starting or stopping reliance on a server capability updates
  `release/sdk-capability-baseline.json` in the same PR.
- New pages under `docs/` need OKF frontmatter; regenerate `docs/SUMMARY.md` with
  `python3 scripts/generate-summary.py`.

## Read before you act
- Conformance lane, known server gaps, lint/type settings, layout, release declarations:
  `docs/contributor/development.md`.
- Public-API and breaking-change policy: `docs/compatibility.md`.
- Review-only development source inputs: `docs/contributor/development-source-inputs.md`.

## Review guidelines

Reviews (people, Codex, Claude) judge the lines a PR adds or changes by Robert C. Martin's *Clean Code*
and cite smell codes ([rubric](https://github.com/honua-io/.github/blob/main/clean-code/RUBRIC.md)). The
`Clean code` PR check enforces what a tool can decide; `quality-exception: <reason>` in the PR body is logged.

BLOCKING:

- G5 duplication: search first; reuse or consolidate, never copy a handler, parser or validator.
- C1 history, ticket/PR refs or reviewer notes in code; C2-C4 obsolete, redundant or rambling comments;
  C5 commented-out code. Comment only what the code cannot say.
- XML doc comments (`///`) in application code; published SDKs keep at most a one-line `<summary>`
  on public members.
- N1 names that hide intent; F1 more than 3 parameters; F2 output arguments; F3 boolean flag arguments.
- Over budget with no reason in the PR: functions ~40 lines or 2 nesting levels; classes, files ~400 lines.

WARNING: the rubric's other smells (N2-N7, G6-G36, T1-T9), e.g. G25 magic numbers or G12
single-implementation interfaces.

<!-- fleet:begin v3 sha256=4faeba041ae102508d105847af58b407641cbfdf1ae506488819a2ccdbe73e29 -->
## Fleet rules (all Honua repos)

Generated from the org fleet-rules source; do not edit this block. Start with org skill `honua-system-map`.

1. Author commits as the repository owner's configured git identity. No AI attribution in commits or PR bodies.
2. Use a separate worktree per task, off the default branch, on durable disk. Include current trunk before opening a PR. No shared-checkout edits or git stash; preserve work with commits.
3. Run .NET builds and tests only through the approved remote build-host shims. Never fall back to a local build. See org skill `honua-build-host`.
4. Commit and push completed work; keep existing branches, commits and worktrees until their retention rules permit cleanup.
5. Claim work before starting, reread the issue and current lane rulings, and release the claim after completion. See org skill `honua-dev-loop`.
6. Use a PR slot and bundle at least three issues, a plan row, or a permitted single-work reason. Current caps and exceptions come from current lane rulings.
7. Target the default branch with the repository's PR template and conventional title. Never force-push or use an admin merge.
8. Run pre-PR checks, obtain one independent review of the final head, and resolve every review thread. Merge on green required checks; arm auto-merge where enforced checks support it. See org skill `honua-pr-flow`.
9. Read failed required-check logs and fix in one push. For red trunk, fix forward or revert within the repository's current ruling deadline; see org skills `honua-red-pr` and `honua-trunk-red`.
10. Never commit secrets, deployment identifiers, private repository names or infrastructure details. Security findings belong in the private tracker. Archived repos get no issues or PRs; public instructions name org skills only.
<!-- fleet:end -->

## Vocabulary review gate

Review every changed public name, CLI command, help string, error and authored example against the [canonical glossary](https://github.com/honua-io/honua-server/blob/115011ce760443e93ec70e4bd5123d7b9fa08414/docs/concepts/domain/README.md) and [shared retired-terms policy](https://github.com/honua-io/honua-server/blob/115011ce760443e93ec70e4bd5123d7b9fa08414/scripts/ci/retired-terms.v1.json). Block retired object names; use each actual kind, Connection, Dataset, Layer, Service, Folder, Environment and API key. Apply the policy's contextual exceptions for protocol wire names, dependency distributions and operating-system terminology. Server contract changes follow the coordinated migration.
