---
type: index
title: "Command-line clients"
description: "The honua and honua-admin console scripts that the PyPI packages install, and where each command is documented."
tags: [cli, operator]
---
# Command-line clients

The PyPI packages install two console scripts:

| Script | Installed by | Commands |
|--------|--------------|----------|
| `honua` | `honua-sdk` | `services`, `layers`, `query`, `style apply`, `doctor`. When `honua-admin` is installed it also has `datasource`, `layer` and `proposal`. |
| `honua-admin` | `honua-admin` | `datasource`, `layer`, `proposal` |

`honua datasource ...` and `honua-admin datasource ...` run the same code, and
so do the `layer` and `proposal` groups. Install both packages to get the
full operator workflow:

```bash
pip install honua-sdk honua-admin
```

- [Run the operator workflow from a terminal](operator-workflow.md): create
  and test a datasource, publish a layer, query it, approve a proposal, then
  unpublish the layer.
- [Command reference](reference.md): every command, its options, its JSON
  output and its exit codes.
- [Collect a support bundle](../diagnostic-bundles.md): `honua doctor`.
