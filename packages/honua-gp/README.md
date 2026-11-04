# honua-gp

`honua-gp` is a separately licensed package for running supported
geoprocessing operations against a Honua deployment. Its implementation uses
the `honua-sdk`, `honua-admin`, and OGC API Processes clients.

## Quick start

```python
import honua_gp as gp

gp.configure(base_url="https://honua.example.com", api_key="...")
gp.env.workspace = "honua://services/transport"
gp.env.overwriteOutput = True

gp.management.MakeFeatureLayer("roads", "roads_lyr", where_clause="STATUS = 'OPEN'")
count = int(gp.management.GetCount("roads_lyr"))
```

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

This package is proprietary and is not published by the public CI workflow.
Its `LICENSE` applies to this package; the surrounding repository packages
use their own licenses.
