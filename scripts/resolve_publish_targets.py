"""Resolve a Python package publication to exact release tags and commits."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib


@dataclass(frozen=True)
class PackageSpec:
    """The release and workflow coordinates for one public distribution."""

    key: str
    distribution: str
    pyproject: Path
    tag_prefix: str


PACKAGE_SPECS: tuple[PackageSpec, ...] = (
    PackageSpec(
        key="sdk",
        distribution="honua-sdk",
        pyproject=Path("packages/honua-sdk/pyproject.toml"),
        tag_prefix="python-sdk-v",
    ),
    PackageSpec(
        key="admin",
        distribution="honua-admin",
        pyproject=Path("packages/honua-admin/pyproject.toml"),
        tag_prefix="python-admin-v",
    ),
)


@dataclass(frozen=True)
class PublishPlan:
    """A fully validated build/publication plan."""

    release_sha: str
    selected: tuple[str, ...]
    publish: bool
    versions: Mapping[str, str]
    tags: Mapping[str, str]

    @property
    def should_build(self) -> bool:
        return bool(self.selected)


def _requested_keys(requested_package: str) -> tuple[str, ...]:
    if requested_package == "both":
        return tuple(spec.key for spec in PACKAGE_SPECS)
    for spec in PACKAGE_SPECS:
        if spec.distribution == requested_package:
            return (spec.key,)
    valid = ", ".join([spec.distribution for spec in PACKAGE_SPECS] + ["both"])
    raise ValueError(f"Unknown package selection {requested_package!r}; expected one of: {valid}.")


def plan_publish(
    *,
    event_name: str,
    release_sha: str,
    versions: Mapping[str, str],
    tag_commits: Mapping[str, str | None],
    release_is_trunk_ancestor: bool,
    requested_package: str = "both",
    dry_run: bool = True,
    release_tag: str = "",
    workflow_ref: str = "",
) -> PublishPlan:
    """Build a plan and reject any ambiguous production publication.

    ``tag_commits`` maps each expected package tag to its peeled commit SHA.
    A missing tag is represented by ``None``.
    """
    if not release_sha:
        raise ValueError("The checked-out release commit SHA is empty.")

    tags = {
        spec.key: f"{spec.tag_prefix}{versions[spec.key]}" for spec in PACKAGE_SPECS
    }

    if event_name == "workflow_run":
        if not release_is_trunk_ancestor:
            raise ValueError(f"Release commit {release_sha} is not an ancestor of origin/trunk.")
        selected = tuple(
            spec.key for spec in PACKAGE_SPECS if tag_commits.get(tags[spec.key]) == release_sha
        )
        return PublishPlan(
            release_sha=release_sha,
            selected=selected,
            publish=bool(selected),
            versions=versions,
            tags=tags,
        )

    if event_name != "workflow_dispatch":
        raise ValueError(f"Unsupported publication event {event_name!r}.")

    selected = _requested_keys(requested_package)
    if dry_run:
        return PublishPlan(
            release_sha=release_sha,
            selected=selected,
            publish=False,
            versions=versions,
            tags=tags,
        )

    if workflow_ref != "refs/heads/trunk":
        raise ValueError("A non-dry manual publication must dispatch the workflow from trunk.")
    if not release_tag:
        raise ValueError("A non-dry manual publication requires an exact release_tag input.")
    if not release_is_trunk_ancestor:
        raise ValueError(f"Release commit {release_sha} is not an ancestor of origin/trunk.")
    if release_tag not in {tags[key] for key in selected}:
        expected = ", ".join(tags[key] for key in selected)
        raise ValueError(f"release_tag {release_tag!r} does not match the selection ({expected}).")

    for key in selected:
        tag = tags[key]
        tag_commit = tag_commits.get(tag)
        if tag_commit is None:
            raise ValueError(f"Required release tag {tag!r} does not exist.")
        if tag_commit != release_sha:
            raise ValueError(f"Tag {tag!r} does not resolve to release commit {release_sha}.")

    return PublishPlan(
        release_sha=release_sha,
        selected=selected,
        publish=True,
        versions=versions,
        tags=tags,
    )


def _tag_commit(workspace: Path, tag: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _resolve_commit(workspace: Path, target_ref: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{target_ref}^{{commit}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _is_ancestor(workspace: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(workspace), "merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise subprocess.CalledProcessError(
        result.returncode,
        result.args,
        output=result.stdout,
        stderr=result.stderr,
    )


def _package_version_at_commit(workspace: Path, release_sha: str, spec: PackageSpec) -> str:
    result = subprocess.run(
        ["git", "-C", str(workspace), "show", f"{release_sha}:{spec.pyproject.as_posix()}"],
        check=True,
        capture_output=True,
        text=True,
    )
    data = tomllib.loads(result.stdout)
    try:
        version = data["project"]["version"]
    except KeyError as exc:
        raise ValueError(f"{spec.pyproject} is missing project.version at {release_sha}.") from exc
    if not isinstance(version, str) or not version:
        raise ValueError(f"{spec.pyproject} project.version must be a non-empty string.")
    return version


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"Expected true or false, received {value!r}.")


def _write_github_outputs(path: Path, plan: PublishPlan) -> None:
    outputs = {
        "release_sha": plan.release_sha,
        "should_build": str(plan.should_build).lower(),
        "publish": str(plan.publish).lower(),
    }
    for spec in PACKAGE_SPECS:
        outputs[spec.key] = str(spec.key in plan.selected).lower()
        outputs[f"{spec.key}_version"] = plan.versions[spec.key]
        outputs[f"{spec.key}_tag"] = plan.tags[spec.key]
    with path.open("a", encoding="utf-8") as output_file:
        for key, value in outputs.items():
            output_file.write(f"{key}={value}\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--target-ref", default="HEAD")
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--workflow-ref", default="")
    parser.add_argument("--package", default="both")
    parser.add_argument("--dry-run", default="true")
    parser.add_argument("--release-tag", default="")
    parser.add_argument(
        "--github-output",
        type=Path,
        default=Path(os.environ["GITHUB_OUTPUT"]) if "GITHUB_OUTPUT" in os.environ else None,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        workspace = args.workspace.resolve()
        release_sha = _resolve_commit(workspace, args.target_ref)
        versions = {
            spec.key: _package_version_at_commit(workspace, release_sha, spec)
            for spec in PACKAGE_SPECS
        }
        tags = {
            spec.key: f"{spec.tag_prefix}{versions[spec.key]}" for spec in PACKAGE_SPECS
        }
        tag_commits = {tag: _tag_commit(workspace, tag) for tag in tags.values()}
        plan = plan_publish(
            event_name=args.event_name,
            release_sha=release_sha,
            versions=versions,
            tag_commits=tag_commits,
            release_is_trunk_ancestor=_is_ancestor(
                workspace, release_sha, "refs/remotes/origin/trunk"
            ),
            requested_package=args.package,
            dry_run=_parse_bool(args.dry_run),
            release_tag=args.release_tag,
            workflow_ref=args.workflow_ref,
        )
        if args.github_output is not None:
            _write_github_outputs(args.github_output, plan)
        print(
            json.dumps(
                {
                    "release_sha": plan.release_sha,
                    "selected": list(plan.selected),
                    "publish": plan.publish,
                    "versions": plan.versions,
                    "tags": plan.tags,
                },
                sort_keys=True,
            )
        )
    except (KeyError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
