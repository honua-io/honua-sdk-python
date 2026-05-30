"""Async Admin API client for Honua Server."""

from __future__ import annotations

import copy
import warnings
from collections.abc import Mapping
from typing import Any

import httpx
from honua_sdk.http import (
    AsyncRetryTransport,
    AuthProvider,
    HonuaHttpError,
    apply_sensitive_auth_headers,
    build_sensitive_auth_headers,
    encode_path_segment,
    extract_trusted_authority,
    normalize_base_url,
    to_http_error,
    to_transport_error,
    validate_auth_configuration,
    validate_external_client_auth_configuration,
    warn_deprecated_bearer_token,
)

from . import _endpoints
from ._models import (
    AdminCapabilitiesResponse,
    AdminCompatibilityBaseline,
    AdminCompatibilityCheckResult,
    AdminCompatibilityFeatureFlags,
    AdminVersionResponse,
    ConnectionTestResult,
    CreateSecureConnectionRequest,
    EncryptionValidationResult,
    KeyRotationResult,
    LayerStyleResponse,
    LayerStyleUpdateRequest,
    ManifestApplyRequest,
    ManifestApplyResult,
    MetadataManifest,
    MetadataResource,
    MigrationInventoryScanRequest,
    MigrationSourceInventoryArtifact,
    PublishedLayerSummary,
    PublishLayerRequest,
    SecureConnectionDetail,
    SecureConnectionSummary,
    ServiceSettingsResponse,
    ServiceSummary,
    TableDiscoveryResponse,
    UpdateSecureConnectionRequest,
    evaluate_admin_compatibility,
)


