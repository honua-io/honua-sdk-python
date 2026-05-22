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
