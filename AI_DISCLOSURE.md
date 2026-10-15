# AI development disclosure

TracerTool's initial implementation was substantially generated and iteratively
revised using **OpenAI Codex**, including parallel coding agents. This was more
than autocomplete or occasional editing assistance.

## Scope and human direction

AI agents contributed application architecture, terrain-processing and editing
code, tests, documentation, literature summaries, packaging scripts and local
verification. A human supplied the intended workflow, requirements, private
reference terrain and critical visual feedback, including the need for smoother
lines and wider vertex spacing on levees. The agents used that feedback to
revise the implementation and exercise the software.

This disclosure describes the initial development through version 0.2.0 and
the subsequent public-repository preparation. It does not claim that every
line was reviewed by a human, that an independent engineer audited the code,
or that generated tests establish surveying or hydraulic accuracy. Tests and
their expected results were also largely developed by AI agents.

## What was checked

The [validation record](docs/VALIDATION.md) identifies the environments, tests,
format read-back checks and actual desktop interactions performed. It also
identifies missing evidence: interactive Windows acceptance, target-GIS handoff,
independent labeled geometry and measured operator productivity. Passing tests
and attractive examples are narrower evidence than those missing checks.

The [research notes](docs/RESEARCH.md) link primary sources and distinguish
implemented methods from ideas for future work. Literature summaries and
engineering choices should be reviewed alongside the sources and code. The
authors of those papers have not endorsed or validated this application.

## Runtime behavior and data

AI was used to develop the software. The application itself uses local raster,
geometry and numerical algorithms; normal operation does not call an AI model,
require an AI account, or upload terrain to a service. It has no telemetry or
automatic updater. Installing dependencies or obtaining releases can require
network access; opening, editing and exporting terrain works locally.

Private development inputs and their derived screenshots are excluded from
the public checkout. The public example image is generated from synthetic
terrain. See [data and examples](docs/INPUTS.md).

## Contributions and responsibility

Contributors should disclose substantial AI assistance in pull requests:
which parts it affected, what they personally reviewed, and which checks they
ran. Private prompts or proprietary inputs are not requested. AI output must
meet the same coordinate, data-integrity, licensing and verification standards
as other contributions. The submitting contributor and accepting maintainer
remain responsible for the change; naming a tool is not a substitute for review.

The [MIT license](LICENSE) applies to original project material. Third-party
components retain their own licenses, documented in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). This disclosure is a provenance
statement, not a claim of third-party approval or an independent license audit.
