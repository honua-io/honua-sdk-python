"""Module-global session shared by the shim functions and ``arcpy.env``.

The session carries:

* The configured Honua / Admin / OGC Processes clients.
* The mirrored ``arcpy.env`` attributes (``workspace``, ``outputCoordinateSystem``,
  ``overwriteOutput``, ``parallelProcessingFactor``, ``scratchWorkspace``).
* A cache of ``MakeFeatureLayer`` / ``MakeTableView`` aliases.
* The active ``AuditWriter`` instance.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any

from ._audit import AuditWriter, default_writer
from ._errors import HonuaGpConfigurationError


@dataclass
class LayerAlias:
    """In-process layer/table alias created by MakeFeatureLayer / MakeTableView."""

    name: str
    source: str
    where: str | None = None
    field_info: Any | None = None
    selection: dict[str, Any] = field(default_factory=dict)
    workspace: str | None = None
    kind: str = "layer"


@dataclass
class HonuaSession:
    """Session-scoped runtime state."""

    base_url: str | None = None
    api_key: str | None = None
    bearer_token: str | None = None
    workspace: str | None = None
    overwrite_output: bool = False
    output_coordinate_system: Any | None = None
    parallel_processing_factor: str | None = None
    scratch_workspace: str | None = None
    extra_client_options: dict[str, Any] = field(default_factory=dict)
    """Extra ``**kwargs`` to forward into the underlying ``HonuaClient`` /
    ``HonuaAdminClient`` constructors. Populated only by
    ``configure(..., **client_kwargs)``; the env proxy stashes unknown
    ``arcpy.env`` attributes in :attr:`extra_env_options` so they never
    reach the SDK constructor."""

    extra_env_options: dict[str, Any] = field(default_factory=dict)
    """Spillover bag for unknown ``arcpy.env.*`` writes (e.g.
    ``arcpy.env.extent``). These are accepted to keep legacy scripts
    importing without ``AttributeError`` but never forwarded to
    ``HonuaClient`` / ``HonuaAdminClient`` -- those constructors have a
    closed keyword signature and would raise ``TypeError`` on unknown
    arguments."""

    _client: Any = field(default=None, repr=False)
    _admin: Any = field(default=None, repr=False)
    _processes: Any = field(default=None, repr=False)
    _layers: dict[str, LayerAlias] = field(default_factory=dict, repr=False)
    _audit_writer: AuditWriter | None = field(default=None, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def configure(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        bearer_token: str | None = None,
        client: Any | None = None,
        admin_client: Any | None = None,
        processes_client: Any | None = None,
        **client_kwargs: Any,
    ) -> None:
        """Configure the session.

        Any of ``client``, ``admin_client``, ``processes_client`` can be
        passed in for testing or to wire pre-authenticated clients. When
        omitted, the session lazily constructs sync clients from
        ``base_url`` + auth using ``honua_sdk.HonuaClient`` and
        ``honua_admin.HonuaAdminClient``.

        When the connection settings (``base_url``, ``api_key``,
        ``bearer_token``, or extra ``**client_kwargs``) change, any
        previously cached clients are dropped so the next ``client()``
        / ``admin_client()`` / ``processes_client()`` accessor rebuilds
        against the new settings. Explicit ``client=`` / ``admin_client=``
        / ``processes_client=`` arguments are applied *after* this
        invalidation, so they still win in the same call.
        """

        with self._lock:
            connection_changed = False
            if base_url is not None and base_url != self.base_url:
                self.base_url = base_url
                connection_changed = True
            if api_key is not None and api_key != self.api_key:
                self.api_key = api_key
                connection_changed = True
            if bearer_token is not None and bearer_token != self.bearer_token:
                self.bearer_token = bearer_token
                connection_changed = True
            if client_kwargs:
                extra_client_options = {**self.extra_client_options, **client_kwargs}
                if extra_client_options != self.extra_client_options:
                    self.extra_client_options = extra_client_options
                    connection_changed = True
            if connection_changed:
                # Connection settings shifted; drop cached clients so the next
                # accessor call rebuilds against the new endpoint / auth.
                # Without this, a previously-built client keeps using the
                # old base_url / api_key after a reconfigure.
                self._client = None
                self._admin = None
                self._processes = None
            if client is not None:
                self._client = client
                self._processes = None  # rebuild from client
            if admin_client is not None:
                self._admin = admin_client
            if processes_client is not None:
                self._processes = processes_client

    def configure_from_env(self) -> None:
        """Pick up ``HONUA_BASE_URL`` / ``HONUA_API_KEY`` / ``HONUA_BEARER_TOKEN``."""

        base_url = os.environ.get("HONUA_BASE_URL")
        api_key = os.environ.get("HONUA_API_KEY")
        bearer = os.environ.get("HONUA_BEARER_TOKEN")
        if base_url:
            self.configure(base_url=base_url, api_key=api_key, bearer_token=bearer)

    # ------------------------------------------------------------------
    # Client accessors (lazy)
    # ------------------------------------------------------------------

    def client(self) -> Any:
        with self._lock:
            if self._client is None:
                self._client = self._build_client()
            return self._client

    def admin_client(self) -> Any:
        with self._lock:
            if self._admin is None:
                self._admin = self._build_admin_client()
            return self._admin

    def processes_client(self) -> Any:
        with self._lock:
            if self._processes is None:
                client = self.client()
                if not hasattr(client, "ogc_processes"):
                    raise HonuaGpConfigurationError(
                        "Configured Honua client does not expose OGC Processes."
                    )
                self._processes = client.ogc_processes()
            return self._processes

    def audit_writer(self) -> AuditWriter:
        return self._audit_writer or default_writer()

    def set_audit_writer(self, writer: AuditWriter | None) -> None:
        self._audit_writer = writer

    # ------------------------------------------------------------------
    # Layer aliases
    # ------------------------------------------------------------------

    def register_layer(self, alias: LayerAlias) -> LayerAlias:
        with self._lock:
            if not self.overwrite_output and alias.name in self._layers:
                raise HonuaGpConfigurationError(
                    f"Layer alias {alias.name!r} already exists; set arcpy.env.overwriteOutput = True to replace."
                )
            self._layers[alias.name] = alias
            return alias

    def get_layer(self, name: str) -> LayerAlias | None:
        with self._lock:
            return self._layers.get(name)

    def resolve_layer_or_source(self, name: str) -> str:
        """Return the underlying source string for an alias, or the input if none registered."""

        alias = self.get_layer(name)
        if alias is None:
            return name
        return alias.source

    def remove_layer(self, name: str) -> bool:
        with self._lock:
            return self._layers.pop(name, None) is not None

    def list_layers(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._layers))

    def reset(self) -> None:
        with self._lock:
            self.base_url = None
            self.api_key = None
            self.bearer_token = None
            self.workspace = None
            self.overwrite_output = False
            self.output_coordinate_system = None
            self.parallel_processing_factor = None
            self.scratch_workspace = None
            self.extra_client_options = {}
            self.extra_env_options = {}
            self._client = None
            self._admin = None
            self._processes = None
            self._layers = {}
            self._audit_writer = None

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build_client(self) -> Any:
        if not self.base_url:
            raise HonuaGpConfigurationError(
                "honua_gp is not configured; call honua_gp.configure(base_url=...) "
                "or set the HONUA_BASE_URL environment variable."
            )
        from honua_sdk import HonuaClient  # local import: keeps shim importable without an env

        kwargs: dict[str, Any] = dict(self.extra_client_options)
        if self.api_key is not None:
            kwargs.setdefault("api_key", self.api_key)
        if self.bearer_token is not None:
            kwargs.setdefault("bearer_token", self.bearer_token)
        return HonuaClient(self.base_url, **kwargs)

    def _build_admin_client(self) -> Any:
        if not self.base_url:
            raise HonuaGpConfigurationError(
                "honua_gp is not configured; call honua_gp.configure(base_url=...) "
                "or set the HONUA_BASE_URL environment variable."
            )
        from honua_admin import HonuaAdminClient

        # Mirror ``_build_client``: start from ``extra_client_options`` so
        # ``configure(..., transport=..., timeout=..., auth_provider=...,
        # follow_redirects=..., max_retries=...)`` reaches both the data and
        # admin clients. Without this, the admin client silently dropped every
        # kwarg the docs promised would forward.
        kwargs: dict[str, Any] = dict(self.extra_client_options)
        if self.api_key is not None:
            kwargs.setdefault("api_key", self.api_key)
        if self.bearer_token is not None:
            kwargs.setdefault("bearer_token", self.bearer_token)
        return HonuaAdminClient(self.base_url, **kwargs)


_SESSION = HonuaSession()


def get_session() -> HonuaSession:
    return _SESSION


__all__ = [
    "HonuaSession",
    "LayerAlias",
    "get_session",
]
