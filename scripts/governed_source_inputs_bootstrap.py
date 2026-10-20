"""Bootstrap producer-only packaging without installing into the subject runtime."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import tempfile
from pathlib import Path
import sys
import zipfile


def bootstrap(wheel: Path, policy: dict) -> dict:
    binding = policy["executionBinding"]
    if wheel.name != binding["implementationPackagingFilename"] or wheel.is_symlink() or not wheel.is_file():
        raise ValueError("implementation tool wheel identity differs")
    data = wheel.read_bytes()
    if hashlib.sha256(data).hexdigest() != binding["implementationPackagingSha256"]:
        raise ValueError("implementation tool wheel bytes differ")
    # This check occurs before adding any implementation import path. Original
    # image packaging is absent and its original pip remains unchanged.
    try:
        importlib.metadata.distribution("packaging")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise ValueError("implementation packaging was installed into original runtime")
    with zipfile.ZipFile(wheel) as archive:
        if archive.testzip() is not None or "packaging/__init__.py" not in archive.namelist():
            raise ValueError("implementation tool wheel is malformed")
    sys.path.insert(0, str(wheel))
    implementation = Path(__file__).resolve().parent
    sys.path.insert(0, str(implementation))
    return {"filename": wheel.name, "sha256": hashlib.sha256(data).hexdigest(),
            "role": "producer-only-readonly-import", "installed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation-packaging-wheel", type=Path, required=True)
    parser.add_argument("--action", choices=["probe", "probe-refusals", "generate", "verify", "mutations"], required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--runtime-policy", type=Path, required=True)
    args = parser.parse_args()
    policy = json.loads(args.runtime_policy.read_bytes())
    bootstrap(args.implementation_packaging_wheel, policy)
    import development_source_inputs as producer
    if args.action == "probe":
        # Deliberately injected ambient import configuration must never reach
        # the subject interpreter. runtime() re-observes a real child process.
        os.environ["PYTHONPATH"] = str(args.implementation_packaging_wheel)
        print(json.dumps(producer.runtime(policy), sort_keys=True))
    elif args.action == "probe-refusals":
        failures = []
        with tempfile.TemporaryDirectory(prefix="honua-tool-refusals-") as temporary:
            scratch = Path(temporary)
            for case in ("wheel-bytes", "wheel-name", "image", "interpreter", "pip", "pip-entrypoint", "wheel-policy"):
                candidate = json.loads(json.dumps(policy))
                wheel = args.implementation_packaging_wheel
                if case in ("wheel-bytes", "wheel-name"):
                    wheel = scratch / (wheel.name if case == "wheel-bytes" else "foreign.whl")
                    wheel.write_bytes(args.implementation_packaging_wheel.read_bytes() + (b"MUTATION" if case == "wheel-bytes" else b""))
                else:
                    key = {"image": "containerImage", "interpreter": "pythonExecutableSha256", "pip": "pipToolFilesSha256",
                           "pip-entrypoint": "pipEntrypointSha256", "wheel-policy": "implementationPackagingSha256"}[case]
                    candidate["executionBinding"][key] = "invalid-reviewed-input"
                path = scratch / "runtime.json"
                path.write_text(json.dumps(candidate))
                command = [sys.executable, "-I", str(Path(__file__).resolve()), "--implementation-packaging-wheel", str(wheel),
                           "--action", "probe", "--source", str(args.source), "--revision", args.revision,
                           "--destination", str(args.destination), "--runtime-policy", str(path)]
                result = subprocess.run(command, capture_output=True, check=False, env={key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "LANG")})  # noqa: S603
                expected = ("implementation tool wheel identity differs" if case == "wheel-name" else
                            "implementation tool wheel bytes differ" if case in ("wheel-bytes", "wheel-policy") else
                            "original documentation pip entrypoint differs" if case == "pip-entrypoint" else
                            "original documentation interpreter or pip bytes differ")
                if result.returncode == 0 or expected.encode() not in result.stderr:
                    raise ValueError("runtime refusal control did not reach its exact input boundary: " + case)
                failures.append(case)
        print(json.dumps({"actualRefusals": failures, "sourceAdmitted": False, "candidateQualified": False}, sort_keys=True))
    elif args.action == "generate":
        producer.generate(args.source, args.revision, args.destination, policy)
    elif args.action == "verify":
        value = json.loads((args.destination / "proposal.json").read_bytes())
        producer.verify_proposal(value, args.source, args.revision, args.destination, policy)
    else:
        from check_development_input_mutations import check
        print(json.dumps(check(args.source, args.revision, args.destination, policy), sort_keys=True))


if __name__ == "__main__":
    main()
