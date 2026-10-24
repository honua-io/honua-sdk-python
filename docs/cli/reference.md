---
type: reference
title: "Command reference"
description: "Every honua and honua-admin command: the SDK call it makes, its options, its stdout and its exit codes."
resource: "honua://capability/admin.control-plane"
tags: [cli, reference]
---
# Command reference

Server commands use typed SDK calls. The CLI sends no HTTP requests of its
own. The explicit `gp` command invokes a separate local developer tool.
`honua-admin <group> ...` and `honua <group> ...` are the same for the
`datasource`, `layer` and `proposal` groups.

## Exit codes and output

| Exit | Meaning |
|------|---------|
| `0` | Success. |
| `1` | The server or transport refused the call. stderr carries `error: HTTP <status>: <message>`, for example `HTTP 403` for a self-approval or `HTTP 404` for a disabled layer. Also returned when `datasource test` reports an unhealthy connection, or when `proposal read --wait` times out. |
| `2` | Usage error: a missing argument, a bad `--body` file, or a group given without a subcommand. |
| `3` | `gp inspect` / `gp logs` only: unauthorized (HTTP 401 or 403). This is not a missing job and not missing evidence. |
| `4` | `gp inspect` / `gp logs` only: the job was not found (HTTP 404). |
| `5` | `gp inspect` / `gp logs` only: retained evidence expired (HTTP 410, or the server said it expired). |
| `6` | `gp inspect` / `gp logs` only: a log stream started and was interrupted before a truthful end. |

With `--json`, a command prints the server-shaped result (camelCase keys) on
stdout: an object for a single record, or an array for a listing. Without
`--json` it prints a table or `key: value` lines. Errors go to stderr only.

## Local GP development

