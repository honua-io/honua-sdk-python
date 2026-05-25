# Examples

Runnable, script-first demos live under
[`examples/`](https://github.com/honua-io/honua-sdk-python/tree/trunk/examples)
in the repository. The repo's
[`examples/README.md`](https://github.com/honua-io/honua-sdk-python/blob/trunk/examples/README.md)
is the single source of truth for the demo catalogue, target users,
extras, entry points, and artifacts -- this page links there so the
table never drifts out of sync with the on-disk scripts.

## Cloud environment contract

All cloud-runnable demos read the same environment variables, documented
alongside the table in
[`examples/README.md`](https://github.com/honua-io/honua-sdk-python/blob/trunk/examples/README.md#cloud-environment-contract):

- `HONUA_BASE_URL`
- `HONUA_API_KEY`
- `HONUA_SERVICE_ID`
- `HONUA_LAYER_ID`
- `HONUA_COLLECTION_ID`
- `HONUA_STAC_COLLECTION_ID`

The checked-in scripts target the seeded `test_service` layer used by
local Honua server development. Cloud runs should point the variables
at an equivalent writable or readable fixture; demos that write data
filter their own slice (e.g. the ETL demo's `uid LIKE 'demo-etl-%'`
target filter).

## Optional STAC and imagery

STAC calls are included in the
[spatial query cookbook](https://github.com/honua-io/honua-sdk-python/blob/trunk/examples/spatial_query_cookbook.py)
when `HONUA_STAC_COLLECTION_ID` points at a fixture collection. A
runnable imagery scoring pipeline is intentionally gated until the
server fixture publishes stable scene metadata, asset keys, cloud-cover
field, and item count.

## Validation

Run the focused example tests from the repository root:

```bash
pytest tests/test_geospatial_etl_example.py tests/test_python_analyst_demos.py
```

For cloud validation, set the environment variables above and run the
scripts manually against a fixture service before attaching artifacts
to issue or PR notes.
