# Retries and Timeouts

This deep-dive explains how the Honua SDK's retry transport behaves, what
counts as a transient failure, how `Retry-After` is honoured, and how to
override timeouts and retry budgets on a per-call or per-clone basis.

The retry transports (`RetryTransport`, `AsyncRetryTransport`) and the
`parse_retry_after` helper are re-exported from the public
`honua_sdk.http` module. The implementation lives in
`honua_sdk._retry_core` (pure policy) plus the sync and async retry
transports; both share the policy verbatim.

## Defaults at a glance

| Knob | Default | Source |
|------|---------|--------|
| `max_retries` | `3` | `_DEFAULT_MAX_RETRIES` |
| `retry_methods` | `{GET, HEAD, PUT, DELETE, OPTIONS}` | `_DEFAULT_RETRY_METHODS` |
| `retry_statuses` | `{429, 502, 503, 504}` | `_DEFAULT_RETRY_STATUSES` |
| `backoff_initial` | `0.5` s | `_DEFAULT_INITIAL_BACKOFF` |
| `backoff_max` | `5.0` s | `_DEFAULT_MAX_BACKOFF` |
| `jitter` | `True` (full-jitter) | `RetryTransport.__init__` |
| `timeout` | `30.0` s | `HonuaClient.__init__` |

## Idempotency gating

Only requests whose HTTP method is in `retry_methods` are retried. By
default the set is the idempotent five (`GET`, `HEAD`, `PUT`, `DELETE`,
`OPTIONS`) so mutations through `POST` are never silently duplicated.

Callers who know their `POST`s are safe (for example, they carry an
`Idempotency-Key` header) can opt in:

```python
from honua_sdk import HonuaClient
from honua_sdk.http import RetryTransport
import httpx

transport = RetryTransport(
    httpx.HTTPTransport(),
    retry_methods=frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "POST"}),
)
client = HonuaClient("https://example.com", transport=transport)
```

When `POST` is in `retry_methods`, mutating helpers such as
[`HonuaClient.apply_edits`][honua_sdk.HonuaClient.apply_edits] auto-generate an
`Idempotency-Key` (a fresh `uuid4().hex`) if the caller did not supply
one — see `build_idempotency_headers` in `honua_sdk._endpoints`.

## Transport-exception retries

In addition to retriable status codes, the transport retries the
following `httpx` exception classes (defined in
`_RETRIABLE_TRANSPORT_EXCEPTIONS`):

- `httpx.ConnectError`
- `httpx.ReadError`
- `httpx.WriteError`
- `httpx.RemoteProtocolError`
- `httpx.PoolTimeout`
- `httpx.ProxyError`
- `httpx.TimeoutException` (parent of `ConnectTimeout`, `ReadTimeout`,
  `WriteTimeout`, `PoolTimeout`)

These are surfaced to callers as
[`HonuaTransportError`][honua_sdk.errors.HonuaTransportError] (or
[`HonuaTimeoutError`][honua_sdk.errors.HonuaTimeoutError] for the timeout
subclasses) once the retry budget is exhausted.

## Backoff math and jitter

For retry attempt `n` (0-indexed), the cap is:

```
cap = min(backoff_initial * 2**n, backoff_max)
```

With the defaults this is the schedule `0.5s, 1.0s, 2.0s, 4.0s, 5.0s, ...`
(capped at `5.0s`).

When `jitter=True` (default) the actual sleep is drawn from
`random.uniform(0, cap)` — known as *full-jitter*. When `jitter=False`
the deterministic `cap` value is used verbatim. The attempt counter
resets on each new request.

## `Retry-After`

When the server responds with `Retry-After`, the parsed value is honoured
(and is **never** jittered) but is **clamped to `backoff_max`** (default
`5.0s`) so a large server-sent header cannot block far longer than the
configured ceiling. Both forms from RFC 7231 are supported (see
`parse_retry_after` re-exported via `honua_sdk.http`):

