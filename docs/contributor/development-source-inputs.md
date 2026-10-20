# Review-only development source inputs

`python scripts/development_source_inputs.py --source /absolute/clean/checkout --revision FULL_40_CHARACTER_SHA --destination /absolute/new/proposal-directory`

Run with the exact Python, pip, packaging and platform declared in
`scripts/development-inputs/runtime.json`. The source must be a clean immutable
checkout of this repository. Outputs stay outside the checkout. The producer
captures every tracked source input and derives the core, grpc, geopandas,
raster, and combined SDK-with-all-extras plus Admin profiles from the actual
package metadata. All five profiles are mandatory.

Each profile retains the actual resolver command, interpreter environment,
original report and output, and anonymously downloaded wheels with canonical
PyPI origins, metadata, exact versions and SHA256 hashes. An independent registry
response must agree with every artifact. Dependency markers and extras are
rejudged recursively; missing dependencies fail. The exact Hatchling build
closure is resolved separately, installed with hash enforcement into a disposable
backend environment, and used without build isolation, dependency resolution or
network indexes to build both packages from tracked source bytes only.

`python scripts/development_source_inputs.py --verify --source /absolute/clean/checkout --revision FULL_40_CHARACTER_SHA --destination /absolute/existing/proposal-directory`

Verification rejoins source/runtime, original resolver reports, all profiles,
artifact bytes and recursive closure, and the separate source-built wheels.
Source or runtime refusal occurs before resolver execution. Drift detected after
resolution refuses before backend installation. Failure outputs are retained;
a missing final `proposal.json` is a failed proposal, never an admitted input.

This is an input proposal for honua-release issue 721 and Python issue 311.
Generation and verification do not admit a source install, relax default
PEP610/direct-origin refusal, establish published wheel identity, publish a
package, change a version or release pin, or qualify a release candidate. The
SDK and Admin publication sources may differ; these source-built wheels carry
their actual checkout identity and never inherit a published artifact's identity.
Every original document and command remains required for the later admitted
source and exact-candidate replay.
