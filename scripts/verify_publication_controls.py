"""Fail closed unless GitHub publication environments and tag rules are protected."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any


class PublicationControlError(RuntimeError):
    """Raised when a required external publication control is absent."""


def validate_environment(payload: Mapping[str, Any], expected_name: str) -> None:
    """Require an existing environment limited to protected branches."""
    if payload.get("name") != expected_name:
        raise PublicationControlError(f"GitHub environment {expected_name!r} is missing or mismatched.")

    policy = payload.get("deployment_branch_policy")
    if not isinstance(policy, Mapping) or policy.get("protected_branches") is not True:
        raise PublicationControlError(
            f"GitHub environment {expected_name!r} must use 'Protected branches only' before publication."
        )
    if policy.get("custom_branch_policies") is not False:
        raise PublicationControlError(
            f"GitHub environment {expected_name!r} must not permit custom deployment branch policies."
        )
    if payload.get("can_admins_bypass") is not False:
        raise PublicationControlError(
            f"GitHub environment {expected_name!r} must not allow administrators to bypass protection rules."
        )


def validate_trunk_branch(payload: Mapping[str, Any]) -> None:
    """Require the ordinary branch response to report trunk as protected."""
    if payload.get("name") != "trunk" or payload.get("protected") is not True:
        raise PublicationControlError("The trunk branch must remain protected before publication.")


def validate_tag_rulesets(rulesets: Sequence[Mapping[str, Any]], expected_pattern: str) -> None:
    """Require an active, bypass-free ruleset that blocks tag updates/deletions."""
    for ruleset in rulesets:
        conditions = ruleset.get("conditions")
        ref_name = conditions.get("ref_name") if isinstance(conditions, Mapping) else None
        includes = ref_name.get("include", []) if isinstance(ref_name, Mapping) else []
        excludes = ref_name.get("exclude", []) if isinstance(ref_name, Mapping) else []
        rule_types = {
            rule.get("type")
            for rule in ruleset.get("rules", [])
            if isinstance(rule, Mapping)
        }
        if (
            ruleset.get("target") == "tag"
            and ruleset.get("enforcement") == "active"
            and expected_pattern in includes
            and not excludes
            and not (ruleset.get("bypass_actors") or [])
            and {"deletion", "update"}.issubset(rule_types)
        ):
            return

    raise PublicationControlError(
        "An active, bypass-free tag ruleset must include "
        f"{expected_pattern!r}, exclude nothing, and restrict both update and deletion."
    )


def _request_json(url: str, token: str) -> Any:
    request = urllib.request.Request(  # noqa: S310 - callers construct a fixed HTTPS API origin
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "honua-publication-control-verifier",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS API origin
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise PublicationControlError(f"Unable to verify GitHub publication controls at {url}: {exc}") from exc


def _load_rulesets(api_root: str, token: str) -> list[Mapping[str, Any]]:
    summaries: list[Any] = []
    page = 1
    while True:
        response = _request_json(
            f"{api_root}/rulesets?includes_parents=true&targets=tag&per_page=100&page={page}",
            token,
        )
        if not isinstance(response, list):
            raise PublicationControlError("GitHub rulesets API returned an unexpected response.")
        summaries.extend(response)
        if len(response) < 100:
            break
        page += 1

    details: list[Mapping[str, Any]] = []
    for summary in summaries:
        ruleset_id = summary.get("id") if isinstance(summary, Mapping) else None
        if not isinstance(ruleset_id, int):
            raise PublicationControlError("GitHub rulesets API returned an entry without an integer id.")
        detail = _request_json(f"{api_root}/rulesets/{ruleset_id}", token)
        if not isinstance(detail, Mapping):
            raise PublicationControlError(f"GitHub ruleset {ruleset_id} returned an unexpected response.")
        details.append(detail)
    return details


def verify_controls(repository: str, environment: str, tag_pattern: str, token: str) -> None:
    """Read and validate the selected package's GitHub publication controls."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise PublicationControlError(f"Invalid GitHub repository name: {repository!r}")
    if not token:
        raise PublicationControlError("GITHUB_TOKEN is required to verify publication controls.")

    api_root = f"https://api.github.com/repos/{repository}"
    encoded_environment = urllib.parse.quote(environment, safe="")
    environment_payload = _request_json(f"{api_root}/environments/{encoded_environment}", token)
    if not isinstance(environment_payload, Mapping):
        raise PublicationControlError(f"GitHub environment {environment!r} returned an unexpected response.")
    validate_environment(environment_payload, environment)

    trunk_branch = _request_json(f"{api_root}/branches/trunk", token)
    if not isinstance(trunk_branch, Mapping):
        raise PublicationControlError("The trunk branch API returned an unexpected response.")
    validate_trunk_branch(trunk_branch)
    validate_tag_rulesets(_load_rulesets(api_root, token), tag_pattern)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--tag-pattern", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        verify_controls(
            args.repository,
            args.environment,
            args.tag_pattern,
            os.environ.get("GITHUB_TOKEN", ""),
        )
    except PublicationControlError as exc:
        print(f"Publication controls rejected: {exc}", file=sys.stderr)
        return 1
    print(f"Verified {args.environment} and immutable {args.tag_pattern} controls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
