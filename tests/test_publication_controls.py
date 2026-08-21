from __future__ import annotations

import pytest

from scripts.verify_publication_controls import (
    PublicationControlError,
    validate_environment,
    validate_tag_rulesets,
    validate_trunk_branch,
    verify_controls,
)


def _ruleset(pattern: str) -> dict[str, object]:
    return {
        "target": "tag",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": [pattern], "exclude": []}},
        "rules": [{"type": "deletion"}, {"type": "update"}],
    }


def test_environment_requires_protected_branches_only() -> None:
    validate_environment(
        {
            "name": "pypi-honua-sdk",
            "can_admins_bypass": False,
            "deployment_branch_policy": {
                "protected_branches": True,
                "custom_branch_policies": False,
            },
        },
        "pypi-honua-sdk",
    )

    with pytest.raises(PublicationControlError, match="Protected branches only"):
        validate_environment(
            {
                "name": "pypi-honua-sdk",
                "can_admins_bypass": False,
                "deployment_branch_policy": None,
            },
            "pypi-honua-sdk",
        )


@pytest.mark.parametrize("can_admins_bypass", [True, None])
def test_environment_rejects_admin_bypass(can_admins_bypass: bool | None) -> None:
    with pytest.raises(PublicationControlError, match="administrators to bypass"):
        validate_environment(
            {
                "name": "pypi-honua-admin",
                "can_admins_bypass": can_admins_bypass,
                "deployment_branch_policy": {
                    "protected_branches": True,
                    "custom_branch_policies": False,
                },
            },
            "pypi-honua-admin",
        )


def test_trunk_branch_requires_public_protected_flag() -> None:
    validate_trunk_branch({"name": "trunk", "protected": True})

    with pytest.raises(PublicationControlError, match="trunk branch must remain protected"):
        validate_trunk_branch({"name": "trunk", "protected": False})

    with pytest.raises(PublicationControlError, match="trunk branch must remain protected"):
        validate_trunk_branch({"name": "other", "protected": True})


def test_control_verifier_uses_non_admin_branch_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_urls: list[str] = []

    def request_json(url: str, token: str) -> object:
        requested_urls.append(url)
        assert token == "github-token"
        if url.endswith("/environments/pypi-honua-sdk"):
            return {
                "name": "pypi-honua-sdk",
                "can_admins_bypass": False,
                "deployment_branch_policy": {
                    "protected_branches": True,
                    "custom_branch_policies": False,
                },
            }
        if url.endswith("/branches/trunk"):
            return {"name": "trunk", "protected": True}
        if "/rulesets?" in url:
            return [{"id": 17}]
        if url.endswith("/rulesets/17"):
            return _ruleset("refs/tags/python-sdk-v*")
        raise AssertionError(f"Unexpected GitHub API URL: {url}")

    monkeypatch.setattr("scripts.verify_publication_controls._request_json", request_json)

    verify_controls(
        "honua-io/honua-sdk-python",
        "pypi-honua-sdk",
        "refs/tags/python-sdk-v*",
        "github-token",
    )

    assert any(url.endswith("/branches/trunk") for url in requested_urls)
    assert not any(url.endswith("/branches/trunk/protection") for url in requested_urls)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"enforcement": "disabled"}, "active"),
        ({"bypass_actors": [{"actor_type": "OrganizationAdmin"}]}, "bypass-free"),
        ({"rules": [{"type": "deletion"}]}, "update and deletion"),
        ({"conditions": {"ref_name": {"include": ["refs/tags/other-*"], "exclude": []}}}, "python-sdk"),
        (
            {
                "conditions": {
                    "ref_name": {
                        "include": ["refs/tags/python-sdk-v*"],
                        "exclude": ["refs/tags/python-sdk-v0.*"],
                    }
                }
            },
            "exclude nothing",
        ),
    ],
)
def test_tag_ruleset_fails_closed(mutation: dict[str, object], message: str) -> None:
    ruleset = _ruleset("refs/tags/python-sdk-v*")
    ruleset.update(mutation)

    with pytest.raises(PublicationControlError, match=message):
        validate_tag_rulesets([ruleset], "refs/tags/python-sdk-v*")


def test_each_publication_tag_pattern_requires_immutable_rules() -> None:
    rulesets = [
        _ruleset("refs/tags/python-sdk-v*"),
        _ruleset("refs/tags/python-admin-v*"),
    ]

    validate_tag_rulesets(rulesets, "refs/tags/python-sdk-v*")
    validate_tag_rulesets(rulesets, "refs/tags/python-admin-v*")
