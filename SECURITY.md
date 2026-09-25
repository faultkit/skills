# Security Policy

## Reporting a vulnerability

Please do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests.

Report privately via GitHub's **Private Vulnerability Reporting**: this
repository's **Security** tab → **Report a vulnerability**. Include the
affected commit or plugin version, what you observed, steps to reproduce,
and the impact. We aim to acknowledge a report within 3 business days and
follow coordinated disclosure.

Vulnerabilities in the faultkit binary itself belong to
[faultkit/faultkit](https://github.com/faultkit/faultkit/security/policy).

## What this plugin does

- Four skills: review, harden, run, run-all. No hooks, no MCP servers, no
  telemetry.
- One outbound call from shipped code: `faultkit/scripts/run_faultkit.py`
  downloads a pinned faultkit release from GitHub when no binary is
  available, verifies its sha256 against the release's `checksums.txt`, and
  never resolves "latest". [Network access](README.md#network-access)
  describes it and the opt-out.
- Run and Run all write into your project only with your consent, otherwise
  into a temporary workspace. Harden opens a pull request only after you say
  yes.
- Runs are for local, test, or explicitly authorized environments. The
  safety gate stops on production signals before anything runs.

## Supported versions

Security fixes land on `main` and ship in the next plugin version. Update
with `claude plugin marketplace update faultkit` and
`claude plugin update faultkit@faultkit`.
