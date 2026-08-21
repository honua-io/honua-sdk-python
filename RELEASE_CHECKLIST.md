# Honua Python Package Release Checklist

The public distributions in this repository are `honua-sdk` and
`honua-admin`. Release Please owns their versions, changelogs, tags, and
GitHub Releases. Do not create or move publication tags by hand.

## Release PR

- Merge normal changes to `trunk` and let the `Release Please` workflow update
  its release PR.
- Review the package-specific version and changelog changes under
  `packages/honua-sdk/` and `packages/honua-admin/`.
- Confirm `README.md` and [INSTALL.md](INSTALL.md) match the current package
  surface.
- Run a dry build from the candidate ref with the `Publish Python Packages`
  workflow. Keep `dry_run` enabled and select the affected package(s); no
  `release_tag` is needed.
- Run `python -m pytest tests/ -q --tb=short` on Python 3.11+.
- For an SDK candidate, install the hash-locked publication requirements,
  build with `python -m build --no-isolation --wheel --sdist` from
  `packages/honua-sdk`, install the artifact in a clean environment, and run
  `python scripts/release_smoke.py --results-path release-smoke-results.json`.
- Review `release-smoke-results.json` for `overall_status`, `probe_counts`, and
  any per-probe `error` payloads.

For staging validation, export `HONUA_BASE_URL`, enable
`HONUA_ENABLE_WRITE_SMOKE=true` only when the add/query/update/delete roundtrip
is intended, and run:

```bash
python -m pytest tests/integration -q --run-integration -m "integration and staging and smoke" --tb=short
```

Use [docs/troubleshooting.md](docs/troubleshooting.md) for the `HONUA_*`
environment contract, seeded staging assumptions, and manual cleanup guidance.

## Automated publication

Publication is intentionally fail-closed until repository owners configure
all four external controls below. Do not dispatch a production recovery merely
to test these settings:

1. In **Settings > Environments**, open both `pypi-honua-sdk` and
   `pypi-honua-admin`. Set **Deployment branches and tags** to **Protected
   branches only**, disable administrator bypass, and keep `trunk` protected by
   the repository's branch rules.
2. In **Settings > Rules > Rulesets**, create an active tag ruleset with no
   bypass actors for `python-sdk-v*` (REST ref pattern
   `refs/tags/python-sdk-v*`). Enable restrictions for both tag updates and tag
   deletion.
3. Create the equivalent active, bypass-free tag ruleset for
   `python-admin-v*` (`refs/tags/python-admin-v*`), again restricting both
   updates and deletion.
4. Confirm the PyPI Trusted Publisher tuples still map this repository and
   `publish-python-sdk.yml` to their matching GitHub environments. The workflow
   verifies the GitHub environment and tag-rule settings through read-only REST
   calls before any build can reach an OIDC publisher; a missing, unreadable,
   disabled, bypassable, or incomplete control stops publication.

1. Merge the Release Please PR. Release Please creates the package tag(s) and
   GitHub Release(s) at that exact merge commit.
2. The completed `Release Please` run starts `Publish Python Packages` through
   `workflow_run`. Ordinary trunk runs with no matching new tag are a no-op.
3. Unprivileged jobs verify package metadata, trunk ancestry, peeled tag
   commit(s), GitHub Release targets, tests, and builds. Third-party
   build/test/type dependencies come from
   `.github/requirements/publish-python.lock` with pip hash enforcement; local
   packages install with dependency resolution and build isolation disabled.
   After validation, a separate fresh artifact job installs only the hashed
   third-party lock, materializes two independent clean worktrees pinned to the
   validated release commit, and builds the final wheel and sdist once from
   each with
   `SOURCE_DATE_EPOCH` derived from that commit. It does not execute repository
   tests or editable package code, and byte-for-byte manifest drift fails the
   run. Branch dry runs stop before a PyPI environment or OIDC permission.
4. A PyPI preflight treats an occupied version as a no-op only when its exact
   filename/SHA256 set matches the built wheel and source distribution. Any
   partial, extra, or mismatched registry file fails the release.
5. The minimal OIDC job only downloads the verified Actions artifact and
   invokes the pinned PyPI publisher. A separate unprivileged job then requires
   exact post-upload PyPI parity.
6. When both packages are released together, the SDK's PyPI parity and GitHub
   assets complete before the dependent `honua-admin` OIDC job can start.
7. The isolated GitHub Release job uploads only missing assets, fails rather
   than overwriting a different digest, verifies the final asset digests, and
   adds the exact-version PyPI install link.

The existing GitHub environments and PyPI Trusted Publisher tuples must remain:

| Distribution | GitHub environment | Workflow |
| --- | --- | --- |
| `honua-sdk` | `pypi-honua-sdk` | `publish-python-sdk.yml` |
| `honua-admin` | `pypi-honua-admin` | `publish-python-sdk.yml` |

No long-lived PyPI token or repository secret is required.

## Manual recovery

Use manual production dispatch only to reconcile an existing Release Please
release after the automated run failed or was missed:

1. Run `Publish Python Packages` from the `trunk` ref.
2. Disable `dry_run`, select the package or `both`, and enter an exact
   `release_tag` such as `python-sdk-v0.1.11`. For `both`, either package tag
   is accepted only when both expected tags resolve to the same release
   commit.
3. Review the resolver output and confirm it reports the intended immutable
   commit and package versions.

The recovery run fails before publication if the workflow is not from
`trunk`, the release commit is not an ancestor of `origin/trunk`, the tag does
not match package metadata, selected tags do not peel to the checked-out
commit, or a GitHub Release is missing, draft, or targets a different commit.
Occupied PyPI coordinates and existing GitHub assets are accepted only with
exact filename/SHA256 parity; no registry or release asset is blindly skipped
or overwritten.
