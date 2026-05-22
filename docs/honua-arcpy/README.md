# honua-arcpy docs

`honua-arcpy` is a **proprietary** drop-in compatibility shim that lets
existing `arcpy` scripts run end-to-end against a Honua deployment. It is
distributed from this monorepo with its own `LICENSE` (see
[`packages/honua-arcpy/LICENSE`](../../packages/honua-arcpy/LICENSE)) which
**overrides** the surrounding Apache-2.0 license for that package only.

## Pointers

* [Compatibility matrix](compatibility-matrix.md) -- generated from the
  in-code manifest at `packages/honua-arcpy/honua_arcpy/_compat.py`.
* [Scanner handoff](scanner-handoff.md) -- how a `scan_arcpy_script`
  inventory becomes a per-call TODO list via `honua-arcpy assess`.
* Package README: [`packages/honua-arcpy/README.md`](../../packages/honua-arcpy/README.md).
* Example end-to-end script:
  [`packages/honua-arcpy/examples/buffer_clip_roundtrip.py`](../../packages/honua-arcpy/examples/buffer_clip_roundtrip.py).

## Distribution

The package is intended for a private PyPI index (founder decision pending --
recommended target is GitHub Packages scoped to the `honua-io` org). The
public CI lane (`ci.yml`) does **not** publish this package; publishing is
gated behind a manual workflow once the index is configured.

When the founder decides to extract the package into a private repo (the
design's R1 recommendation), the contents of `packages/honua-arcpy/` move
verbatim. The in-code manifest, audit logger, dispatcher, CLI, eval suite,
and tests are designed to be standalone within that directory.
