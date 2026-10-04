---
type: guide
title: "Run the operator workflow from a terminal"
description: "Create and test a PostGIS datasource, publish a table, query and count it, approve an agent's proposal as a second principal, then unpublish the layer, using only the PyPI command-line clients."
resource: "honua://capability/admin.control-plane"
tags: [cli, operator, publish, approval]
---
# Run the operator workflow from a terminal

This guide runs a whole publication from the shell with the `honua` script.
Every step is one command, and with `--json` each one prints a JSON object you
can pipe into `jq`.

## Before you start

```bash
pip install honua-sdk honua-admin
export HONUA_BASE_URL=https://honua.example.com
export HONUA_ADMIN_KEY=...   # control-plane commands: datasource, layer, proposal
export HONUA_API_KEY=...     # data-plane commands: services, layers, query
```

The control-plane commands read `--api-key`, then `HONUA_ADMIN_KEY`, then
`HONUA_API_KEY`. The data-plane commands read `--api-key`, then
`HONUA_API_KEY`.

## 1. Find the published services

```bash
honua services --json
```

## 2. Create a datasource and test it

The password never goes on the command line. Name an environment variable
that holds it with `--password-env`, pipe it in with `--password-stdin`, or put
it in a `--body` file that only you can read.

```bash
export FIXTURE_DB_PASSWORD=...
honua datasource create \
  --name lifecycle --host db.internal --port 5432 --database gis --username honua \
  --password-env FIXTURE_DB_PASSWORD --ssl-mode Require --json
```

The result carries `connectionId`. Test the stored connection:

```bash
honua datasource test conn-1 --json
```

The command exits `1` when the server reports `"isHealthy": false`.

## 3. Publish a table and list it

```bash
honua layer publish conn-1 \
  --schema honua_data --table lifecycle_sites --layer-name lifecycle_sites \
  --service-name lifecycle --geometry-column geom --geometry-type Point \
  --srid 4326 --primary-key gid --json
honua layer list conn-1 --service-name lifecycle --json
```

`publish` prints the new layer's `layerId`. You can also pass the whole
request as JSON with `--body layer.json`, and flags override fields from the
file.

## 4. Query and count the features

```bash
honua query lifecycle 1 --where "status = 'open'" --format geojson
honua query lifecycle 1 --count --json
```

`query` makes one request and prints the server's page as GeoJSON (the
default) or as Esri JSON (`--format json`). If the server cut the page short,
it carries `exceededTransferLimit`; use `--limit` and `--offset` to read the
next page.

## 5. Approve a proposal as a separate principal

Governed principals don't publish directly. When an agent calls the MCP
`honua_publish_service` tool, the server records a proposal and waits for
approval. The command line has no submit command, because the server has no
REST call for submitting a proposal. Find the waiting proposal, then approve it
with a different key:

```bash
honua proposal list --status AwaitingApproval --json
honua proposal approve prop-123 --api-key "$APPROVER_KEY" --json
honua proposal read prop-123 --wait --api-key "$APPROVER_KEY" --json
```

If the principal that requested the proposal tries to approve it, the server
refuses: the command exits `1` and prints `error: HTTP 403: ...` on stderr.
`read --wait` polls once a second until the status is terminal (`Succeeded`,
`Failed`, `Rejected`, `RolledBack` or `Cancelled`). It exits `1` if that
doesn't happen within `--wait-timeout` seconds (default 120). To turn a
proposal down instead, run `honua proposal reject prop-123 --reason "..."`.

## 6. Unpublish the layer

```bash
honua layer unpublish conn-1 1 --service-name lifecycle --json
honua query lifecycle 1   # exits 1: error: HTTP 404: ...
```

`unpublish` (alias `disable`) turns the layer off but keeps its definition.
`honua layer enable conn-1 1` turns it back on.

See the [command reference](reference.md) for every option.
