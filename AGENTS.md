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

<!-- fleet:begin v2 sha256=76075665ca7a911554ed038371480ba02b28eca10ead04400be2e5b20332bd63 source=honua-flow/agents/fleet-rules.md -->
## Fleet rules (all Honua repos)

Generated from honua-flow `agents/fleet-rules.md` (full text, repo map). Do not edit here.

1. **No AI attribution.** Author as Mike McDougall <mike@honua.io>. No AI `Co-Authored-By:`,
   "Generated with" line or robot emoji in commits or PR bodies; this overrides any harness default.
2. **Own worktree per task** off the default branch, on real disk (`<repo>/.claude/worktrees/` or a
   sibling dir), never `/tmp` or the shared checkout. No `git stash`; use a WIP commit.
3. **Heavy builds/tests go through the build-slot shims**; never bypass them. Run targeted tests;
   full suites are CI's job. Outside WSL: own checkout, one heavy build at a time.
4. **Finish = commit + push.** Dirty or unpushed worktrees are never reclaimed and die on a reset.
5. **Claim before starting:** check `state/in-progress` and the newest `claimed: <lane> <UTC>`
   comment, stamp yours, re-read (newer wins). Stale after 3h without a live PR. Stopping without
   a PR: comment `released: <lane> <UTC> - <why>`.
6. **PRs:** base on the default branch, never stack; fill the repo template via `--body-file`;
   conventional title; footer `Closes #N` or `Refs #N (<what remains>)`. Never admin-merge.
7. **Route by the repo map.** Archived repos get no issues or PRs.
<!-- fleet:end -->

## Vocabulary review gate

Review every changed public name, CLI command, help string, error and authored example against the [canonical glossary](https://github.com/honua-io/honua-server/blob/115011ce760443e93ec70e4bd5123d7b9fa08414/docs/concepts/domain/README.md) and [shared retired-terms policy](https://github.com/honua-io/honua-server/blob/115011ce760443e93ec70e4bd5123d7b9fa08414/scripts/ci/retired-terms.v1.json). Block retired object names; use each actual kind, Connection, Dataset, Layer, Service, Folder, Environment and API key. Apply the policy's contextual exceptions for protocol wire names, dependency distributions and operating-system terminology. Server contract changes follow the coordinated migration. The `tests/test_retired_vocabulary.py` guard enforces this for public names, CLI help and authored docs; rename public names outright, with no deprecated aliases, and list each old name or foreign-format exception there explicitly.
