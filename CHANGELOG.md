# Changelog

All notable changes to the Honua Python SDK will be documented in this file.

## [0.0.1a0] - Unreleased

### Added

- Core HTTP client (`HonuaClient`) for Honua Server REST API
- Feature query support with geometry and attribute filtering
- Optional gRPC transport via `honua-sdk[grpc]` extra
- `honua-arcpy` 0.1.0 -- proprietary drop-in `arcpy` compatibility shim
  covering 45 top-of-corpus functions (analysis / management / data-access),
  dispatching through the existing SDK / admin / OGC API Processes clients,
  with audit JSONL, compatibility matrix, scanner-handoff CLI, and 50-script
  eval harness. Distributed via private PyPI only -- see
  [`docs/honua-arcpy/`](docs/honua-arcpy/README.md).
