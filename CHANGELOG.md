# Changelog

All notable changes to revrook CE are recorded in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project will follow [Semantic Versioning](https://semver.org/) once it has a release.

No version has been released: there is no tag, no GitHub release and no published image. Everything below is under Unreleased and describes the release candidate that the Development environment runs. The version in `pyproject.toml` stays `0.0.0.dev0` until a release is authorised ([docs/release-candidate.md](docs/release-candidate.md)).

## [Unreleased]

### Added

- Repository, container and CI foundations: a multi-stage non-root image, a compose stack (web, worker, PostgreSQL 16), hashed requirement files, the nine-check merge gate and the licence audit.
- Sign-in with Argon2id, signed session cookies, CSRF protection, API tokens, an append-only audit trail and strict response headers.
- An evidence store: content-addressed files, immutable revisions, assurance labels, a hash chain with a verify command, per-client pseudonymisation, retention and deletion per client.
- Importers for Microsoft 365 exports (identity, secure score, devices, conditional access, directory roles) and for generic device, backup, network, training, leaver and mail exports, with a profile editor for files whose columns have other names.
- A library of 51 controls with plain-language wording, the check engine (automatic rules, manual alternatives, exceptions register) and the NIST CSF 2.0 and SP 800-171 reference names.
- The scoring engine: exact rational scores with a lower and an upper bound, freshness decay, gate caps, coverage, ruleset versions and stored snapshots that regenerate byte for byte.
- A public DNS check for SPF, DKIM and DMARC that stores a failed lookup as unknown and never as a fail.
- Reports made from a stored snapshot: the quarterly security review and the cyber insurance evidence pack, each as one HTML file with print styles, a disclaimer on every page and an export history that keeps an immutable copy and its SHA-256.
- The web interface: clients, overview, checklist, control drawer, evidence and imports, exceptions, report builder, export history, settings and a glossary.
- Operations: a scheduler, expiry reminders by mail, retention purge, a full data export without personal identifiers, deletion per client, optional Prometheus metrics, a system page with a stale-worker banner, an optional outside heartbeat, and a backup and restore guide with a script that proves a restore.
- Extension API version 1 with seven extension points and plugin loading through an entry point group ([docs/extension-api.md](docs/extension-api.md)).
- Documentation: quick start, install, configuration, upgrade, security review and a mapping policy, with an index in the README. `scripts/demo.sh` loads one synthetic client so that a new installation has something to look at.
- `verify-mappings` command: lists the mapping rows nobody has verified, checks every NIST identifier against the pinned names extract (a consistency check against the 32 CSF and 26 SP 800-171 identifiers transcribed from the catalog at the recorded commit; it is not a comparison with the full catalog) and keeps the register of verified rows equal to the control file.
- An upgrade test that seeds a database at each earlier schema revision, upgrades it to the newest and checks that no row is lost.
- `tests/test_docs.py`: links between pages, the configuration table against the settings, the README statements and the format of this file.

### Changed

- The web interface has a design system ([docs/design-system.md](docs/design-system.md)): tokens for colour, type, spacing and radius; an app shell with a charcoal navigation rail, grouped links with icons and the signed-in user; redesigned sign-in and first-run pages with the logo at a proper size; and the buttons, fields, tables, cards, status pills, alerts, empty states, import area and confirmation patterns the other pages will adopt. No behaviour, data or evidence rule changed.
- Home is a dashboard of every client ([docs/design-system.md](docs/design-system.md), Dashboard): four stat cards with sparklines from the stored reports, a posture ring per client, the most urgent controls across all clients, the scores of the last 90 days, the controls by domain and the recent changes of the audit trail. It reads the same views and snapshots as the client pages and the reports; nothing is stored and no behaviour, data or evidence rule changed.
- The stylesheets and scripts are linked with a version query (`?v=` and a digest of the four files, `asset_version()` in `app/ui/brand.py`), so a new version of a file has a new address and a browser or a cache in front of the installation never serves an old stylesheet with a new page after an upgrade.
- `docs/operations.md` states how request bodies are framed: a body must declare its size in `Content-Length`, and any `Transfer-Encoding` is answered with 411.
- The compose smoke test runs the quick start (`scripts/e2e/phase_11.sh`) and fails if it takes ten minutes or more. The script is for CI only: it leaves a fixed-password administrator account behind, so the quick start does not tell users to run it.

### Fixed

- The arrow of a select, the date picker icon and the check mark of a checkbox were `data:` images of Pico CSS, which the content security policy blocks; the native controls are shown instead and the stylesheet loads no image at all.
- In the app shell on a narrow phone the "Community Edition" badge overlapped the sign-out button, and in the rail the signed-in name was cut short beside that button: the badge is hidden below 600 px (the footer names the edition) and the button has its own line in the rail. The sign-in tagline grows to 24 px only from 1024 px, where the panel is wide enough for it.
- A request with `Transfer-Encoding: chunked` and a small `Content-Length` passed the body size check; any `Transfer-Encoding` is now refused with 411.
- A plugin that fails to load no longer chains its own error into the message; only its name and the class of the error are reported.
- A bearer token on a page no longer skips the CSRF check; only paths under `/api/` do.
- An API id past 2^63 - 1 gave a 500; it is now refused with 422.

### Security

- The security checklist of phase 11 was run and is in [docs/security-review.md](docs/security-review.md): no finding of High or Medium severity is open. Fixed: parallel sign-ins could use up the database connections, request bodies other than uploads had no size cap and the data export was built whole in memory.
- Scores are uncalibrated design choices and mappings to outside frameworks are unverified unless marked; nothing in revrook is a certification.
