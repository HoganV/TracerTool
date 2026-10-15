# Security policy

Report suspected vulnerabilities in raster/project parsing, unintended file
access or writes, and dependencies distributed with TracerTool. Ordinary tracing
quality and usability problems can use the public bug-report form; potentially
exploitable issues should follow the private route below.

## Reporting a vulnerability

If this GitHub repository has private vulnerability reporting enabled, use its
**Security** (or **Security and quality**) tab and **Report a vulnerability**.
This opens a private advisory report. The presence of this policy does **not**
mean that the GitHub setting is enabled. See GitHub's
[private reporting instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).

If that option is unavailable, open a blank public issue titled
**Private security contact requested**, containing only a request for a private
reporting channel. Wait for a maintainer to provide one. Do not include the bug's
details, affected files, exploit steps, or attachments in that public request.
This fallback follows GitHub's
[coordinated disclosure guidance](https://docs.github.com/en/code-security/concepts/vulnerability-reporting-and-management/coordinated-disclosure).

Once a private channel is established, include the exact application version or
commit, operating system, source/portable distribution, potential impact, and a
minimal reproduction using synthetic or otherwise shareable inputs. Include
relevant dependency versions if known. Do not send credentials, private terrain,
client project files, or unrelated personal data. Coordinate publication of
technical details with the maintainer handling the report.

## Versions and expectations

Reports are welcome for any version; identify whether the problem also affects
the current development code or latest available release, if you have safely
checked. There is no published long-term support schedule, guaranteed response
time, or bounty program. Any supported release lines, backports, and security
fixes will be described in release notes or advisories.

TracerTool processes local files through native GIS libraries. Local processing
does not provide a sandbox for untrusted inputs. Reproductions should use a
disposable test environment and copies of data you are authorized to test.
