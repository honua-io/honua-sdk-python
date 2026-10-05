These bindings are generated from **honua-io/geospatial-grpc v1.0.0**, revision
`0f701ecc6b0c41a5ea43e2dff3c46ce654312576`, using `grpcio-tools==1.70.0`
(protobuf compiler 5.29.0). This matches the `Geospatial.Grpc` package pinned by
honua-server `ff5f5671903e96e13cffac7b73546c3ed0f853c5` (`nightly-ff5f567`).

The SDK owns generation in `scripts/generate_proto.sh`; the protocol repository
owns the schema. The script fetches the immutable revision, generates
FeatureService and its complete dependency closure, and qualifies generated
imports/module names under `honua_sdk.grpc._generated`. Do not edit the generated
Python files. It removes obsolete `honua.v1` output only after successful generation.

From the SDK repository root, in a development virtual environment:

```sh
pip install grpcio-tools==1.70.0
scripts/generate_proto.sh
# Offline alternative: archive the same pinned commit from a local checkout.
scripts/generate_proto.sh /path/to/geospatial-grpc
```

The public request's `result_offset` and `result_record_count` map to canonical
int64 wire fields 20 and 21 (`result_offset_long`, `result_record_count_long`).
The old int32 fields 8 and 9 are reserved by the canonical schema.
