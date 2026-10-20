ci: install the gRPC interop candidate from a built wheel

## Summary

Scorecard code-scanning alert #295 (PinnedDependenciesID, `pipCommand not pinned by hash`) is the last open pinning finding in this repo. It points at `.github/workflows/ci.yml:34`, where the `grpc-interop` job runs `pip install --no-deps --no-build-isolation ./packages/honua-sdk`. Scorecard counts a non-editable source-path install as unpinned. The `-e` installs elsewhere in CI already pass.

The job now builds the candidate wheel with the hatchling version locked in `ci.lock`, then installs that wheel with `--no-deps`. A source-path install builds that same wheel implicitly, so the installed candidate is unchanged and the job still tests an installed copy of the package, not an editable one.

## Changes Made

- `ci.yml` `grpc-interop`: `pip wheel --no-deps --no-build-isolation --wheel-dir build/candidate-wheel ./packages/honua-sdk`, then `pip install --no-deps build/candidate-wheel/*.whl`. `build/` is already gitignored.

## Breaking Changes

None.

## Testing

- Checked against Scorecard's own rules (`checks/raw/shell_download_validate.go`): only `pip install` counts as a download, and a `--no-deps` install whose only argument is a `*.whl` path counts as pinned.
- In a scratch venv on native Windows, with `hatchling==1.30.1` (the version `ci.lock` locks), both commands succeed and `honua_sdk` installs into site-packages.
- actionlint 1.7.12 passes on all workflows.
- honua-release `tools/check_action_pins.py` (trunk 4642e4d, with the reusable-workflow reachability check enabled) passes on all workflows.
- `git diff --check` passes.

The open alert counts on trunk f36e702 (2026-10-20) are 5 code-scanning (this PinnedDependenciesID plus the repo-policy checks BranchProtection, CodeReview, CII-Best-Practices and Fuzzing) and 0 Dependabot. Scorecard re-evaluates this alert on trunk after merge. No alert was dismissed.
