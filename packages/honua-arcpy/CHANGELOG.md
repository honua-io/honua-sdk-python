# Changelog

All notable changes to `honua-arcpy` will be documented in this file.

## 0.1.0 (2026-05-22)

Initial drop. Adds the proprietary `honua_arcpy` shim package covering 45
top-of-corpus arcpy functions (15 analysis, 20 management, 10 data-access).
Dispatches through `honua_sdk`, `honua_admin`, and
`honua_sdk.protocols.OgcProcessesClient` -- no direct REST/gRPC plumbing.

- Dispatch core, audit JSONL logger, path resolver, env/session shim.
- Compatibility matrix generated from in-code manifest.
- `honua-arcpy assess` CLI consuming the `honua_admin._arcpy_scanner` output.
- 50-script eval suite + `eval/run_eval.py` harness writing JUnit + JSON.
- End-to-end Buffer / Clip / ApplyEdits example.
- CI lane `honua-arcpy-eval.yml` reusing the staging-integration container
  pattern.
- Legacy suffix aliases (`Buffer_analysis`, `Clip_analysis`,
  `GetCount_management`, ...) so unmodified arcpy scripts continue to
  import.

### Known limitations

- `AddField`, `DeleteField`, `Rename`, `ListFields`, and `Describe` are
  shipped as stubs that raise `HonuaArcpyUnsupportedError`.
  `HonuaAdminClient` does not yet expose per-layer schema mutation or
  reading; the stubs surface the gap with a replacement hint and a
  `honua-server#layer-schema-mutate` / `honua-server#layer-schema-read`
  tracking ticket so the migration scanner picks them up.
- `GetCount` is `partial`: it materializes the full result set because the
  `Source` facade does not expose a count-only helper yet. Use bounded
  `where` clauses for large layers.
- `SourceDescriptor` mappings emitted by `_resolve.descriptor_mapping`
  default to `geoservices-feature-service` and treat unrecognized paths as
  `service_id=<name>, layer_id=0`. Customers with non-default layer IDs
  should configure `HONUA_ARCPY_PATH_MAP`.
