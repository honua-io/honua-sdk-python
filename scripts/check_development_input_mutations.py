"""Rejudge one actual complete proposal and original-sequence mutation controls."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

import development_source_inputs as producer


def check(source: Path, revision: str, directory: Path, policy: dict) -> dict:
    original = json.loads((directory / "proposal.json").read_bytes())
    producer.verify_proposal(original, source, revision, directory, policy)
    mutations = ["context-loss", "step-loss", "step-reorder", "ordinal", "command", "block", "extras-superset", "editable",
                 "source-before", "source-resolved", "source-after", "installed-before", "installed-after", "derived-command",
                 "install-command", "raw-report", "backend-command", "editable-identity", "published", "admitted", "candidate"]
    for mutation in mutations:
        value = deepcopy(original)
        context = value["documentationSequences"][0]
        step = context["steps"][0]
        if mutation == "context-loss":
            value["documentationSequences"].pop()
        elif mutation == "step-loss":
            context["steps"].pop()
        elif mutation == "step-reorder":
            context["steps"][0], context["steps"][1] = context["steps"][1], context["steps"][0]
        elif mutation == "ordinal":
            step["ordinal"] = 9
        elif mutation == "command":
            step["command"] += " --no-compile"
        elif mutation == "block":
            context["blockSha256"] = "0" * 64
        elif mutation == "extras-superset":
            step["requested"] = ["./packages/honua-sdk[grpc,geopandas,raster]"]
        elif mutation == "editable":
            value["documentationSequences"][1]["steps"][0]["editable"] = [False]
        elif mutation.startswith("source-"):
            key = {"source-before": "sourceBefore", "source-resolved": "sourceResolved", "source-after": "sourceAfter"}[mutation]
            step[key][next(iter(step[key]))] = "0" * 64
        elif mutation in ("installed-before", "installed-after"):
            key = "before" if mutation.endswith("before") else "after"
            step[key][next(iter(step[key]))]["version"] = "999.0"
        elif mutation == "derived-command":
            step["commandDerived"].remove("--no-build-isolation")
        elif mutation == "install-command":
            step["installCommand"].remove("--no-index")
        elif mutation == "raw-report":
            step["rawHashes"]["resolver"] = "0" * 64
        elif mutation == "backend-command":
            context["bootstrapCommand"].remove("--require-hashes")
        elif mutation == "editable-identity":
            context["editableWheels"][0]["publishedIdentity"] = True
        elif mutation == "published":
            value["publishedWheelIdentity"] = True
        elif mutation == "admitted":
            value["sourceAdmitted"] = True
        else:
            value["candidateQualified"] = True
        try:
            producer.verify_proposal(value, source, revision, directory, policy)
        except ValueError:
            continue
        raise AssertionError("complete proposal accepted mutation: " + mutation)
    # Controls never rewrite original retained reports or source files.
    producer.verify_proposal(original, source, revision, directory, policy)
    return {"completeOriginalPositive": "PASS", "mutationsRejected": mutations, "sourceAdmitted": False,
            "candidateQualified": False, "publishedWheelIdentity": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--runtime-policy", type=Path, default=Path(__file__).parent / "development-inputs/runtime.json")
    args = parser.parse_args()
    result = check(args.source, args.revision, args.destination, json.loads(args.runtime_policy.read_bytes()))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
