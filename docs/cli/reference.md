---
type: reference
title: "Command reference"
description: "Every honua and honua-admin command: the SDK call it makes, its options, its stdout and its exit codes."
resource: "honua://capability/admin.control-plane"
tags: [cli, reference]
---
# Command reference

Each command makes one typed SDK call. The CLI sends no HTTP requests of its
own. `honua-admin <group> ...` and `honua <group> ...` are the same for the
`datasource`, `layer` and `proposal` groups.

## Exit codes and output

| Exit | Meaning |
|------|---------|
| `0` | Success. |
| `1` | The server or transport refused the call. stderr carries `error: HTTP <status>: <message>`, for example `HTTP 403` for a self-approval or `HTTP 404` for a disabled layer. Also returned when `datasource test` reports an unhealthy connection, or when `proposal read --wait` times out. |
| `2` | Usage error: a missing argument, a bad `--body` file, or a group given without a subcommand. |

With `--json`, a command prints the server-shaped result (camelCase keys) on
stdout: an object for a single record, or an array for a listing. Without
`--json` it prints a table or `key: value` lines. Errors go to stderr only.

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
