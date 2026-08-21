# Publication dependency lock

`publish-python.lock` is the only third-party dependency input used by the
Python publication workflow's typecheck, test, and build jobs. Pip installs it
with `--require-hashes` and `--only-binary=:all:`. Local Honua packages are then
installed editable with both dependency resolution and build isolation
disabled, so the exact Hatchling version in this lock controls the build
backend even during recovery of an older tag.

To update the lock, first review and edit the exact direct pins in
`publish-python.in`, then regenerate with Python 3.13 and pip-tools 7.5.2:

```bash
pip-compile --generate-hashes --strip-extras \
  --output-file=.github/requirements/publish-python.lock \
  .github/requirements/publish-python.in
```

Review all transitive changes and verify the resulting lock installs with hash
enforcement on the supported Python 3.11, 3.12, and 3.13 runners before merge.
