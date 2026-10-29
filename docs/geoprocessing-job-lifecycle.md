---
type: concept
title: "How a geoprocessing job progresses"
description: "The server contract a job follows from submission through polling to result retrieval, and where the SDK sits in it."
resource: "honua://capability/jobs.durable-runtime"
tags: [geoprocessing, jobs, lifecycle]
---
# Geoprocessing job lifecycle

## Server contract first

`HonuaGeoprocessing` operates registered OGC API Processes. It does not upload
or execute arbitrary Python code.

| Item | Contract |
| --- | --- |
| Capability | `process.ogc-api-processes` |
| Submit | `POST /ogc/processes/processes/{processId}/execution` |
| Status | `GET /ogc/processes/jobs/{jobId}` |
| Results | `GET /ogc/processes/jobs/{jobId}/results` |
| Cancel | `DELETE /ogc/processes/jobs/{jobId}` (best effort) |
| Auth | `HonuaClient` API key, bearer token, or refreshable auth provider |
| Fixture | `honua-samples/jobs/geoprocessing-job-lifecycle.json#job-page-fixture:geometry-buffer-v1` |
| Maturity | Source preview; not yet published to PyPI |
| Result href | Absolute result links are fetched only when scheme, host, and port match the client. A foreign origin is refused. |

Inspect the process description before constructing `inputs`; those schemas are
defined by the registered server process. The focused example therefore takes
an explicit process id and JSON input object rather than embedding a payload
that only works for one deployment:

```bash
python examples/geoprocessing_job_lifecycle.py \
  --process-id geometry.buffer \
  --inputs-json '{"inputGeoJson":"{}","distance":100}'
```

That command belongs to the example script. The product `honua` CLI currently
has no process/job subcommands.

The example calls the real
[`HonuaGeoprocessing.submit_inputs`](reference/honua-sdk/clients.md#honua_sdk.geoprocessing.HonuaGeoprocessing.submit_inputs),
[`wait`](reference/honua-sdk/clients.md#honua_sdk.geoprocessing.HonuaGeoprocessing.wait), and
[`results`](reference/honua-sdk/clients.md#honua_sdk.geoprocessing.HonuaGeoprocessing.results)
methods. The wait has a deadline and performs a best-effort dismiss on timeout.
Use `dismiss(job_id)` only from an explicit operator cancellation action.

The shared, server-first JS/Python/.NET task contract, expected status sequence,
and semantic assertion live in `honua-samples/jobs/geoprocessing-job-lifecycle.json`.

## Synchronous execution

`respond_async=False` lets the server return document outputs in the submission
response. The SDK marks that execution successful and stores its qualified
outputs in `job.inline_results`. Pass the job object to `results()` so the same
code also works when the server chooses asynchronous execution:

```python
job = gp.submit_inputs("geometry.area", inputs, respond_async=False)
terminal = gp.wait(job, timeout=120)
outputs = gp.results(terminal)
```

The async client uses the same contract with `await`. A synchronous response may
have no durable job ID; retain the job object to retrieve its inline results.

## Custom Python batch jobs

Custom-code authoring is a separate production project. The current server
contract is AWS-Batch-only and pins runtime, allowlisted repository, full commit
SHA, `module:function` entrypoint, dependency manifest, declared scope, and a
server-assigned output prefix. The Python SDK has no custom-code authoring or
submission API, and no current Studio Python editor/publish flow is admitted.
Do not substitute `submit_inputs()` for that missing product surface.
