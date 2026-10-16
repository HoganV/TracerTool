# AI development disclosure

TracerTool's initial implementation was substantially generated and iteratively
revised using **OpenAI Codex**, including parallel coding agents. This was more
than autocomplete or occasional editing assistance.

## Scope and human direction

AI agents contributed application architecture, terrain-processing and editing
code, tests, documentation, literature summaries, packaging scripts and local
verification. A human supplied the intended workflow, requirements, private
reference terrain and critical visual feedback. That feedback first requested
smoother levee lines and wider spacing, then identified poor default behavior,
overconstrained guides and missing draft-editing/display controls. Agents used
both rounds of feedback to revise the software, test synthetic examples and
operate the real Linux desktop application through computer control.

This disclosure covers development through version 0.2.2, including public
repository preparation, the 0.2.1 Python 3.14 compatibility update, and the
0.2.2 tracing, display, persistence and draft-editing revisions. Parallel AI
agents also wrote the new regression tests and documentation. It does not claim
that every line was reviewed by a human, that an independent engineer audited
the code,
or that generated tests establish surveying or hydraulic accuracy. Tests and
their expected results were also largely developed by AI agents.

## What was checked

The [validation record](docs/VALIDATION.md) identifies the environments, tests,
format read-back checks and actual desktop interactions performed. It also
identifies missing evidence: interactive Windows acceptance, target-GIS handoff,
independent labeled geometry and measured operator productivity. Passing tests
and attractive examples are narrower evidence than those missing checks.
The 0.2.2 desktop exercises included fine projected terrain and a coarser USGS
raster through an explicitly reprojected copy with a disclosed working grid.
They establish observed workflow behavior, not independent feature accuracy.
A later native inspection exposed an endpoint following an isolated shoulder
feature; agents revised the continuity check and added synthetic reproductions.
Hosted Windows/Linux tests verified the initial 0.2.2 source snapshot, while
the later correction has separately recorded local checks. Results are tied to
their tested snapshots. Historical portable/Wine evidence does not validate a
0.2.2 binary or native Windows interactive workflow.

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
