---
type: index
title: "Long-form documentation map"
description: "What lives in this docs directory and in what order to read it, from the quickstart through the deep-dives to the generated API reference."
resource: "https://pypi.org/project/honua-sdk/"
tags: [sdk, python, navigation]
---
# Honua SDK Documentation

This directory holds the long-form docs for the Honua Python SDKs
(`honua-sdk` data-plane, `honua-admin` control-plane). The monorepo
[README](../README.md) covers installation and the high-level package map;
the pages below are organized by audience.

Start at **[the Python SDK landing page](index.md)** — it carries the canonical
idiom, the install matrix for both packages, and the "I want to…" routing table.
This file is the directory map for people browsing the repository.

## What is here

- [index.md](index.md) — the landing page for both packages.
- [quickstart.md](quickstart.md) — five-minute setup and first query against
  the public demo server.
- [core-client.md](core-client.md) — the `Source` / `Query` / `Result` facade,
  protocol routing, and capability checks.
- [protocol-examples.md](protocol-examples.md) — per-protocol recipes.
- [protocol-parity.md](protocol-parity.md) — supported protocol matrix.
- [auth.md](auth.md) — API keys, bearer tokens, refreshable providers.
- [pagination.md](pagination.md), [retries-and-timeouts.md](retries-and-timeouts.md)
  — cross-cutting client behaviour.
- [compatibility.md](compatibility.md) — server baseline and the release gate.
- [troubleshooting.md](troubleshooting.md) — reading `HonuaHttpError` payloads.
- [examples.md](examples.md), [demo-suite.md](demo-suite.md) — runnable demos.
- [honua-gp/](honua-gp/README.md) — the proprietary ArcPy shim.
- [reference/](reference/honua-sdk/clients.md) — generated API reference.

## Project process

- [operating-cadence.md](operating-cadence.md) -- release, review, and audit
  cadence followed by the SDK maintainers.
