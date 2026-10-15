# Publishing TracerTool

The public source repository is [HoganV/TracerTool](https://github.com/HoganV/TracerTool).
Source publication and public binary distribution have separate checks below.
Public source availability does not mean that the local portable bundles have
completed their distribution review.

## Use the sanitized checkout

For the original local workspace, the prepared publishing repository is
`dist/github/TracerTool`. It has a new initial Git history on `main`, containing
the reviewed public snapshot. The development repository retains historical
private terrain metadata even after its current files are sanitized. **Do not
push the original development repository, its branches or its tags.** Deleting
a file from the latest commit does not remove it from earlier commits.

From the original workspace, enter the prepared checkout and inspect it:

```sh
cd dist/github/TracerTool
python scripts/check_publication.py --history
git status --short
git log --all --oneline
git remote -v
```

A later clone of the public repository is already the correct checkout; run
these checks from its root without the first `cd`. The publishing checkout must
contain a committed, reviewed snapshot with no staged or unstaged tracked
changes; `--history` refuses a dirty tracked checkout. Commit reviewed changes
in this sanitized repository before rerunning the audit, and resolve every
audit failure before pushing.

The audit checks tracked file contents and filenames, reachable committed file
blobs, commit and annotated-tag metadata, and ref names for private input/output
material, common credential patterns and local home paths. It also checks
local documentation links, required project documents and version consistency.
Terrain/vector outputs and GDAL sidecars are excluded. This is a focused
publication check, not a guarantee that no sensitive content can exist. Review
the public file list, commit/tag messages and generated examples as well.

The current source, documentation, tests and synthetic demonstration may be
shared after review. Private reference rasters, their detailed inventory,
private-data screenshots/projects, local build tools and old portable bundles
are not publication assets. Read [AI_DISCLOSURE.md](../AI_DISCLOSURE.md) for the
project's development provenance and review boundaries.

## Initial GitHub push

1. Finish the public-source audit above and inspect the clean checkout. Run the
   source tests and smoke test using [BUILDING.md](BUILDING.md).
2. Create an empty repository in the intended GitHub account or organization.
   Do not initialize it with a README, license or `.gitignore`; those are
   already in the prepared checkout. Copy the exact Git URL from GitHub.
3. In the **sanitized checkout only**, replace `REPOSITORY_GIT_URL` below with
   that copied URL. If `origin` already exists, inspect it first instead of
   blindly replacing it.

```sh
git remote add origin REPOSITORY_GIT_URL
git remote -v
git push -u origin main
```

Push only the reviewed `main` branch. Do not use a mirror/all-branches push or
copy the original development `.git` directory into the prepared checkout.
For an existing public clone, use its configured remote and an ordinary
reviewed push instead of repeating repository creation. GitHub's
[importing local code guide](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)
describes authentication, empty-repository creation and the remote/push flow.

4. Inspect the first Actions run. Require the public-readiness job and every
   test-matrix job to pass before treating hosted CI as verified. The workflow
   configuration itself is not a successful GitHub run. Add branch protection
   using those observed status checks, and keep dependency updates reviewed.

## What the workflow does

Pushes and pull requests run the committed-snapshot and complete-history
publication audit before tests, including filename and commit/tag/ref metadata
checks. That job uses `fetch-depth: 0`. The test matrix covers Python 3.11 and 3.12 on
Linux, and Python 3.13/3.14 on Windows. It checks installed dependency consistency,
the synthetic/Qt suite and the generated-terrain desktop smoke scenario. These
original 3.11/3.12/3.13 jobs passed in the first public source run; the exact commit, job
results and verification boundaries are recorded in [VALIDATION.md](VALIDATION.md).

The workflow uses read-only repository permissions, does not persist checkout
credentials, sets bounded job times, and cancels obsolete pull-request runs.
It uses ordinary `pull_request`, not a privileged fork-checkout event. Its
external actions are pinned to these official release commits, verified on
2026-10-15:

| Action | Release | Commit |
|---|---|---|
| Checkout | [v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| Setup Python | [v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0) | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| Upload artifact | [v7.0.2](https://github.com/actions/upload-artifact/releases/tag/v7.0.2) | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |

The action manifests use Node 24; the workflow targets GitHub-hosted runners.
It has not been qualified for an older self-hosted runner or GitHub Enterprise
Server installation. The security choices follow GitHub's
[secure workflow guidance](https://docs.github.com/en/actions/reference/security/secure-use).

Portable jobs run only on manual dispatch with **Build and verify portable
apps** selected. They build, smoke-test and verify a clean extracted archive.
The separate **Upload binaries only after the distribution review** choice is
off by default; leaving it off runs verification without retaining downloadable
binary artifacts. A public-repository Actions artifact is distribution too.
When enabled after review, uploads contain only the named ZIP/checksum outputs,
expire after 14 days, and do not create a GitHub Release. There is no automatic
release publication or tag-triggered binary upload.

## Dependency maintenance

[dependabot.yml](../.github/dependabot.yml) checks GitHub Actions and the Python
project weekly and opens reviewable update pull requests. It does not merge
changes. Commit-SHA action pins retain release comments so updates can be
reviewed against upstream releases. See GitHub's
[Dependabot configuration reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)
and [action-update guidance](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/auto-update-actions).

The standalone `scripts/windows-build-constraints.txt` is a resolved release
build environment, not a promise of automatic Dependabot coverage. Review it
with each relevant dependency update, regenerate it from the tested Windows
build environment, and rerun source and frozen/extracted checks. In particular,
the documented Qt version constraint was selected for the local Wine toolchain;
do not remove it without fresh target-platform evidence. Review upstream
security notices as well as update PRs; SHA pins and a dependency bot are not a
complete vulnerability assessment.

## Source publication and binary distribution gates

| Asset | Gate before sharing publicly |
|---|---|
| Sanitized source repository | Clean full-history audit; reviewed public files, license, development disclosure and synthetic examples; no private data or old development history. |
| Source prerelease | Use the sanitized public commit; inspect the source archive; include [0.2.0 notes](releases/0.2.0.md) and preserve the prerelease label. Do not attach the old local source ZIP without a fresh public-data audit. |
| Portable ZIPs or Actions binary artifacts | Rebuild from the sanitized commit; review every bundled library's license/notices and required corresponding source/relinking materials; rerun package checks; finish clean-Windows and intended-GIS acceptance before presenting a generally supported Windows download. |

The existing local Linux/Windows bundles predate this public-data cleanup and
have **not** been cleared for public distribution. Do not upload them merely
because their functional checks passed. [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)
records the dependency review scope. Native Windows desktop acceptance,
target-GIS interoperability and operator-reviewed positional accuracy remain
open in [VALIDATION.md](VALIDATION.md) and [ROADMAP.md](ROADMAP.md).

For a first public source release, create a **draft** against the reviewed
sanitized commit, use the prepared notes, and mark it **prerelease**. Inspect
the target/tag and every asset before publishing it manually. A source-only
prerelease can accurately describe the locally tested application without
advertising unreviewed binaries. GitHub documents the draft and prerelease
controls in [Managing releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).
