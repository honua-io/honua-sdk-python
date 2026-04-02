# Honua Python SDK Release Checklist

## Baseline

- Update `pyproject.toml` version using semantic versioning.
- Add release notes to [CHANGELOG.md](CHANGELOG.md).
- Confirm `README.md` and [INSTALL.md](INSTALL.md) match the current package surface.

## Validation

- Run `python -m pytest tests/ -q --tb=short` on Python 3.11+.
- Run `python -m pytest tests/integration -q --run-integration -m "integration and staging and smoke" --tb=short` against staging when validating a release candidate.
- Build the package with `hatch build`.
- Create a clean virtual environment, install the built `honua-sdk` artifact, and run `python scripts/release_smoke.py`.
- Review `release-smoke-results.json` before publish.
- Dry-run the `Publish Python SDK` workflow when validating a release candidate.

Use [docs/troubleshooting.md](docs/troubleshooting.md) for the `HONUA_*` environment contract, seeded staging assumptions, and manual cleanup guidance.

## Publish

- Merge release changes to `trunk`.
- Create a `python-sdk-v<version>` tag that matches `pyproject.toml`.
- Monitor the `Publish Python SDK` workflow for PyPI upload completion.
