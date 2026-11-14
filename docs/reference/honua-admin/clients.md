---
type: reference
title: "honua-admin clients"
description: "Generated API reference for the control-plane client used to manage connections, services and layers."
resource: "https://pypi.org/project/honua-admin/"
tags: [api-reference, honua-admin]
---
# honua-admin › Clients

The admin SDK ships sync and async clients with parity to the data-plane
SDK: pick [`HonuaAdminClient`][honua_admin.HonuaAdminClient] for scripts
and CLIs, and
[`AsyncHonuaAdminClient`][honua_admin.AsyncHonuaAdminClient] for async
services. Both clients share the data-plane configuration model
(auth, retries, timeouts, ``with_options(...)``); see the
[honua-sdk core client model](../../core-client.md) for the conceptual
overview that applies to both packages.

```python
from honua_admin import HonuaAdminClient

with HonuaAdminClient("https://admin.your-honua-server.com", api_key="...") as admin:
    services = admin.list_services()
```

Upload a file and update a service's access policy through either client:

```python
from honua_admin import BackgroundImportResponse, HonuaAdminClient

with HonuaAdminClient("https://admin.your-honua-server.com", api_key="...") as admin:
    with open("points.geojson", "rb") as source:
        result = admin.upload_file(source, filename="points.geojson", table_name="points")
    if isinstance(result, BackgroundImportResponse):
        print(result.job_id, result.status_url)
    elif result.success:
        print(result.schema, result.physical_table_name, result.feature_count)
    else:
        print(result.error_code, result.error_message)
    settings = admin.update_access_policy("default", allow_anonymous=True)
```

For `AsyncHonuaAdminClient`, await both calls. `upload_file` sends multipart
`file` and `TableName`; it accepts bytes or an open binary stream. It buffers
all remaining bytes in memory from the stream's current position, leaves the
stream open at EOF, and rejects empty/exhausted input. For a second call,
rewind the stream explicitly or pass bytes. Use files that fit in available
memory. Let httpx generate the multipart Content-Type and boundary; do not
set Content-Type in request headers or an external client's default headers.
`content_type` sets only the file part's media type.

Uploads use the existing POST retry policy: one attempt by default, with
replayable buffered content if a caller explicitly enables POST retries on
a supplied transport or external httpx client. Supply an `idempotency_key`
when opting into POST retries. Both operations accept `timeout`,
`extra_headers`, and `idempotency_key` per call and preserve configured base
paths and authentication.

`update_access_policy` sends only supplied fields. `None` preserves the
server value; `False` disables the corresponding anonymous permission, and
`[]` clears a role restriction. The response contains refreshed service
settings, including the resolved access policy.

## Folders

Both clients expose the server's one-level Folder catalog. Access is managed
per Service. `service_name` remains the logical Admin identity; use protocol
links from discovery when connecting to a Service.

| Method | Result |
| --- | --- |
| `list_folders()` | `(list[Folder], snapshot_etag)` including empty Folders |
| `create_folder(name, if_match=etag)` | `(Folder, new_etag)` |
| `update_folder(id, if_match=etag, ...)` | `(Folder, new_etag)` |
| `delete_folder(id, if_match=etag)` | New ETag; the Folder must be empty |
| `move_service(name, folder_id, if_match=etag)` | New ETag; `None` selects Root |

```python
from honua_admin import HonuaAdminClient

with HonuaAdminClient("https://admin.your-honua-server.com", api_key="...") as admin:
    folders, etag = admin.list_folders()
    if etag is None:
        raise RuntimeError("The catalog response did not include an ETag")
    folder, etag = admin.create_folder("Survey", title="Field survey", if_match=etag)
    if etag is None:
        raise RuntimeError("The mutation response did not include an ETag")
    etag = admin.move_service("parcels", folder.metadata.id, if_match=etag)
```

Await the same methods on `AsyncHonuaAdminClient`. The ETag belongs to the
whole catalog, so another catalog edit can make it stale. A stale write raises
`HonuaHttpError` with status 412: refresh and review the intended change before
retrying. Conflicts, non-empty deletion and authorization failures retain the
server's HTTP error status and details. Where approval is required, these calls
surface that requirement; they do not approve the mutation.

Omitting `namespace` keeps the operation unscoped. Supplying it selects the
namespace operation in the Environment the client is connected to. Folder moves and
path renames retain the old public paths according to the server's reservation
rules. `update_folder(..., title=None)` clears display text; omitting `title`
preserves it. Changing `name` changes the Folder path.

Publishing accepts `PublishLayerRequest.folder_id`: omit it to preserve the
server's default or existing membership, supply `None` to select Root, or pass
the Folder ID. `public_name` selects the immutable public leaf for a new
Service. It is separate from the logical `service_name` and display title.
Existing calls without these fields keep their original request JSON.

**See also**: [honua-sdk Clients](../honua-sdk/clients.md) for the data-plane
counterpart that shares the same configuration model, and
[Core client model](../../core-client.md) for cross-package `with_options(...)`
semantics.

::: honua_admin.HonuaAdminClient
::: honua_admin.AsyncHonuaAdminClient