- delta-seconds: `Retry-After: 3` → 3.0 seconds; `Retry-After: 120` is
  clamped to `backoff_max` (→ 5.0 seconds with the defaults).
- HTTP-date: `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT` →
  `min(max(0, target - now), backoff_max)` in seconds. A date in the past
  becomes `0.0`.

Unparseable values fall back to the exponential backoff above.

## Per-call options

Every public client method accepts three per-call overrides:

| Option | Effect |
|--------|--------|
| `timeout` | Forwarded to the underlying `httpx` request as a per-request timeout. |
| `extra_headers` | Merged onto the request headers (lower precedence than `idempotency_key`). |
| `idempotency_key` | Sets the `Idempotency-Key` request header. |

```python
result = client.list_services(timeout=5.0, extra_headers={"X-Trace": "abc"})
```

## `with_options()` — sticky overrides

Use [`HonuaClient.with_options`][honua_sdk.HonuaClient.with_options] when
you want a clone that applies the same overrides across many requests:

```python
fast_client = client.with_options(timeout=2.0)
slow_client = client.with_options(timeout=60.0, max_retries=10)
```

Behaviour notes:

- **Timeout floor.** The underlying `httpx.Client` binds its timeout at
  construction. Tightening the timeout (`new < init`) builds an
  **independent clone** with its own `httpx.Client` so the lower
  transport timeout actually applies. Loosening (`new >= init`) reuses
  the parent's `httpx.Client` and pool with a per-request
  `httpx.Timeout(...)` override.
- **Connection-pool sharing.** Transport-sharing clones do not own the
  transport — calling `close()` on the clone is a no-op; only the
  parent's `close()` (or context-manager exit) tears the pool down.
- **`base_url` always clones.** Passing `base_url=` always builds an
  independent clone; the clone owns its `httpx.Client` and must be
  closed independently.
- **`max_retries` overrides** are forwarded to the retry transport via
  `request.extensions["honua_max_retries"]`, so they apply even on
  transport-sharing clones.

## Worked recipes

### Honor server-provided `Retry-After`

No code required — `Retry-After` is honoured automatically. To inspect
the parsed value on a 429 that escaped the retry budget:

```python
from honua_sdk import HonuaRateLimitError

try:
    client.list_services()
except HonuaRateLimitError as exc:
    print(f"rate limited; server asked for {exc.retry_after}s")
```

### Opt POST into retries with an explicit idempotency key

```python
result = client.apply_edits(
    "parcels",
    layer_id=0,
    adds=[{"attributes": {"name": "lot-42"}, "geometry": geom}],
    idempotency_key="apply-2026-05-21-batch-001",
)
```

If you opt POST into `retry_methods` and omit `idempotency_key`, the SDK
auto-generates a fresh `uuid4().hex` per request.

### Tighten timeout for a single hot path

```python
preview = client.with_options(timeout=2.0)
features = preview.source(descriptor).query(Query(where="1=1", limit=10))
```

Because `2.0 < 30.0`, this builds an independent clone. Close it (or
use a `with` block) when you're done.

### Retry on `ConnectError` but not on 4xx

The default policy already does this: only `429, 502, 503, 504` retry;
all other 4xx responses surface immediately as
[`HonuaHttpError`][honua_sdk.errors.HonuaHttpError] subclasses, and
`ConnectError` is in `_RETRIABLE_TRANSPORT_EXCEPTIONS`. To narrow
further (e.g. retry transport errors only, no status retries):

```python
from honua_sdk.http import RetryTransport
import httpx

transport = RetryTransport(
    httpx.HTTPTransport(),
    retry_statuses=frozenset(),  # disable status-driven retries
)
client = HonuaClient("https://example.com", transport=transport)
```

## See also

- [Pagination](pagination.md) — Source pagination signals and iterator vs
  collected patterns.
- [Errors][honua_sdk.errors.HonuaError] — exception hierarchy raised by
  the SDK transport layer.
- [Core client model](core-client.md) — broader configuration tour.
