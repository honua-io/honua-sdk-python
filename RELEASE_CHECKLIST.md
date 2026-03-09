# Honua Python SDK Release Checklist

## Baseline

- Update `pyproject.toml` version using semantic versioning.
- Add release notes to [CHANGELOG.md](CHANGELOG.md).
- Confirm `README.md` and [INSTALL.md](INSTALL.md) match the current package surface.

## Validation

- Run `python -m pytest tests/ -q --tb=short` on Python 3.11+.
- Build the package with `hatch build`.
- Dry-run the `Publish Python SDK` workflow when validating a release candidate.

## Publish

- Merge release changes to `trunk`.
- Create a `python-sdk-v<version>` tag that matches `pyproject.toml`.
- Monitor the `Publish Python SDK` workflow for PyPI upload completion.
