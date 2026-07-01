#!/usr/bin/env python3
"""Generate the synchronous client modules from their async source-of-truth.

The synchronous data-plane (:mod:`honua_sdk.client`) and control-plane
(:mod:`honua_admin._client`) clients are *near-perfect mirrors* of their async
counterparts: identical method names, signatures, docstrings, and control flow,
differing only by the mechanical sync/async transform (``async def`` → ``def``,
``await x`` → ``x``, ``async with`` → ``with``, the ``httpx.AsyncClient`` →
``httpx.Client`` family, and the ``Async*`` class/module names → their sync
equivalents).

To eliminate the long-lived hand-maintained duplication, the **async modules
are the single source of truth** and the sync modules are *generated* from them
by this script. The generated files are committed to the repository so that
``pip install`` never needs codegen and there is **no new runtime dependency**
(this is a dev-only tool — it is not in any package's dependency list, and the
``unasync`` package is intentionally not used).

Usage::

    python scripts/gen_sync.py            # rewrite the committed sync files
    python scripts/gen_sync.py --check    # fail if a sync file is stale

The ``--check`` mode regenerates each file in memory and compares it against the
committed version, exiting non-zero (with a diff) if they differ. CI runs this
mode so that editing an async source without regenerating its sync mirror fails
the build.

Whenever a sync/async pair drifts in a way this transform cannot express,
*reconcile the divergence in the async source* and extend the replacement table
below — never hand-edit a generated sync file (its header says as much).

In addition to the fully-generated file-pairs (``TARGETS``), the ``--check``
mode also guards the hand-maintained **intra-file sync/async twins**
(``TWIN_TARGETS``: the protocol / source / ogc / workflow / geoprocessing
facades, where a sync class lives next to its ``Async`` twin in one module).
Those twins are not whole-file generated — a few methods legitimately diverge in
their bodies beyond the mechanical transform — so :func:`check_twins` instead
verifies that both classes expose the *same method surface* (names + signatures,
modulo the async→sync transform), failing the build on any silent drift.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from re import Match

ROOT = Path(__file__).resolve().parents[1]

AUTO_GENERATED_BANNER = (
    "# AUTO-GENERATED from {source} by scripts/gen_sync.py "
    "— do not edit by hand.\n"
    "# Edit the async source-of-truth and run `python scripts/gen_sync.py`.\n"
)


@dataclass(frozen=True)
class Rule:
    """A single ordered text replacement.

    ``pattern`` is a compiled regex applied with :func:`re.Pattern.sub`;
    ``replacement`` is its substitution. Rules are applied in declaration
    order, so more specific rules must precede the general ones they would
    otherwise be clobbered by (e.g. ``Asynchronous`` → ``Synchronous`` must
    run before the generic ``\\bAsync`` → ```` strip).
    """

    pattern: re.Pattern[str]
    replacement: str | Callable[[Match[str]], str]

    def apply(self, text: str) -> str:
        return self.pattern.sub(self.replacement, text)


def _rule(
    pattern: str, replacement: str | Callable[[Match[str]], str]
) -> Rule:
    return Rule(re.compile(pattern), replacement)


# Ordered, exhaustive sync/async replacement table.
#
# Order matters. Specific rules come first; the broad ``\bAsync`` identifier
# strip comes last so it only fires on the residual ``Async*`` class names
# (``AsyncHonuaClient`` → ``HonuaClient`` etc.) after the typed/httpx/module
# special cases have already been handled.
_COMMON_RULES: tuple[Rule, ...] = (
    # --- prose (docstrings / comments / module summary) -------------------
    # ``Asynchronous`` / ``asynchronous`` must be rewritten before the generic
    # ``Async`` strip would corrupt them. Casing is preserved.
    _rule(r"\bAsynchronous\b", "Synchronous"),
    _rule(r"\basynchronous\b", "synchronous"),
    # ``Async counterpart to :class:`X`: <word>`` is async-only boilerplate
    # that describes the relationship to the sync class — meaningless in the
    # generated sync file. Strip the lead-in (which may wrap across a line)
    # and upper-case the first letter of the sentence it introduced, so e.g.
    # "Async counterpart to :class:`HonuaClient`: wraps the …" becomes
    # "Wraps the …". The ``\s+`` after the colon absorbs the line wrap +
    # docstring indentation.
    _rule(
        r"Async counterpart to :class:`[^`]+`:\s+([a-z])",
        lambda m: m.group(1).upper(),
    ),
    # Module-summary docstrings: ``"""Async ... API client ..."""``. The
    # leading ``Async `` (with a trailing space, so the generic Async-strip
    # below — which requires an immediately-following capital — does not fire)
    # is dropped from the one-line module docstring.
    _rule(r'^"""Async ', '"""'),
    # Residual async-flavoured prose inside docstrings that does NOT use the
    # ``async``/``await`` *keywords* (those are handled by the statement-level
    # rules below) but still describes async behaviour. These phrases are
    # wrong in the generated sync file.
    #
    # "an async <Thing>" / "the async <Thing>" → drop the adjective, fixing
    # the indefinite article to agree with the now-following word. The
    # source uses LETTER-based article agreement (e.g. "a WFS", "a STAC",
    # "an OGC", "an OData"), so the article is "an" iff the next word starts
    # with a vowel *letter* — which reproduces every hand-written sync case.
    _rule(
        r"\b([Aa])n? async (\w)",
        lambda m: (
            f"{m.group(1)}n {m.group(2)}"
            if m.group(2).lower() in "aeiou"
            else f"{m.group(1)} {m.group(2)}"
        ),
    ),
    _rule(r"\b([Tt])he async (\w)", r"\1he \2"),
    # Parenthetical "(async)" qualifier in summary lines — drop it (the sync
    # mirror simply omits it). Handles both " ... signals (async)." and
    # " ... request (async), ...".
    _rule(r"\s*\(async\)", ""),
    # "this coroutine is a no-op" → "this method is a no-op". Scope the
    # rewrite to the "... is a no-op" phrasing so we never touch a genuine
    # technical use of the word elsewhere.
    _rule(r"\bcoroutine is a no-op\b", "method is a no-op"),
    # "awaiting :meth:`x`" → "calling :meth:`x`" (the sync verb).
    _rule(r"\bawaiting (?=:meth:`)", "calling "),
    #
    # --- statement-level async syntax -------------------------------------
    _rule(r"\basync def\b", "def"),
    _rule(r"\basync with\b", "with"),
    _rule(r"\basync for\b", "for"),
    # Any *remaining* bare "async <lower-word>" adjective in prose (no leading
    # article) — e.g. "async iterator"/"async generator". Runs AFTER the
    # ``async def``/``with``/``for`` keyword rules above so it only ever fires
    # on residual prose, never on a control-flow keyword.
    _rule(r"\basync (?=[a-z])", ""),
    # ``await EXPR`` → ``EXPR``. Only strip the keyword + following space; this
    # leaves the awaited expression intact. ``await`` only ever appears as a
    # prefix operator in these modules.
    _rule(r"\bawait\s+", ""),
    #
    # --- dunder context-manager / iterator protocol -----------------------
    _rule(r"__aenter__", "__enter__"),
    _rule(r"__aexit__", "__exit__"),
    _rule(r"__aiter__", "__iter__"),
    _rule(r"__anext__", "__next__"),
    #
    # --- async stdlib / builtins ------------------------------------------
    # The retry-transport mirror imports ``asyncio`` for ``asyncio.sleep``; its
    # sync sibling imports ``time`` for ``time.sleep``. Rewrite the top-level
    # import before the ``asyncio.sleep`` → ``time.sleep`` call rewrite below.
    _rule(r"\bimport asyncio\b", "import time"),
    _rule(r"\basyncio\.sleep\b", "time.sleep"),
    # Any other ``asyncio.<attr>`` is unexpected in these facades; map the
    # module defensively so a stray reference becomes a clear sync error
    # rather than a silently-awaited coroutine. (No occurrences today.)
    _rule(r"\banext\(", "next("),
    _rule(r"\baiter\(", "iter("),
    #
    # --- typing constructs -------------------------------------------------
    _rule(r"\bAsyncIterator\b", "Iterator"),
    _rule(r"\bAsyncIterable\b", "Iterable"),
    _rule(r"\bAsyncGenerator\b", "Generator"),
    _rule(r"\bAsyncContextManager\b", "ContextManager"),
    # ``Awaitable[T]`` → ``T`` (unwrap the awaitable). Handles a single level
    # of bracket nesting in the inner type, which is all the public surface
    # uses. (No occurrences today, but kept for completeness/safety.)
    _rule(r"\bAwaitable\[((?:[^\[\]]|\[[^\[\]]*\])*)\]", r"\1"),
    #
    # --- httpx async surface ----------------------------------------------
    # Handled by the generic ``\bAsync`` strip below
    # (AsyncClient → Client, AsyncBaseTransport → BaseTransport,
    # AsyncHTTPTransport → HTTPTransport), but the resource-close method is
    # distinct and must be mapped explicitly.
    _rule(r"\baclose\b", "close"),
    # The async response/transport read + dispatch entry points have distinct
    # names from their sync counterparts (``aread`` → ``read``,
    # ``handle_async_request`` → ``handle_request``); the generic ``Async``
    # strip never fires on these all-lowercase identifiers.
    _rule(r"\baread\b", "read"),
    _rule(r"\bhandle_async_request\b", "handle_request"),
    #
    # --- function-name seams ----------------------------------------------
    # The async client uses the awaitable auth-application helper; its sync
    # mirror calls the synchronous one. The ``_async`` suffix is lowercase and
    # underscore-prefixed, so the generic ``\bAsync`` strip never fires on it.
    _rule(
        r"\b_apply_sensitive_auth_headers_async\b",
        "_apply_sensitive_auth_headers",
    ),
    # honua-admin imports the public (non-underscore) async applier from
    # ``honua_sdk.http`` and awaits it; its generated sync mirror calls the
    # synchronous public applier. Matched separately from the underscore rule
    # above (whose ``\b_`` prefix never fires on the public name).
    _rule(
        r"\bapply_sensitive_auth_headers_async\b",
        "apply_sensitive_auth_headers",
    ),
    #
    # --- module-name seams -------------------------------------------------
    # Async-only sibling modules collapse onto their sync equivalents.
    _rule(r"\b_async_retry\b", "_retry"),
    _rule(r"\basync_geocoding\b", "geocoding"),
    # The gRPC client class embeds ``Async`` mid-identifier
    # (``HonuaGrpcAsyncClient``), so the generic ``\bAsync`` strip below — which
    # requires a word boundary immediately before ``Async`` — never fires on it.
    # Map it explicitly to its sync sibling.
    _rule(r"\bHonuaGrpcAsyncClient\b", "HonuaGrpcClient"),
    #
    # --- residual Async-prefixed identifiers ------------------------------
    # Everything left — the ``Async*`` client/transport/protocol class names
    # (AsyncHonuaClient → HonuaClient, AsyncSource → Source,
    # AsyncRetryTransport → RetryTransport, AsyncClient → Client, …). The word
    # boundary keeps it from touching substrings inside larger identifiers.
    _rule(r"\bAsync(?=[A-Z])", ""),
)


@dataclass(frozen=True)
class Target:
    """One async-source → generated-sync mapping."""

    source: Path
    dest: Path
    rules: tuple[Rule, ...] = field(default=_COMMON_RULES)

    @property
    def source_rel(self) -> str:
        return self.source.relative_to(ROOT).as_posix()

    @property
    def dest_rel(self) -> str:
        return self.dest.relative_to(ROOT).as_posix()


TARGETS: tuple[Target, ...] = (
    Target(
        source=ROOT / "packages/honua-sdk/honua_sdk/async_client.py",
        dest=ROOT / "packages/honua-sdk/honua_sdk/client.py",
    ),
    Target(
        source=ROOT / "packages/honua-sdk/honua_sdk/async_geocoding.py",
        dest=ROOT / "packages/honua-sdk/honua_sdk/geocoding.py",
    ),
    Target(
        source=ROOT / "packages/honua-sdk/honua_sdk/_async_retry.py",
        dest=ROOT / "packages/honua-sdk/honua_sdk/_retry.py",
    ),
    Target(
        source=ROOT / "packages/honua-admin/honua_admin/_async_client.py",
        dest=ROOT / "packages/honua-admin/honua_admin/_client.py",
    ),
)


# ---------------------------------------------------------------------------
# Intra-file sync/async twin guard (AUD-160/161, issue #129)
# ---------------------------------------------------------------------------
#
# The ``TARGETS`` above cover the async→sync *file-pair* mirrors, which are
# fully generated. A second family of sync/async duplication lives *inside a
# single module*: the protocol / source / ogc / workflow / geoprocessing
# facades each ship a hand-written sync class next to its ``Async`` twin
# (``Source``/``AsyncSource``, ``WfsClient``/``AsyncWfsClient``, …). These are
# NOT whole-file generated because a handful of methods legitimately diverge in
# their *bodies* beyond the mechanical transform (e.g. ``anyio.to_thread`` for
# blocking file I/O in ``geoservices``; ``asyncio.CancelledError`` handling in
# ``geoprocessing``). They can therefore still silently drift in their *public
# surface* — a method or parameter added to one twin but not the other.
#
# The guard below closes that gap: for every registered twin pair it verifies
# that the two classes expose the **same set of methods with the same
# signatures** (modulo the mechanical async→sync transform). Signatures are
# normalized via :func:`ast.unparse` so formatting/whitespace never matters —
# only the actual method surface. This runs as part of ``gen_sync.py --check``
# (CI), so a divergent twin fails the build exactly like a stale file-pair.
#
# Twin classes are *not* rewritten by ``gen_sync.py`` (unlike ``TARGETS``);
# they remain hand-maintained. The guard only *verifies* parity.

# Extra replacements needed for the intra-file twins whose sync/async seam is
# an *infix* ``Sync``/``Async`` (not the leading ``Async`` prefix handled by
# ``_COMMON_RULES``): the typed request protocols and the shared protocol base.
_TWIN_EXTRA_RULES: tuple[Rule, ...] = (
    _rule(r"\bSupportsAsync", "SupportsSync"),
    _rule(r"\b_AsyncProtocol\b", "_SyncProtocol"),
)
_TWIN_RULES: tuple[Rule, ...] = _COMMON_RULES + _TWIN_EXTRA_RULES

_SDK_ROOT = ROOT / "packages/honua-sdk/honua_sdk"


@dataclass(frozen=True)
class Twin:
    """A module holding hand-maintained sync/async twin classes to keep in lockstep.

    ``pairs`` maps each ``async_class`` name to its ``sync_class`` name within
    ``source``. The guard checks that the two classes expose an identical
    method surface once the async names/signatures are mechanically transformed.
    """

    source: Path
    pairs: tuple[tuple[str, str], ...]

    @property
    def source_rel(self) -> str:
        return self.source.relative_to(ROOT).as_posix()


TWIN_TARGETS: tuple[Twin, ...] = (
    Twin(
        _SDK_ROOT / "source.py",
        (("AsyncSourceClientProtocol", "SourceClientProtocol"), ("AsyncSource", "Source")),
    ),
    Twin(
        _SDK_ROOT / "ogc.py",
        (
            ("AsyncHonuaOgcFeatures", "HonuaOgcFeatures"),
            ("AsyncHonuaOgcFeatureCollection", "HonuaOgcFeatureCollection"),
        ),
    ),
    Twin(_SDK_ROOT / "workflow.py", (("AsyncHonuaWorkflow", "HonuaWorkflow"),)),
    Twin(_SDK_ROOT / "geoprocessing.py", (("AsyncHonuaGeoprocessing", "HonuaGeoprocessing"),)),
    Twin(_SDK_ROOT / "protocols/_base.py", (("_AsyncProtocol", "_SyncProtocol"),)),
    Twin(
        _SDK_ROOT / "protocols/geoservices.py",
        (
            ("AsyncGeoServicesFeatureServerClient", "GeoServicesFeatureServerClient"),
            ("AsyncGeoServicesMapServerClient", "GeoServicesMapServerClient"),
            ("AsyncGeoServicesImageServerClient", "GeoServicesImageServerClient"),
            ("AsyncGeoServicesGeometryServerClient", "GeoServicesGeometryServerClient"),
        ),
    ),
    Twin(_SDK_ROOT / "protocols/odata.py", (("AsyncODataClient", "ODataClient"),)),
    Twin(
        _SDK_ROOT / "protocols/ogc_extras.py",
        (
            ("AsyncOgcMapsClient", "OgcMapsClient"),
            ("AsyncOgcTilesClient", "OgcTilesClient"),
            ("AsyncOgcCoveragesClient", "OgcCoveragesClient"),
            ("AsyncOgcProcessesClient", "OgcProcessesClient"),
            ("AsyncOgcRecordsClient", "OgcRecordsClient"),
            ("AsyncOgcRecordsCollectionClient", "OgcRecordsCollectionClient"),
        ),
    ),
    Twin(
        _SDK_ROOT / "protocols/scenes.py",
        (("AsyncSceneClient", "SceneClient"), ("AsyncElevationClient", "ElevationClient")),
    ),
    Twin(_SDK_ROOT / "protocols/stac.py", (("AsyncStacClient", "StacClient"),)),
    Twin(_SDK_ROOT / "protocols/wfs.py", (("AsyncWfsClient", "WfsClient"),)),
    Twin(_SDK_ROOT / "protocols/wms.py", (("AsyncWmsClient", "WmsClient"),)),
    Twin(_SDK_ROOT / "protocols/wmts.py", (("AsyncWmtsClient", "WmtsClient"),)),
)


def _transform_twin(text: str) -> str:
    for rule in _TWIN_RULES:
        text = rule.apply(text)
    return text


def _class_def(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise KeyError(name)


def _twin_method_surface(node: ast.ClassDef) -> dict[str, str]:
    """Map each method name to a normalized ``name(args) -> return`` signature."""
    surface: dict[str, str] = {}
    for child in node.body:
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            args = ast.unparse(child.args)
            returns = ast.unparse(child.returns) if child.returns is not None else ""
            surface[child.name] = f"{child.name}({args}) -> {returns}"
    return surface


def check_twins() -> list[str]:
    """Return a list of drift messages for the intra-file sync/async twins.

    Each pair passes when the async class, once mechanically transformed to its
    sync form, exposes exactly the sync class's method surface.
    """
    problems: list[str] = []
    for twin in TWIN_TARGETS:
        tree = ast.parse(twin.source.read_text(encoding="utf-8"))
        for async_name, sync_name in twin.pairs:
            try:
                async_node = _class_def(tree, async_name)
                sync_node = _class_def(tree, sync_name)
            except KeyError as exc:
                problems.append(f"{twin.source_rel}: missing twin class {exc}")
                continue
            sync_surface = _twin_method_surface(sync_node)
            async_surface = {
                # Transform the whole ``name(args) -> ret`` signature so that
                # async-only dunder names (``__aenter__`` → ``__enter__``) and
                # async return types (``AsyncIterator`` → ``Iterator``) line up.
                sig.split("(", 1)[0]: sig
                for sig in (
                    _transform_twin(raw)
                    for raw in _twin_method_surface(async_node).values()
                )
            }
            only_async = sorted(set(async_surface) - set(sync_surface))
            only_sync = sorted(set(sync_surface) - set(async_surface))
            if only_async:
                problems.append(
                    f"{twin.source_rel}: {async_name} has method(s) missing from "
                    f"{sync_name}: {only_async}"
                )
            if only_sync:
                problems.append(
                    f"{twin.source_rel}: {sync_name} has method(s) missing from "
                    f"{async_name}: {only_sync}"
                )
            for name in sorted(set(async_surface) & set(sync_surface)):
                if async_surface[name] != sync_surface[name]:
                    problems.append(
                        f"{twin.source_rel}: signature drift in {name}()\n"
                        f"    {sync_name}: {sync_surface[name]}\n"
                        f"    {async_name}: {async_surface[name]}"
                    )
    return problems


def _ruff_fix_imports(text: str, dest: Path) -> str:
    """Re-sort imports in the generated source via ``ruff``.

    The async and sync sibling-module import names sort to different positions
    (e.g. ``from ._async_retry import AsyncRetryTransport`` sits before
    ``_http`` while ``from ._retry import RetryTransport`` sorts after
    ``_query_dispatch``). Rather than encode brittle positional edits, run
    ruff's import-sorter (rule family ``I``) over the transformed text. ruff is
    a dev/CI tool already required by this repo; it is **not** a runtime
    dependency of any package.
    """
    proc = subprocess.run(
        [
            "ruff",
            "check",
            "--select",
            "I",
            "--fix",
            "--quiet",
            "--stdin-filename",
            str(dest),
            "-",
        ],
        input=text,
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    # ruff exits non-zero when it could not auto-fix everything; with only the
    # import-sort rule selected and well-formed input that should not happen.
    if proc.returncode not in (0, 1):
        sys.stderr.write(proc.stderr)
        raise SystemExit(
            f"ruff import-sort failed for {dest} (exit {proc.returncode})"
        )
    return proc.stdout


def _transform(target: Target) -> str:
    source_text = target.source.read_text(encoding="utf-8")

    # Apply the ordered replacement table to the body.
    body = source_text
    for rule in target.rules:
        body = rule.apply(body)

    # Insert the auto-generated banner *after* the module docstring so the
    # docstring remains ``__doc__``. The async source always opens with a
    # triple-quoted one-line module docstring on line 1.
    banner = AUTO_GENERATED_BANNER.format(source=target.source_rel)
    lines = body.splitlines(keepends=True)
    insert_at = _docstring_end_index(lines)
    rebuilt = "".join(lines[:insert_at]) + banner + "".join(lines[insert_at:])

    return _ruff_fix_imports(rebuilt, target.dest)


def _docstring_end_index(lines: list[str]) -> int:
    """Index of the first line *after* the module docstring.

    Supports a single-line triple-quoted docstring (the convention used by
    both async sources) and a multi-line one. Returns ``0`` when there is no
    leading module docstring.
    """
    if not lines:
        return 0
    first = lines[0].lstrip()
    for quote in ('"""', "'''"):
        if first.startswith(quote):
            # Single-line docstring: closing quotes on the same line.
            if first.rstrip().endswith(quote) and len(first.strip()) >= 2 * len(quote):
                return 1
            # Multi-line: scan for the closing delimiter.
            for idx in range(1, len(lines)):
                if quote in lines[idx]:
                    return idx + 1
            return len(lines)
    return 0


