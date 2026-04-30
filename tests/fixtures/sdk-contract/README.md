# SDK Contract Fixtures

These JSON fixtures define cross-SDK semantics for the Honua shared source and
query contract. They are meant to be consumed by JavaScript, Python, and .NET
tests.

The fixtures validate behavior and envelopes, not exact method spelling. Each
SDK should map the same concepts into idiomatic local names.

Current fixture:

- `semantic-contract.v1.json`: protocol and capability registries, common
  language binding names, result-envelope scenarios, unsupported-capability
  expectations, and degraded-result expectations.

When this fixture changes, update:

- The source/query section in `docs/core-client.md`
- The parity notes in `docs/protocol-parity.md`
- The JavaScript and .NET fixture consumers in their SDK repositories
