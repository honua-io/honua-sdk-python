# honua-gp

> **Native application path:** [gRPC for live data and edits; PMTiles, GeoParquet and COG through the CDN](../../docs/native-data-paths.md). Start there for browser gRPC-Web setup, signed private URLs and regeneration after changes. OGC API and GeoServices REST examples below are compatibility workflows.

`honua-gp` is an Apache-2.0 package for running supported
geoprocessing operations against a Honua deployment. Its implementation uses
the `honua-sdk`, `honua-admin`, and OGC API Processes clients.

## Quick start

```python
import honua_gp as gp

gp.configure(base_url="https://honua.example.com", api_key="...")
gp.env.overwriteOutput = True

gp.management.MakeFeatureLayer("honua://services/transport/1", "roads_lyr", where_clause="STATUS = 'OPEN'")
count = int(gp.management.GetCount("roads_lyr"))
```

Replace `transport` and `1` with the Service name and `layerId` returned when
you publish your Layer. Use the complete `honua://services/<service>/<layerId>`
URI: a Dataset name inside `gp.env.workspace` does not look up the published
Layer and defaults to Layer 0. Replace the filter with one valid for your data.

The supported operations and their current limitations are listed in the
[compatibility matrix](docs/compatibility-matrix.md). Unsupported operations
raise a clear error. Every invocation writes a JSONL audit record under
`${HONUA_GP_AUDIT_DIR:-./.honua-gp/audit}`; paths and credentials are
redacted before the record is written.

The `honua-gp matrix` command renders or checks the compatibility matrix.

## Status

The manifest contains 13 supported entries and 16 partial entries
(29 supported/partial) + 35 stubs.

## Distribution

Releases use the repository's trusted-publishing workflow with build provenance
and a wheel SBOM. Install a published version from PyPI:

```bash
pip install honua-gp
```

The [Apache-2.0 license](LICENSE) matches `honua-sdk` and `honua-admin`.
