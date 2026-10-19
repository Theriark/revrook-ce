# revrook-ce

Revrook Community Edition (CE): self-hosted client security posture, insurance evidence and QBR reporting for small MSPs.

Licensed under the [MIT licence](LICENSE).

## Status

Pre-release. This repository is in Development only. There is no released version, no hosted service and no supported installation yet. Nothing here should be read as a claim of customers, certification or availability.

## What this repository is

This is the Community Edition (CE) and nothing else. Every file in it is under the MIT licence, it runs on your own machine with no licence key, no outside account and no paid service, and it holds no code and no names that belong to a later or paid edition. What an installation adds goes in through the documented extension API (version 1, [docs/extension-api.md](docs/extension-api.md)).

You export evidence from the tools you already use (device, backup, network, training, leaver, mail and Microsoft 365 exports) and upload it. Revrook checks it against 51 plain-language controls, scores the result with a lower and an upper bound, and makes a quarterly security review and a cyber insurance evidence pack for each client, each as one HTML file.

## What the output is

Revrook produces a configuration evidence summary. It is not a certification, audit or legal advice. Every evidence item shows its evidence date, and every score shows the ruleset version used to produce it.

**Scores are uncalibrated design choices.** The weights, thresholds and bands of the ruleset are our own written-down judgement. They have not been calibrated against real incidents, insurers or auditors. Read a score to compare a client with its own earlier state and to see what to fix first, not as a measurement.

**Mappings to outside frameworks are unverified unless marked.** Controls carry pointers to NIST CSF 2.0, NIST SP 800-171, CIS Controls, ISO/IEC 27001, Cyber Essentials and NIS2 identifiers. No row has been verified yet, and a report prints an outside identifier only for a row that a person has marked verified, so today it prints none ([docs/mapping-verification.md](docs/mapping-verification.md)).

## Try it

The [quick start](docs/quick-start.md) takes you from nothing to an exported quarterly review in about ten minutes, with invented demo data: start the stack with `docker compose up --build --wait`, make the first account, then run `bash scripts/demo.sh YOUR-USER-NAME`.

## Documentation

| Page | What it holds |
| --- | --- |
| [docs/quick-start.md](docs/quick-start.md) | From nothing to an exported quarterly review, with demo data |
| [docs/install.md](docs/install.md) | Running it for real: keys, compose, TLS and a checklist |
| [docs/configuration.md](docs/configuration.md) | Every environment variable with its default |
| [docs/upgrade.md](docs/upgrade.md) | Moving to a newer version, and going back |
| [docs/operations.md](docs/operations.md) | Worker, reminders, retention, limits, metrics, backup and restore |
| [docs/security.md](docs/security.md) | Sign-in and security design |
| [docs/security-review.md](docs/security-review.md) | The security checklist of phase 11 and its findings |
| [docs/controls.md](docs/controls.md) | The control library and the check engine |
| [docs/scoring.md](docs/scoring.md) | The scoring decisions and the sensitivity result |
| [docs/scoring-engine.md](docs/scoring-engine.md) | The scoring engine and snapshots |
| [docs/importers.md](docs/importers.md) | How each source is exported and imported |
| [docs/dns-check.md](docs/dns-check.md) | The public SPF, DKIM and DMARC check |
| [docs/reports.md](docs/reports.md) | The two reports and their export |
| [docs/mapping-verification.md](docs/mapping-verification.md) | Mapping policy, source versions and the register of verified rows |
| [docs/extension-api.md](docs/extension-api.md) | Extension API version 1 |
| [docs/licences.md](docs/licences.md) | Licences of the dependencies |
| [docs/development.md](docs/development.md) | Development guide |
| [docs/testing.md](docs/testing.md) | Testing notes |
| [docs/ci-cd.md](docs/ci-cd.md) | CI/CD flow and known gaps |
| [docs/pdf-spike.md](docs/pdf-spike.md) | The PDF spike and why the reports are HTML |
| [docs/release-candidate.md](docs/release-candidate.md) | Acceptance state and the release workflow check |

Changes are listed in the [CHANGELOG](CHANGELOG.md).

## Contributing and security

- Contribution rules: [CONTRIBUTING.md](CONTRIBUTING.md)
- Reporting a vulnerability: [SECURITY.md](SECURITY.md)
- CI/CD flow and known gaps: [docs/ci-cd.md](docs/ci-cd.md)

## Running it

- Install and first start: [docs/install.md](docs/install.md)
- Worker, reminders, retention, metrics, backup and restore: [docs/operations.md](docs/operations.md)
