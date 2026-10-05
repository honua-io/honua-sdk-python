Run the Docker interoperability regression against the independently built
`ghcr.io/honua-io/honua-server:nightly-ff5f567` (pinned by digest in `conftest.py`):

```sh
python3 -m pytest tests/grpc -q --run-integration
```

Docker Compose and network access to the pinned server repository/image are
required. The fixture downloads the candidate's canonical client conformance
Compose configuration and SQL seed from its exact source revision, uses the
documented admin password unchanged, waits for the server's own migrations,
and then seeds `test_service` / layer 0. Each run uses an isolated Compose
project and dynamically allocated loopback port and cleans up its containers
and volumes. Server diagnostics remain in pytest's temporary `server.log`.

Four cases cover synchronous/asynchronous unary queries and streams, including
pagination, response metadata, attributes, and geometry. There is no local
Python service implementation or mock transport. Before regenerating the SDK,
all four fail with `UNIMPLEMENTED: Service is unimplemented.` The normal local
suite excludes this opt-in live-server module; explicitly requested interop
runs fail on infrastructure errors rather than skipping cases.