Install the `Honua.Geoprocessing.Cli` devkit separately using the
[server authoring guide](https://docs.honua.io/guides/query-analyze/gp-devkit-authoring).
Put its `honua-gp-devkit` executable on PATH, or set `HONUA_GP_CLI` to its full
executable path. The SDK does not download or install this engine automatically.

```bash
honua gp doctor --managed-only --json
honua gp list --json
honua gp describe geometry.buffer --json
```

Arguments and output pass through to the engine, including repeated `--param`
values. The engine owns its exit codes; failure to launch it returns `127`.
No server URL is needed for these local commands. `honua doctor` remains the
separate support-bundle command.

## Diagnose a GP job

`honua gp inspect` and `honua gp logs` are handled by this SDK before that
devkit fallback. They read the canonical `honua.job-diagnostics/v1` projection
(`GET /api/v1/admin/jobs/{jobId}/diagnostics`). They do not require
`HONUA_GP_CLI` or a server source checkout.

```bash
honua gp inspect JOB_ID --base-url https://example.test
honua gp inspect JOB_ID --json
honua gp logs JOB_ID --events 100
honua gp inspect .honua/runs/RUN_ID
```

Pass a local receipt directory (the folder that contains `receipt.json` and
`events.jsonl`) to format it with the same code and make no network or
credential read. A remote job id uses `--base-url` / `HONUA_BASE_URL` and
`--api-key` / `HONUA_API_KEY`.

Human inspect output leads with the failing phase, the attempt, and a next
action that follows `failure.recovery` or the recorded retry disposition.
`--json` prints that projection only, with no progress prose on stdout. Logs
print bounded event pages (`--events`, default 50, maximum 500) and disclose
truncation. `events.firstCursor`, `events.nextCursor`, `events.truncated`, and
`evidence.missing` / `evidence.truncated` are kept. An owner view stays an
owner view; a 403 is unauthorized, not missing evidence. Secrets are redacted
from command output and are not written to logs.

An installed published CLI inspecting a live successful and intentionally
failed candidate job is not claimed here. That journey remains outstanding.

This developer tool does not add a local backend selector to SDK server
submissions. Server-side untrusted custom code retains its AWS Batch isolation
policy. The existing proprietary `honua-gp` ArcPy compatibility executable is
a different tool; it is not used as the devkit engine.

## Connection options

Every control-plane command accepts:

| Option | Default |
|--------|---------|
| `--base-url URL` | `HONUA_BASE_URL` |
| `--api-key KEY` | `HONUA_ADMIN_KEY`, then `HONUA_API_KEY` |
| `--timeout SECONDS` | `30` |
| `--json` | table / `key: value` output |

`services`, `layers` and `query` accept `--base-url` and `--api-key`, which
default to `HONUA_BASE_URL` and `HONUA_API_KEY`.

## Data plane (`honua`)

| Command | SDK call | Output |
|---------|----------|--------|
| `honua services [--json \| --format table]` | `HonuaClient.list_service_summaries` | `[{"name", "type", "url"}]` |
| `honua layers SERVICE_ID [--json \| --format table]` | `HonuaClient.feature_server(...).metadata` | `[{"id", "name", "type", "geometryType"}]`; an unknown service exits `1` with `HTTP 404` |
| `honua query SERVICE_ID LAYER_ID` | `HonuaClient.query_features` | The server's GeoJSON `FeatureCollection` (`--format geojson`, default) or Esri JSON page (`--format json`) |
| `honua query SERVICE_ID LAYER_ID --count [--json]` | `HonuaClient.query_features` with `returnCountOnly` | `N`, or `{"count": N}` with `--json` |

`query` options: `--where` (default `1=1`), `--out-fields` (default `*`),
`--order-by`, `--limit` (`resultRecordCount`), `--offset` (`resultOffset`).

## `datasource`

| Command | SDK call |
|---------|----------|
| `datasource list` | `HonuaAdminClient.list_connections` |
| `datasource create ...` | `HonuaAdminClient.create_connection` |
| `datasource test CONNECTION_ID` | `HonuaAdminClient.test_connection`; exits `1` when `isHealthy` is `false` |

`create` options: `--name`, `--description`, `--host`, `--port` (default
`5432`), `--database`, `--username`, `--ssl-required`, `--ssl-mode`,
`--secret-reference`, `--secret-type`, and one password source:

- `--password-env VAR` reads the password from environment variable `VAR`.
- `--password-stdin` reads the first line of stdin.
- `--body FILE` reads a JSON request object (camelCase or snake_case keys,
  `-` for stdin). Flags override its fields.

The password is never accepted as a flag value, and it is never printed.

## `layer`

| Command | SDK call |
|---------|----------|
| `layer list CONNECTION_ID [--service-name NAME]` | `HonuaAdminClient.list_layers` |
| `layer publish CONNECTION_ID ...` | `HonuaAdminClient.publish_layer` |
| `layer unpublish CONNECTION_ID LAYER_ID [--service-name NAME]` (alias `disable`) | `HonuaAdminClient.set_layer_enabled(..., False)` |
| `layer enable CONNECTION_ID LAYER_ID [--service-name NAME]` | `HonuaAdminClient.set_layer_enabled(..., True)` |

`publish` options: `--table` (required here or in `--body`), `--schema`
(default `public`), `--layer-name`, `--service-name`, `--description`,
`--geometry-column`, `--geometry-type`, `--srid`, `--primary-key`, `--field`
(repeatable), `--disabled`, `--body FILE`.

Each command prints a `PublishedLayerSummary`: `layerId`, `layerName`,
`schema`, `table`, `geometryType`, `srid`, `primaryKey`, `fieldCount`,
`enabled` and `serviceName`.

## `proposal`

| Command | SDK call |
|---------|----------|
| `proposal list [--status S] [--kind K] [--requested-by P]` | `HonuaAdminClient.list_proposals` |
| `proposal read PROPOSAL_ID [--wait] [--wait-timeout SECONDS]` | `HonuaAdminClient.get_proposal` |
| `proposal approve PROPOSAL_ID` | `HonuaAdminClient.approve_proposal` |
| `proposal reject PROPOSAL_ID --reason TEXT` | `HonuaAdminClient.reject_proposal` |

`read`, `approve` and `reject` print an `OperationProposalDetail`:
`proposalId`, `kind`, `status`, `requestedBy`, `resolvedBy`,
`resolutionReason`, `summary`, `diff`, `dryRun`, `riskLevel`,
`blockingReasons`, `warnings`, `guardrailTier`, `executionOperationId` and
timestamps. The server refuses a self-approval with `403`, an unknown proposal
with `404`, and a proposal that cannot be applied in its state with `409`.
Proposals come from the agent surface (the MCP `honua_publish_service` tool
for a governed principal). The server has no REST call for submitting one, so
the CLI has no submit command.

## `honua admin`

`honua admin ...` forwards to the `@honua/sdk-js` command line when that
binary is on `PATH` or named by `HONUA_JS_CLI`. When neither is found, the
command exits `127` and names the Python operator commands above.
