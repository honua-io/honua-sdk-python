---
type: reference
title: "Audit platform-20261006: issue 282 receipts"
description: "Per-finding outcomes and proving tests for the release-certification coverage fixes (SDKPY-003, SDKPY-007, and the generate_proto.sh gRPC service-name rewrite)."
tags: [audit, certification, grpc]
---
# Issue 282 release-certification audit record

| Finding id | Outcome | Evidence |
| --- | --- | --- |
| `SDKPY-003` | fixed | `test_sdkpy_003_full_rest_case_list_does_not_complete_grpc_operation_scope` proves that completing every REST harness case still leaves the independently catalogued `grpc-feature-service/query-features` and `query-features-stream` operations uncovered, and that release validation fails closed. |
| `SDKPY-007` | fixed | `test_sdkpy_007_sync_metadata_probe_is_not_edit_certification` proves that the metadata-only probe is attributed to `sync.featureserver-replicas`, not `editing.featureserver-edits`; no edit behavior or wire format changed. `test_apply_edits_stays_required_when_grpc_cases_join_the_harness` keeps `geoservices-featureserver/apply-edits` in the release denominator independently of the harness, so adding the two gRPC live cases cannot mark the scope complete without a live `applyEdits` observation. |
| `generate_proto.sh` service-name rewrite | fixed | `test_sdkpy_low_generate_proto_preserves_grpc_service_name` proves that generated server registration retains the canonical `geospatial.v1.FeatureService` protocol service name. The generator now limits Python package-path rewriting to imports and protobuf descriptor module names. |