def generate(target: Target) -> str:
    return _transform(target)


def write_all() -> None:
    for target in TARGETS:
        generated = generate(target)
        target.dest.write_text(generated, encoding="utf-8")
        print(f"wrote {target.dest_rel} (from {target.source_rel})")


def check_all() -> int:
    stale: list[str] = []
    for target in TARGETS:
        generated = generate(target)
        current = target.dest.read_text(encoding="utf-8")
        if generated != current:
            stale.append(target.dest_rel)
            diff = difflib.unified_diff(
                current.splitlines(keepends=True),
                generated.splitlines(keepends=True),
                fromfile=f"{target.dest_rel} (committed)",
                tofile=f"{target.dest_rel} (regenerated)",
            )
            sys.stderr.writelines(diff)

    twin_problems = check_twins()

    if stale:
        sys.stderr.write(
            "\nStale generated sync file(s): "
            + ", ".join(stale)
            + "\nRun `python scripts/gen_sync.py` and commit the result.\n"
        )
    if twin_problems:
        sys.stderr.write(
            "\nSync/async twin drift (intra-file mirrors, issue #129):\n"
            + "\n".join(f"  - {problem}" for problem in twin_problems)
            + "\nReconcile the divergent twin so both classes expose the same "
            "method surface.\n"
        )
    if stale or twin_problems:
        return 1
    print("Generated sync files are up to date; sync/async twins are in lockstep.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed sync files match the async sources; "
        "exit non-zero (with a diff) if any is stale.",
    )
    args = parser.parse_args(argv)
    if args.check:
        return check_all()
    write_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
