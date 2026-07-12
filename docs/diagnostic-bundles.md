# Sanitized diagnostic bundles

`honua doctor` creates a local, bounded support artifact without uploading it.
The artifact conforms to the canonical
[`diagnostic-bundle.v1` schema](https://honua.io/schemas/diagnostic-bundle.v1.json),
vendored byte-for-byte in the installed SDK and pinned to:

- support source commit `0c990fbe8f519a00a57e26dab21cbb8f80d559ea`;
- 6,494 bytes; and
- SHA-256 `4dd7282d17bb417d56f1c3cfa243e03b612a401e5d22be766658849287e431a9`.

The matching public provenance record is
[`diagnostic-bundle.v1.provenance.json`](https://honua.io/schemas/diagnostic-bundle.v1.provenance.json).
The support-owned valid/invalid conformance corpus is also shipped with the
package and exercised in CI so validator behavior cannot drift from intake.

## Emit and review

Capture the final failing exchange in a local JSON file. This input may contain
raw values because the command reads it only into memory:

```json
{
  "request": {
    "method": "GET",
    "url": "https://server.example/rest/services/roads/FeatureServer/0/query?token=secret",
    "headers": { "authorization": "Bearer secret" }
  },
  "response": {
    "status": 500,
    "mediaType": "application/problem+json",
    "headers": { "content-type": "application/problem+json" },
    "body": { "error": "failed", "apiKey": "secret" }
  }
}
```

Choose the classification and both consent values explicitly:

```bash
honua doctor \
  --exchange ./failure.json \
  --classification customer-data \
  --redaction-acknowledged true \
  --share-with-support false \
  --output ./diagnostic-bundle.json
```

Add `--base-url https://server.example/honua` to attempt one anonymous,
credential-free capability read. Probe failure produces a minimal sanitized
envelope and does not remove the supplied failure, which remains the final
envelope.

The command validates the complete bundle against the pinned v1 constraints
before atomic output and writes owner-only permissions where supported. Stdout
contains only a machine-readable result summary (SDK/runtime context, schema
pin, envelope count, and upload state), never the artifact path or traffic.
`sdkContext` is not written into the artifact because the canonical v1 schema
forbids extension fields.

Review the JSON locally. If it is appropriate to share, rerun with
`--share-with-support true` and submit the reviewed file through the support
intake workflow. The CLI itself never uploads.

## Privacy boundary

The Python emitter deliberately persists no body preview. Request and response
bodies are hashed in memory, then discarded; the artifact retains only original
byte size, SHA-256, and flags recording that the content was removed. It also:

- removes URL origin, user information, path parameters, and query values;
- drops Authorization, Proxy-Authorization, Cookie, Set-Cookie, API keys,
  signatures, tokens, and every non-allowlisted header;
- omits absent optional fields rather than serializing `null`;
- rejects credential-shaped bundle IDs and consent identities;
- caps input at 30 MiB, each body at the schema's 25 MiB maximum, capability
  responses at 256 KiB, envelopes at 50, and headers at 32; and
- never writes raw request/response bytes, configured API keys, cookies, or
  customer body values to stdout, stderr, artifacts, telemetry, or snapshots.

## Read-only replay

Replay the final sanitized read envelope against a separately configured server:

```bash
honua doctor \
  --replay ./diagnostic-bundle.json \
  --base-url https://server.example \
  --output ./diagnostic-replay.json
```

Replay validates and safety-checks the entire source artifact before network
access. It sends no captured headers, bodies, credentials, or query values,
disables redirects, and allows exactly one bounded `GET` or `HEAD`. Mutation,
subscription, traversal, placeholder paths, request bodies, unsafe headers,
credential-shaped previews, malformed bundles, changed verifiable hashes,
timeouts, and over-budget responses fail closed. A successful replay creates a
new sanitized v1 bundle and never modifies the source.
