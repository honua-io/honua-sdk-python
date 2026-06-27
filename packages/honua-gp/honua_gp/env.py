"""arcpy.env shim -- module-level attributes mirrored to the session."""

from __future__ import annotations

from typing import Any

from ._session import get_session


class _EnvProxy:
    """Attribute proxy that mirrors writes to the global session."""

    __slots__ = ()

    _ALIASES: dict[str, str] = {
        "workspace": "workspace",
        "scratchWorkspace": "scratch_workspace",
        "outputCoordinateSystem": "output_coordinate_system",
        "overwriteOutput": "overwrite_output",
        "parallelProcessingFactor": "parallel_processing_factor",
    }

    def __getattr__(self, name: str) -> Any:
        session = get_session()
        if name in self._ALIASES:
            return getattr(session, self._ALIASES[name])
        if name in session.extra_env_options:
            return session.extra_env_options[name]
        return None  # arcpy.env returns None for unset attributes.

    def __setattr__(self, name: str, value: Any) -> None:
        session = get_session()
        if name in self._ALIASES:
            setattr(session, self._ALIASES[name], value)
            return
        # Unknown env attributes are accepted to keep customer scripts running;
        # they are stored on ``extra_env_options`` (NOT ``extra_client_options``)
        # so common legacy writes like ``arcpy.env.extent`` cannot leak into
        # the ``HonuaClient(**kwargs)`` constructor and trip its closed
        # keyword signature with ``TypeError``.
        session.extra_env_options[name] = value

    def __dir__(self) -> list[str]:
        return sorted((*self._ALIASES, *get_session().extra_env_options))


workspace = None  # type: ignore[assignment]  # placeholder for IDE introspection only
scratchWorkspace = None  # type: ignore[assignment]
outputCoordinateSystem = None  # type: ignore[assignment]
overwriteOutput = False  # type: ignore[assignment]
parallelProcessingFactor: str | None = None  # type: ignore[assignment]


# Real arcpy exposes ``arcpy.env`` as a module-like attribute that supports
# attribute set/get. The proxy instance mirrors that semantics.
env = _EnvProxy()


__all__ = ["env"]
