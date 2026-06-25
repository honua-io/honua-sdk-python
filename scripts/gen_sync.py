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
"""

from __future__ import annotations

import argparse
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
    #
    # --- module-name seams -------------------------------------------------
    # Async-only sibling modules collapse onto their sync equivalents.
    _rule(r"\b_async_retry\b", "_retry"),
    _rule(r"\basync_geocoding\b", "geocoding"),
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
        source=ROOT / "packages/honua-admin/honua_admin/_async_client.py",
        dest=ROOT / "packages/honua-admin/honua_admin/_client.py",
    ),
)


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
    if stale:
        sys.stderr.write(
            "\nStale generated sync file(s): "
            + ", ".join(stale)
            + "\nRun `python scripts/gen_sync.py` and commit the result.\n"
        )
        return 1
    print("Generated sync files are up to date.")
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