class AsyncHonuaAdminClient:
    """Asynchronous client for the Honua Admin (control-plane) API.

    Async counterpart to :class:`HonuaAdminClient`: methods map 1:1 to
    admin REST endpoints (services, metadata resources, manifests,
    connections, layers, styles, config) and return typed model objects.

    Authentication is configured at construction with at most one of
    ``api_key``, ``bearer_token``, or ``auth_provider`` (mutually
    exclusive). ``bearer_token=`` is **deprecated** (removal in 0.2.x);
    prefer ``auth_provider=StaticAuthProvider({"Authorization": f"Bearer
    {token}"})``. When ``client`` is supplied as a pre-built
    :class:`httpx.AsyncClient`, no auth kwargs may be passed — configure
    them on the client instead.

    Retries: only idempotent methods (GET/HEAD/PUT/DELETE/OPTIONS) on
    transient statuses (429/502/503/504) are retried by default. Opt
    POST in by configuring ``retry_methods`` on the underlying retry
    transport; mutating helpers (``apply_manifest``, ``create_connection``,
    ``publish_layer``) then auto-generate ``Idempotency-Key`` headers.

    Use as an async context manager so the underlying transport closes
    deterministically::

        async with AsyncHonuaAdminClient("https://example.com", api_key="...") as admin:
            services = await admin.list_services()

    Per-call overrides (``timeout``, ``extra_headers``,
    ``idempotency_key``) are exposed on every method; use
    :meth:`with_options` for sticky per-clone overrides (shared
    transport unless ``base_url`` is supplied).

    All HTTP failures surface as :class:`HonuaHttpError` (or one of its
    status-specific subclasses such as :class:`HonuaAuthError` /
    :class:`HonuaRateLimitError`); transport-level failures surface as
    :class:`HonuaTransportError` (and its subclass
    :class:`HonuaTimeoutError`).

    See also: :class:`honua_sdk.AsyncHonuaClient` and
    ``docs/core-client.md``.
    """

    MINIMUM_SUPPORTED_SERVER_BASELINE = AdminCompatibilityBaseline()

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        api_key: str | None = None,
        bearer_token: str | None = None,
        auth_provider: AuthProvider | None = None,
        follow_redirects: bool = False,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 3,
    ) -> None:
        """Construct an async admin client bound to a single Honua deployment.

        Args:
            base_url: Server base URL (scheme + host + optional path
                prefix). Trailing slashes are normalized.
            timeout: Request timeout in seconds applied to every call.
            api_key: Optional ``X-API-Key`` header value. Mutually
                exclusive with passing a pre-built ``client``.
            bearer_token: Optional ``Authorization: Bearer …`` value.
                Mutually exclusive with ``auth_provider`` and with a
                pre-built ``client``.
            auth_provider: Pluggable provider that yields request-time
                auth headers. Mutually exclusive with ``bearer_token``
                and with a pre-built ``client``.
            follow_redirects: Whether the underlying
                :class:`httpx.AsyncClient` follows 3xx redirects.
                Sensitive auth headers are still stripped when redirected
                to a different authority.
            client: A caller-supplied :class:`httpx.AsyncClient`. When
                set, the SDK will not own or close the client and the
                auth kwargs above must not be passed (configure them on
                the client instead).
            transport: A caller-supplied
                :class:`httpx.AsyncBaseTransport`. Mutually exclusive with
                ``client``. Use this to inject a
                :class:`httpx.MockTransport` in tests.
            max_retries: Maximum number of retry attempts on transient
                HTTP statuses (429/502/503/504). ``0`` disables retries.
                Only safe methods (GET/HEAD/PUT/DELETE/OPTIONS) and
                transient statuses (429/502/503/504) are retried by
                default.

        Raises:
            ValueError: ``client`` and ``transport`` are both supplied,
                or auth kwargs are supplied alongside a pre-built ``client``.
        """
        if client is not None and transport is not None:
            raise ValueError("Provide either `client` or `transport`, not both.")
        validate_auth_configuration(bearer_token=bearer_token, auth_provider=auth_provider)
        warn_deprecated_bearer_token(bearer_token)
        validate_external_client_auth_configuration(
            client=client,
            api_key=api_key,
            bearer_token=bearer_token,
            auth_provider=auth_provider,
        )

        # Stash constructor inputs so ``with_options`` can build an
        # independent clone without re-deriving these from ``self``.
        self._init_base_url = base_url
        self._init_timeout = timeout
        self._init_api_key = api_key
        self._init_bearer_token = bearer_token
        self._init_auth_provider = auth_provider
        self._init_follow_redirects = follow_redirects
        self._init_transport = transport
        self._init_max_retries = max_retries

        self._owns_client = client is None
        # Per-request overrides set by ``with_options``; ``None`` means the
        # underlying client's defaults apply.
        self._options_timeout: float | None = None
        self._options_max_retries: int | None = None
        # Track retry-eligible methods so mutating helpers can auto-generate
        # idempotency keys when callers opted ``POST`` into ``retry_methods``.
        self._retry_methods: frozenset[str] = frozenset()
        if client is not None:
            self._client = client
            # Capture the public ``base_url`` from the supplied client so we
            # never reach into the private ``_base_url`` attribute of
            # :class:`httpx.AsyncClient` from request-time code paths.
            self._base_url: httpx.URL = httpx.URL(client.base_url)
            return

        normalized_base_url = normalize_base_url(base_url)
        self._base_url = httpx.URL(normalized_base_url)
        trusted_authority = extract_trusted_authority(self._base_url)
        auth_headers = build_sensitive_auth_headers(api_key=api_key, bearer_token=bearer_token)

        async def _request_hook(request: httpx.Request) -> None:
            apply_sensitive_auth_headers(
                request,
                trusted_authority=trusted_authority,
                auth_headers=auth_headers,
                auth_provider=auth_provider,
            )

        effective_transport = transport
        if max_retries > 0:
            inner = effective_transport or httpx.AsyncHTTPTransport()
            retry_transport = AsyncRetryTransport(inner, max_retries=max_retries)
            effective_transport = retry_transport
            self._retry_methods = retry_transport.retry_methods

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            follow_redirects=follow_redirects,
            transport=effective_transport,
            event_hooks={"request": [_request_hook]},
        )

    # -- context manager ----------------------------------------------------

    async def __aenter__(self) -> AsyncHonuaAdminClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Release underlying HTTP resources if this instance owns the client.

        When constructed with an externally supplied
        :class:`httpx.AsyncClient`, ownership stays with the caller and
        this coroutine is a no-op.
        """
        if self._owns_client:
            await self._client.aclose()

    def with_options(
        self,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        base_url: str | None = None,
    ) -> AsyncHonuaAdminClient:
        """Return a clone with overridden options.

        When only ``timeout`` and/or ``max_retries`` are supplied, the
        returned client **reuses the original's** :class:`httpx.AsyncClient`
        and its connection pool — only the per-request ``timeout`` and
        (optionally) the per-request retry budget are overridden. In this
        transport-sharing mode the clone does **not** own the underlying
        client; awaiting :meth:`close` on the clone is a no-op. Only the
        original is responsible for closing the transport.

        **Passing ``base_url`` creates an independent client; the
        transport is NOT shared.** Because the underlying
        :class:`httpx.AsyncClient` binds its ``base_url`` (and
        authority-bound timeouts, event hooks, and connection-pool keys)
        at construction time, swapping the base URL on a shared client
        would silently target the wrong host for any code path that
        relies on those bindings. To avoid that footgun, supplying
        ``base_url`` builds a fresh :class:`httpx.AsyncClient` for the
        clone and the clone owns it — you must ``await
        clone.close()`` (or use ``async with``) independently of the
        original.

        The auth provider, if any, is reused (not duplicated) so token
        state is shared across the original and the clone.

        Args:
            timeout: When set, overrides the per-request timeout. Smaller
                ``timeout`` values automatically build an independent
                client (with the smaller transport timeout); larger
                values reuse the parent's transport with a per-request
                ``httpx.Timeout(...)`` override.
            max_retries: When set, overrides the retry budget. ``0``
                disables retries on the clone via a per-request extension
                read by the retry transport.
            base_url: When set, the returned clone is fully independent
                (owns its own :class:`httpx.AsyncClient` and connection
                pool) and must be closed separately. The transport is
                NOT shared with the original.

        Returns:
            An :class:`AsyncHonuaAdminClient` — transport-sharing when
            the override timeout is greater than or equal to the
            parent's configured timeout, independently-owned when
            ``base_url`` is supplied or when ``timeout`` is smaller than
            the parent's configured timeout.
        """
        if self._init_base_url is None and base_url is None and self._base_url is None:
            raise ValueError(
                "with_options() requires base_url when the original client was "
                "constructed with a pre-built httpx.AsyncClient."
            )
        needs_independent_clone = base_url is not None or (
            timeout is not None and timeout < self._init_timeout
        )
        if needs_independent_clone:
            # Independent clone: build a fresh httpx.AsyncClient so the new
            # base_url is honored end-to-end (URL resolution, authority-bound
            # timeouts, event hooks, connection pool keys), or so a smaller
            # transport timeout is actually applied (the parent's bound
            # timeout floors per-request overrides on the shared client).
            # The clone owns the new client and must be closed independently
            # of the original.
            effective_timeout = (
                timeout
                if (timeout is not None and timeout < self._init_timeout)
                else self._init_timeout
            )
            # Suppress the re-fired bearer_token deprecation on the internal
            # clone path; the caller acknowledged it at original construction.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                clone = self.__class__(
                    base_url if base_url is not None else self._init_base_url,
                    timeout=effective_timeout,
                    api_key=self._init_api_key,
                    bearer_token=self._init_bearer_token,
                    auth_provider=self._init_auth_provider,
                    follow_redirects=self._init_follow_redirects,
                    transport=self._init_transport,
                    max_retries=self._init_max_retries,
                )
            clone._options_timeout = (
                timeout if timeout is not None else self._options_timeout
            )
            clone._options_max_retries = (
                max_retries if max_retries is not None else self._options_max_retries
            )
            return clone

        # Shallow-copy ``self`` so future ``_init_*`` slots ride along
        # automatically; see :meth:`honua_sdk.HonuaClient.with_options`
        # for the full rationale.
        clone = copy.copy(self)
        clone._owns_client = False  # clone never closes the shared transport
        clone._options_timeout = (
            timeout if timeout is not None else self._options_timeout
        )
        clone._options_max_retries = (
            max_retries if max_retries is not None else self._options_max_retries
        )
        return clone

    def copy(
        self,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        base_url: str | None = None,
    ) -> "AsyncHonuaAdminClient":
        """Alias for :meth:`with_options`.

        Provided for parity with the stripe-python convention. The
        semantics are identical to :meth:`with_options`; see that method
        for the full contract.
        """
        return self.with_options(
            timeout=timeout, max_retries=max_retries, base_url=base_url
        )

    def _idempotency_headers(
        self,
        idempotency_key: str | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str] | None:
        """Build the ``Idempotency-Key`` header dict, auto-generating if needed."""
        return _endpoints.build_idempotency_headers(
            idempotency_key,
            retry_methods=self._retry_methods,
            extra=extra,
        )

    # -- internal helpers ---------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        """Issue a single async admin-API request, applying per-call overrides.

        Per-request options (Stripe / OpenAI-SDK shaped):

        * ``timeout``: overrides client- and ``with_options``-level timeouts
          for this call only.
        * ``extra_headers``: merged into the outbound request headers
          (``headers`` win on conflict; ``idempotency_key`` then overrides
          any ``Idempotency-Key`` set elsewhere).
        * ``idempotency_key``: when set, attaches an ``Idempotency-Key``
          header to the outbound request.
        """
        url = self._base_url.copy_with(raw_path=path.encode("ascii"))
        merged_headers = _merge_request_headers(headers, extra_headers, idempotency_key)
        request_kwargs: dict[str, Any] = {
            "method": method,
            "url": url,
            "params": params,
            "json": json_body,
            "headers": merged_headers,
        }
        if timeout is not None:
            request_kwargs["timeout"] = (
                timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout)
            )
        elif self._options_timeout is not None:
            request_kwargs["timeout"] = httpx.Timeout(self._options_timeout)
        if self._options_max_retries is not None:
            request_kwargs["extensions"] = {
                "honua_max_retries": self._options_max_retries,
            }
        try:
            response = await self._client.request(**request_kwargs)
        except httpx.HTTPError as exc:
            raise to_transport_error(exc) from exc
        if response.status_code >= 400:
            raise to_http_error(response)
        return response

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """Issue a request and unwrap the ApiResponse envelope.

        The Honua admin API wraps every successful response in::

            {"success": true, "data": <payload>, "message": "...", "timestamp": "..."}

        This method returns the inner ``data`` value. Per-request options
        ``timeout``, ``extra_headers``, ``idempotency_key`` are forwarded to
        :meth:`_request`.
        """
        response = await self._request(
            method,
            path,
            params=params,
            json_body=json_body,
            headers=headers,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return _endpoints.unwrap_envelope(response)

    # ======================================================================
    # Services
    # ======================================================================

    async def list_services(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[ServiceSummary]:
        """List every service registered on the admin catalog.

        Returns:
            Typed :class:`ServiceSummary` objects for each service the
            server reports. Empty when the server returns a non-list
            payload (e.g. an empty envelope).

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed before any HTTP
                response was received.
        """
        data = await self._request_json(
            "GET",
            "/api/v1/admin/services/",
            timeout=timeout,
            extra_headers=extra_headers,
        )
        if not isinstance(data, list):
            return []
        return [ServiceSummary.from_dict(s) for s in data]

    async def get_service_settings(
        self,
        name: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> ServiceSettingsResponse:
        """Fetch the resolved settings for a single service.

        Args:
            name: Service name as advertised by the catalog. URL-encoded.

        Returns:
            A :class:`ServiceSettingsResponse` describing protocol
            availability and per-protocol configuration.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        service_name = encode_path_segment(name)
        data = await self._request_json(
            "GET",
            f"/api/v1/admin/services/{service_name}/settings",
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return ServiceSettingsResponse.from_dict(data)

    async def update_protocols(
        self,
        name: str,
        protocols: list[str],
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> ServiceSettingsResponse:
        """Replace the enabled-protocol list for a service.

        Args:
            name: Service name; URL-encoded.
            protocols: Desired ordered list of protocol identifiers.

        Returns:
            The refreshed :class:`ServiceSettingsResponse`.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the update.
            HonuaTransportError: The request failed at the transport layer.
        """
        service_name = encode_path_segment(name)
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/services/{service_name}/protocols",
            json_body=protocols,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return ServiceSettingsResponse.from_dict(data)

    async def update_mapserver_settings(
        self,
        name: str,
        *,
        max_image_width: int | None = None,
        max_image_height: int | None = None,
        default_image_width: int | None = None,
        default_image_height: int | None = None,
        default_dpi: int | None = None,
        default_format: str | None = None,
        default_transparent: bool | None = None,
        max_features_per_layer: int | None = None,
        extra_settings: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> ServiceSettingsResponse:
        """Patch the MapServer-specific settings for a service.

        Args:
            name: Service name; URL-encoded.
            max_image_width: Maximum allowed image width in pixels.
            max_image_height: Maximum allowed image height in pixels.
            default_image_width: Default image width applied when callers omit one.
            default_image_height: Default image height applied when callers omit one.
            default_dpi: Default DPI used when callers omit one.
            default_format: Default image format (e.g. ``"png"``, ``"jpg"``).
            default_transparent: Default transparency setting for rendered tiles.
            max_features_per_layer: Server-side cap on features returned per layer.
            extra_settings: Escape hatch for additional snake-case settings that
                aren't represented as explicit kwargs. Keys are converted to
                camelCase before being sent. Only fields with non-``None``
                values are forwarded.

        Returns:
            The refreshed :class:`ServiceSettingsResponse`.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the update.
            HonuaTransportError: The request failed at the transport layer.
        """
        from ._models import _to_camel

        service_name = encode_path_segment(name)
        explicit: dict[str, Any] = {
            "max_image_width": max_image_width,
            "max_image_height": max_image_height,
            "default_image_width": default_image_width,
            "default_image_height": default_image_height,
            "default_dpi": default_dpi,
            "default_format": default_format,
            "default_transparent": default_transparent,
            "max_features_per_layer": max_features_per_layer,
        }
        merged: dict[str, Any] = {k: v for k, v in explicit.items() if v is not None}
        if extra_settings:
            for k, v in extra_settings.items():
                merged.setdefault(k, v)
        body = {_to_camel(k): v for k, v in merged.items()}
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/services/{service_name}/mapserver",
            json_body=body,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return ServiceSettingsResponse.from_dict(data)

    # ======================================================================
    # Metadata Resources
    # ======================================================================

    async def list_metadata_resources(
        self,
        kind: str | None = None,
        namespace: str | None = None,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[MetadataResource]:
        """List metadata resources, optionally filtered by kind/namespace.

        Args:
            kind: Optional resource-kind filter.
            namespace: Optional namespace filter.

        Returns:
            Matching :class:`MetadataResource` objects; empty when the
            server returns a non-list payload.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        params: dict[str, str] = {}
        if kind is not None:
            params["kind"] = kind
        if namespace is not None:
            params["namespace"] = namespace
        data = await self._request_json(
            "GET",
            "/api/v1/admin/metadata/resources",
            params=params or None,
            timeout=timeout,
            extra_headers=extra_headers,
        )
        if not isinstance(data, list):
            return []
        return [MetadataResource.from_dict(r) for r in data]

    async def get_metadata_resource(
        self,
        kind: str,
        ns: str,
        name: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> tuple[MetadataResource, str | None]:
        """Fetch a single metadata resource together with its ETag.

        Args:
            kind: Resource kind; URL-encoded.
            ns: Namespace; URL-encoded.
            name: Resource name; URL-encoded.

        Returns:
            A tuple ``(resource, etag)``; ``etag`` is ``None`` when the
            server did not return an ``ETag`` response header.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success
                status or the response body was not valid JSON.
            HonuaTransportError: The request failed at the transport layer.
        """
        kind_segment = encode_path_segment(kind)
        namespace_segment = encode_path_segment(ns)
        name_segment = encode_path_segment(name)
        response = await self._request(
            "GET",
            f"/api/v1/admin/metadata/resources/{kind_segment}/{namespace_segment}/{name_segment}",
            timeout=timeout,
            extra_headers=extra_headers,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise HonuaHttpError(
                response.status_code,
                "Failed to decode metadata resource JSON response",
                body=response.text,
            ) from exc
        inner = payload.get("data", payload) if isinstance(payload, Mapping) else payload
        resource = MetadataResource.from_dict(inner)
        etag = response.headers.get("ETag") or response.headers.get("etag")
        return resource, etag

    async def create_metadata_resource(
        self,
        resource: MetadataResource,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> MetadataResource:
        """Create a new metadata resource on the server.

        Args:
            resource: Desired initial state of the resource.

        Returns:
            The server-canonical :class:`MetadataResource` after creation.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the create.
            HonuaTransportError: The request failed at the transport layer.
        """
        data = await self._request_json(
            "POST",
            "/api/v1/admin/metadata/resources",
            json_body=resource.to_dict(),
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return MetadataResource.from_dict(data)

    async def update_metadata_resource(
        self,
        kind: str,
        ns: str,
        name: str,
        resource: MetadataResource,
        *,
        if_match: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> MetadataResource:
        """Replace the contents of a metadata resource.

        Args:
            kind: Resource kind; URL-encoded.
            ns: Namespace; URL-encoded.
            name: Resource name; URL-encoded.
            resource: Desired full state of the resource.
            if_match: Optional ETag for optimistic concurrency.

        Returns:
            The server-canonical :class:`MetadataResource` after update.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the update (including
                precondition failures when ``if_match`` is supplied).
            HonuaTransportError: The request failed at the transport layer.
        """
        kind_segment = encode_path_segment(kind)
        namespace_segment = encode_path_segment(ns)
        name_segment = encode_path_segment(name)
        hdrs: dict[str, str] = {}
        if if_match is not None:
            hdrs["If-Match"] = if_match
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/metadata/resources/{kind_segment}/{namespace_segment}/{name_segment}",
            json_body=resource.to_dict(),
            headers=hdrs or None,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return MetadataResource.from_dict(data)

    async def delete_metadata_resource(
        self,
        kind: str,
        ns: str,
        name: str,
        *,
        if_match: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        """Delete a single metadata resource.

        Args:
            kind: Resource kind; URL-encoded.
            ns: Namespace; URL-encoded.
            name: Resource name; URL-encoded.
            if_match: Optional ETag for optimistic concurrency.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the delete.
            HonuaTransportError: The request failed at the transport layer.
        """
        kind_segment = encode_path_segment(kind)
        namespace_segment = encode_path_segment(ns)
        name_segment = encode_path_segment(name)
        hdrs: dict[str, str] = {}
        if if_match is not None:
            hdrs["If-Match"] = if_match
        await self._request(
            "DELETE",
            f"/api/v1/admin/metadata/resources/{kind_segment}/{namespace_segment}/{name_segment}",
            headers=hdrs or None,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    # ======================================================================
    # Manifests
    # ======================================================================

    async def get_version(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AdminVersionResponse:
        """Return the server's reported admin API version.

        Returns:
            An :class:`AdminVersionResponse`.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        data = await self._request_json(
            "GET",
            "/api/v1/admin/version",
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return AdminVersionResponse.from_dict(data)

    async def get_capabilities(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AdminCapabilitiesResponse:
        """Return the server's advertised admin capabilities and compat block.

        Returns:
            An :class:`AdminCapabilitiesResponse`.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        data = await self._request_json(
            "GET",
            "/api/v1/admin/capabilities",
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return AdminCapabilitiesResponse.from_dict(data)

    async def get_capability_flags(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AdminCompatibilityFeatureFlags:
        """Return coarse feature flags from the admin compatibility contract.

        When the server does not expose a compatibility block (older
        deployments), the returned flags are all ``False``.

        Returns:
            An :class:`AdminCompatibilityFeatureFlags` describing which
            optional admin surfaces the server supports.

        Raises:
            HonuaHttpError: The underlying capabilities fetch failed
                with a non-success status.
            HonuaTransportError: The capabilities fetch failed at the
                transport layer.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`get_capabilities`.
        """
        compatibility = (
            await self.get_capabilities(timeout=timeout, extra_headers=extra_headers)
        ).compatibility
        if compatibility is None:
            return AdminCompatibilityFeatureFlags(
                metadata_resources=False,
                manifest_export=False,
                manifest_apply=False,
                manifest_dry_run=False,
                manifest_prune=False,
            )
        return compatibility.features

    async def check_compatibility(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AdminCompatibilityCheckResult:
        """Evaluate whether the connected server satisfies the admin SDK baseline.

        Returns:
            An :class:`AdminCompatibilityCheckResult` summarising whether
            the server's compatibility block meets
            :attr:`MINIMUM_SUPPORTED_SERVER_BASELINE`, along with any
            specific gaps.

        Raises:
            HonuaHttpError: The underlying capabilities fetch failed
                with a non-success status.
            HonuaTransportError: The capabilities fetch failed at the
                transport layer.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`get_capabilities`.
        """
        capabilities = await self.get_capabilities(timeout=timeout, extra_headers=extra_headers)
        return evaluate_admin_compatibility(
            capabilities.compatibility,
            self.MINIMUM_SUPPORTED_SERVER_BASELINE,
        )

    async def get_manifest(
        self,
        namespace: str | None = None,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> MetadataManifest:
        """Export the server's metadata as a single declarative manifest.

        Args:
            namespace: Optional namespace filter.

        Returns:
            A :class:`MetadataManifest`.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        params: dict[str, str] | None = None
        if namespace is not None:
            params = {"namespace": namespace}
        data = await self._request_json(
            "GET",
            "/api/v1/admin/manifest",
            params=params,
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return MetadataManifest.from_dict(data)

    async def apply_manifest(
        self,
        request: ManifestApplyRequest,
        *,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> ManifestApplyResult:
        """Apply a declarative metadata manifest to the server.

        Args:
            request: Manifest payload plus any dry-run / prune flags.
            idempotency_key: Stripe-style ``Idempotency-Key`` header value.
                When ``None`` and the underlying retry transport is
                configured to retry ``POST`` (i.e. the caller opted in via
                ``retry_methods``), a fresh ``uuid4`` hex is generated so
                that retries are de-duplicated server-side.

        Returns:
            A :class:`ManifestApplyResult` summarising the effect.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the manifest.
            HonuaTransportError: The request failed at the transport layer.
        """
        data = await self._request_json(
            "POST",
            "/api/v1/admin/manifest/apply",
            json_body=request.to_dict(),
            headers=self._idempotency_headers(idempotency_key),
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return ManifestApplyResult.from_dict(data)

    # ======================================================================
    # Migration Toolkit
    # ======================================================================

    async def scan_migration_source(
        self,
        request: MigrationInventoryScanRequest,
        *,
        export_json: bool = False,
    ) -> MigrationSourceInventoryArtifact:
        """POST /api/v1/admin/import/scan"""
        params = {"export": "json"} if export_json else None
        data = await self._request_json(
            "POST",
            "/api/v1/admin/import/scan",
            params=params,
            json_body=request.to_dict(),
        )
        return MigrationSourceInventoryArtifact.from_dict(data)

    # ======================================================================
    # Connections
    # ======================================================================

    async def list_connections(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[SecureConnectionSummary]:
        """List every secure datasource connection registered on the server.

        Returns:
            Typed :class:`SecureConnectionSummary` objects; empty when
            the server returns a non-list payload.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        data = await self._request_json(
            "GET",
            "/api/v1/admin/connections",
            timeout=timeout,
            extra_headers=extra_headers,
        )
        if not isinstance(data, list):
            return []
        return [SecureConnectionSummary.from_dict(c) for c in data]

    async def get_connection(
        self,
        id: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> SecureConnectionDetail:
        """Fetch detailed information for a single secure connection.

        Args:
            id: Connection identifier; URL-encoded.

        Returns:
            A :class:`SecureConnectionDetail`.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        connection_id = encode_path_segment(id)
        data = await self._request_json(
            "GET",
            f"/api/v1/admin/connections/{connection_id}",
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return SecureConnectionDetail.from_dict(data)

    async def create_connection(
        self,
        request: CreateSecureConnectionRequest,
        *,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> SecureConnectionSummary:
        """Create a new secure datasource connection.

        Args:
            request: Connection definition (DSN, credentials, options).
            idempotency_key: Stripe-style ``Idempotency-Key`` header value.
                When ``None`` and the underlying retry transport is
                configured to retry ``POST`` (i.e. the caller opted in via
                ``retry_methods``), a fresh ``uuid4`` hex is generated so
                that retries are de-duplicated server-side.

        Returns:
            A :class:`SecureConnectionSummary` (secrets elided).

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the create.
            HonuaTransportError: The request failed at the transport layer.
        """
        data = await self._request_json(
            "POST",
            "/api/v1/admin/connections",
            json_body=request.to_dict(),
            headers=self._idempotency_headers(idempotency_key),
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return SecureConnectionSummary.from_dict(data)

    async def test_draft_connection(
        self,
        request: CreateSecureConnectionRequest,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> ConnectionTestResult:
        """Verify a draft connection definition without persisting it.

        Args:
            request: The same payload that would be sent to
                :meth:`create_connection`.

        Returns:
            A :class:`ConnectionTestResult`. A failed probe is reported
            in the result payload, not as an exception.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server returned a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        data = await self._request_json(
            "POST",
            "/api/v1/admin/connections/test",
            json_body=request.to_dict(),
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return ConnectionTestResult.from_dict(data)

    async def update_connection(
        self,
        id: str,
        request: UpdateSecureConnectionRequest,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> SecureConnectionSummary:
        """Replace mutable fields on an existing secure connection.

        Args:
            id: Connection identifier; URL-encoded.
            request: Patch payload describing the new state.

        Returns:
            A refreshed :class:`SecureConnectionSummary`.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the update.
            HonuaTransportError: The request failed at the transport layer.
        """
        connection_id = encode_path_segment(id)
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/connections/{connection_id}",
            json_body=request.to_dict(),
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return SecureConnectionSummary.from_dict(data)

    async def test_connection(
        self,
        id: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> ConnectionTestResult:
        """Re-run the server-side connection probe for a stored connection.

        Args:
            id: Connection identifier; URL-encoded.

        Returns:
            A :class:`ConnectionTestResult`.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server itself rejected the request.
            HonuaTransportError: The request failed at the transport layer.
        """
        connection_id = encode_path_segment(id)
        data = await self._request_json(
            "POST",
            f"/api/v1/admin/connections/{connection_id}/test",
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return ConnectionTestResult.from_dict(data)

    async def delete_connection(
        self,
        id: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        """Delete a stored secure connection.

        Args:
            id: Connection identifier; URL-encoded.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the delete.
            HonuaTransportError: The request failed at the transport layer.
        """
        connection_id = encode_path_segment(id)
        await self._request(
            "DELETE",
            f"/api/v1/admin/connections/{connection_id}",
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    async def validate_encryption(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> EncryptionValidationResult:
        """Verify that the server can decrypt every stored credential.

        Returns:
            An :class:`EncryptionValidationResult`.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        data = await self._request_json(
            "POST",
            "/api/v1/admin/connections/encryption/validate",
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return EncryptionValidationResult.from_dict(data)

    async def rotate_encryption_key(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> KeyRotationResult:
        """Rotate the server's connection-encryption key.

        Returns:
            A :class:`KeyRotationResult`.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the rotation request.
            HonuaTransportError: The request failed at the transport layer.
        """
        data = await self._request_json(
            "POST",
            "/api/v1/admin/connections/encryption/rotate-key",
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return KeyRotationResult.from_dict(data)

    # ======================================================================
    # Layers
    # ======================================================================

    async def list_layers(
        self,
        conn_id: str,
        service_name: str | None = None,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[PublishedLayerSummary]:
        """List published layers belonging to a connection.

        Args:
            conn_id: Connection identifier; URL-encoded.
            service_name: When provided, restrict to one service's layers.

        Returns:
            Matching :class:`PublishedLayerSummary` objects; empty when
            the server returns a non-list payload.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        connection_id = encode_path_segment(conn_id)
        params: dict[str, str] | None = None
        if service_name is not None:
            params = {"serviceName": service_name}
        data = await self._request_json(
            "GET",
            f"/api/v1/admin/connections/{connection_id}/layers",
            params=params,
            timeout=timeout,
            extra_headers=extra_headers,
        )
        if not isinstance(data, list):
            return []
        return [PublishedLayerSummary.from_dict(item) for item in data]

    async def publish_layer(
        self,
        conn_id: str,
        request: PublishLayerRequest,
        *,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> PublishedLayerSummary:
        """Publish a new layer derived from a stored connection.

        Args:
            conn_id: Connection identifier; URL-encoded.
            request: Layer-publication payload.
            idempotency_key: Stripe-style ``Idempotency-Key`` header value.
                When ``None`` and the underlying retry transport is
                configured to retry ``POST`` (i.e. the caller opted in via
                ``retry_methods``), a fresh ``uuid4`` hex is generated so
                that retries are de-duplicated server-side.

        Returns:
            A :class:`PublishedLayerSummary` describing the new layer.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the publish request.
            HonuaTransportError: The request failed at the transport layer.
        """
        connection_id = encode_path_segment(conn_id)
        data = await self._request_json(
            "POST",
            f"/api/v1/admin/connections/{connection_id}/layers",
            json_body=request.to_dict(),
            headers=self._idempotency_headers(idempotency_key),
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return PublishedLayerSummary.from_dict(data)

    async def set_layer_enabled(
        self,
        conn_id: str,
        layer_id: int,
        enabled: bool,
        service_name: str | None = None,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> PublishedLayerSummary:
        """Toggle whether a single published layer is enabled.

        Args:
            conn_id: Connection identifier; URL-encoded.
            layer_id: Numeric layer identifier.
            enabled: Desired ``enabled`` state.
            service_name: Optional service-scoped toggle.

        Returns:
            The refreshed :class:`PublishedLayerSummary`.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the toggle.
            HonuaTransportError: The request failed at the transport layer.
        """
        connection_id = encode_path_segment(conn_id)
        params: dict[str, str] | None = None
        if service_name is not None:
            params = {"serviceName": service_name}
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/connections/{connection_id}/layers/{layer_id}/enabled",
            json_body={"enabled": enabled},
            params=params,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return PublishedLayerSummary.from_dict(data)

    async def set_service_layers_enabled(
        self,
        conn_id: str,
        enabled: bool,
        service_name: str | None = None,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> list[PublishedLayerSummary]:
        """Toggle every layer on a connection (optionally per service) in bulk.

        Args:
            conn_id: Connection identifier; URL-encoded.
            enabled: Desired ``enabled`` state for every layer in scope.
            service_name: Optional per-service restriction.

        Returns:
            Refreshed :class:`PublishedLayerSummary` objects for every
            affected layer; empty when the server returns a non-list
            payload.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the bulk toggle.
            HonuaTransportError: The request failed at the transport layer.
        """
        connection_id = encode_path_segment(conn_id)
        params: dict[str, str] | None = None
        if service_name is not None:
            params = {"serviceName": service_name}
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/connections/{connection_id}/layers/enabled",
            json_body={"enabled": enabled},
            params=params,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        if not isinstance(data, list):
            return []
        return [PublishedLayerSummary.from_dict(item) for item in data]

    # ======================================================================
    # Discovery
    # ======================================================================

    async def discover_tables(
        self,
        conn_id: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> TableDiscoveryResponse:
        """Ask the server which tables are visible through a connection.

        Args:
            conn_id: Connection identifier; URL-encoded.

        Returns:
            A :class:`TableDiscoveryResponse`.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        connection_id = encode_path_segment(conn_id)
        data = await self._request_json(
            "GET",
            f"/api/v1/admin/connections/{connection_id}/tables",
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return TableDiscoveryResponse.from_dict(data)

    # ======================================================================
    # Styles
    # ======================================================================

    async def get_layer_style(
        self,
        layer_id: int,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> LayerStyleResponse:
        """Fetch the stored renderer / style document for a layer.

        Args:
            layer_id: Numeric layer identifier.

        Returns:
            A :class:`LayerStyleResponse`.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        data = await self._request_json(
            "GET",
            f"/api/v1/admin/metadata/layers/{layer_id}/style",
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return LayerStyleResponse.from_dict(data)

    async def update_layer_style(
        self,
        layer_id: int,
        request: LayerStyleUpdateRequest,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> LayerStyleResponse:
        """Replace the stored renderer / style document for a layer.

        Args:
            layer_id: Numeric layer identifier.
            request: The new renderer payload.

        Returns:
            A refreshed :class:`LayerStyleResponse`.

        Per-request options (``timeout`` / ``extra_headers`` /
        ``idempotency_key``) are forwarded to :meth:`_request`.

        Raises:
            HonuaHttpError: The server rejected the style update.
            HonuaTransportError: The request failed at the transport layer.
        """
        data = await self._request_json(
            "PUT",
            f"/api/v1/admin/metadata/layers/{layer_id}/style",
            json_body=request.to_dict(),
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
        return LayerStyleResponse.from_dict(data)

    # ======================================================================
    # Config
    # ======================================================================

    async def get_config(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Return the server's effective admin configuration block.

        Returns:
            The server-side admin config as a plain ``dict``; an empty
            ``dict`` when the server returns a non-mapping payload.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server responded with a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
        data = await self._request_json(
            "GET",
            "/api/v1/admin/config",
            timeout=timeout,
            extra_headers=extra_headers,
        )
        if isinstance(data, dict):
            return data
        return {}


def _merge_request_headers(
    headers: Mapping[str, str] | None,
    extra_headers: Mapping[str, str] | None,
    idempotency_key: str | None,
) -> dict[str, str] | None:
    """Merge per-request header overrides.

    Precedence (lowest → highest): ``extra_headers`` → ``headers`` →
    explicit ``idempotency_key``.
    """
    if headers is None and extra_headers is None and idempotency_key is None:
        return None
    merged: dict[str, str] = {}
    if extra_headers:
        merged.update(extra_headers)
    if headers:
        merged.update(headers)
    if idempotency_key is not None:
        merged["Idempotency-Key"] = idempotency_key
    return merged
