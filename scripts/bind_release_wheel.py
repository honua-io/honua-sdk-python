#!/usr/bin/env python3
"""Select the published Python wheel from retained release governance."""
import os
from pathlib import Path

import yaml

from scripts.published_wheel_identity import validate_identity


def release_wheel(manifest):
    component = manifest["components"]["honua-sdk-python"]
    wheel = manifest["clientArtifacts"]["honua-sdk-python-wheel"]
    version, digest, source = (wheel[key] for key in ("version", "digest", "sourceSha"))
    validate_identity(wheel)
    if (
        wheel["ecosystem"] != "pypi"
        or wheel["repository"] != "honua-io/honua-sdk-python"
        or wheel["publicationState"] != "published"
        or component["artifact"] != "pypi:honua-sdk"
        or (version, digest, source) != tuple(component[key] for key in ("version", "artifactSha256", "sha"))
        or wheel["filename"] != f"honua_sdk-{version}-py3-none-any.whl"
    ):
        raise ValueError("release manifest has no matching published honua-sdk wheel identity")
    return wheel


def main():
    manifest = Path(os.environ["GITHUB_WORKSPACE"]) / "honua-release-governance/platform-manifest.yaml"
    try:
        wheel = release_wheel(yaml.safe_load(manifest.read_text(encoding="utf-8")))
        for input_name, field in (
            ("SDK_PACKAGE", "package"), ("SDK_PACKAGE_VERSION", "version"),
            ("SDK_PACKAGE_DIGEST", "digest"), ("SDK_SOURCE_SHA", "sourceSha"),
        ):
            supplied = os.environ.get(input_name, "")
            if supplied and supplied != wheel[field]:
                raise ValueError(f"{input_name} differs from the release manifest")
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(f"Release wheel binding refused: {exc}") from exc
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as env:
        print(f"HONUA_SDK_PUBLIC_VERSION={wheel['version']}", file=env)
        print(f"HONUA_SDK_PUBLIC_WHEEL={wheel['filename']}", file=env)
        print(f"HONUA_SDK_PUBLIC_WHEEL_SHA256={wheel['digest'].removeprefix('sha256:')}", file=env)
        print(f"HONUA_SDK_PUBLIC_SOURCE_SHA={wheel['sourceSha']}", file=env)


if __name__ == "__main__":
    main()
