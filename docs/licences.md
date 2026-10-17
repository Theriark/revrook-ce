# Dependency licences

revrook CE is MIT licensed. This file records the licence of every direct
dependency, read from the LICENSE file in the project's own source repository,
and the driver decision of the phase 0 spike. Datasets are recorded separately
in `LICENSES-CONTENT.md`.

Policy (merge gate check 6): MIT, MIT-0, BSD-2-Clause, BSD-3-Clause, Apache-2.0,
ISC, PSF-2.0, Python-2.0, CNRI-Python, 0BSD, Unlicense and CC0-1.0 are allowed;
MPL-2.0 only for development packages. LGPL, GPL, AGPL, SSPL and unknown
licences fail, transitive packages included. `tools/licence_audit.py` enforces
this on the installed packages; psycopg must not appear in the lock file.

## Direct runtime dependencies

"Date read" is the day the LICENSE file was read at its source. All files were
read on 2026-10-17 from the default branch of the repository named in the
"LICENSE file read" column.

| Dependency | SPDX identifier | LICENSE file read | Date read | Notes |
| --- | --- | --- | --- | --- |
| alembic | MIT | sqlalchemy/alembic `LICENSE` | 2026-10-17 | |
| argon2-cffi | MIT | hynek/argon2-cffi `LICENSE` | 2026-10-17 | |
| asyncpg | Apache-2.0 | MagicStack/asyncpg `LICENSE` | 2026-10-17 | Driver chosen by the spike below. |
| charset-normalizer | MIT | jawah/charset_normalizer `LICENSE` | 2026-10-17 | |
| cryptography | Apache-2.0 OR BSD-3-Clause | pyca/cryptography `LICENSE` | 2026-10-17 | The file offers either licence (LICENSE.APACHE or LICENSE.BSD). Those two files were not opened. |
| dnspython | ISC | rthalley/dnspython `LICENSE` | 2026-10-17 | Permissive. Phase 7 may use dnspython for SPF, DKIM and DMARC lookups. The file also carries a second ISC-style notice for code from Nominum and Google. |
| fastapi | MIT | fastapi/fastapi `LICENSE` | 2026-10-17 | |
| greenlet | MIT AND PSF-2.0 | python-greenlet/greenlet `LICENSE` | 2026-10-17 | Required by SQLAlchemy's asyncio support (SQLAlchemy 2.1 does not install it on its own). The file is MIT; a few platform source files derive from Stackless Python and carry the PSF licence (`LICENSE.PSF`, not opened). Both identifiers are on the allow-list. |
| itsdangerous | BSD-3-Clause | pallets/itsdangerous `LICENSE.txt` | 2026-10-17 | Re-read at tag 2.2.0 for the lock: three-clause BSD, Copyright 2011 Pallets. The package metadata only says "BSD License", so it is recorded in `licence-exceptions.txt`. |
| jinja2 | BSD-3-Clause | pallets/jinja `LICENSE.txt` | 2026-10-17 | Re-read at tag 3.1.6 for the lock: three-clause BSD, Copyright 2007 Pallets. The package metadata only says "BSD License", so it is recorded in `licence-exceptions.txt`. |
| pydantic | MIT | pydantic/pydantic `LICENSE` | 2026-10-17 | |
| python-multipart | Apache-2.0 | Kludex/python-multipart `LICENSE.txt` | 2026-10-17 | The file keeps the template copyright line `[yyyy] [name of copyright owner]`. |
| PyYAML | MIT | yaml/pyyaml `LICENSE` | 2026-10-17 | |
| sqlalchemy | MIT | sqlalchemy/sqlalchemy `LICENSE` | 2026-10-17 | |
| uvicorn | BSD-3-Clause | encode/uvicorn `LICENSE.md` | 2026-10-17 | |

## Transitive runtime package that needed a policy decision: cffi (MIT-0)

cffi is not a direct dependency. argon2-cffi-bindings requires it. Its metadata
declares the SPDX expression `MIT-0` and its LICENSE file (python-cffi/cffi
`LICENSE` at tag v2.1.1, read 2026-10-17) is the "MIT No Attribution" licence:
the MIT grant without the attribution condition. It is strictly more permissive
than MIT, so phase 0 added `MIT-0` to the allow-list in
`tools/licence_audit.py` rather than recording an exception (an exception cannot
admit an identifier that is off the list). MIT-0 is NOT on the allow-list of the
approved phase plan (merge gate check 6 of phase-plan-3), so this addition is a
deviation that needs an R&D decision. It cannot simply be removed: cffi is in the
runtime lock, so check 6 would fail. R&D is asked to confirm the addition or to
choose another resolution.

## Front-end assets (vendored in phase 1, not in the repository yet)

| Asset | SPDX identifier | LICENSE file read | Date read | Notes |
| --- | --- | --- | --- | --- |
| htmx | 0BSD | bigskysoftware/htmx `LICENSE` | 2026-10-17 | The file is titled "Zero-Clause BSD". |
| Pico CSS | MIT | picocss/pico `LICENSE.md` | 2026-10-17 | |

## Planned dependencies not yet in `requirements.in`

| Dependency | Needed from | Status |
| --- | --- | --- |
| openpyxl | phase 3 or 4 (XLSX import) | LICENSE file NOT read. Its source lives on foss.heptapod.net, which the phase 0 run could not read. Read it before adding the dependency. |
| httpx | development tests now; possibly runtime later | Direct dependency of the development group only, see the decision below. LICENSE (BSD-3-Clause) read in encode/httpx `LICENSE.md` on 2026-10-17. |
| hypothesis | phase 2 (development only) | Not added yet. LICENSE file not read. |

## Open licence decision for R&D: httpx pulls in certifi (MPL-2.0)

httpx depends on certifi, whose licence is MPL-2.0. The allow-list permits
MPL-2.0 only for development packages, so httpx cannot be a runtime dependency
under the current policy. Phase 0 therefore keeps httpx in `requirements-dev.in`
(the tests need it) and the runtime lock stays free of certifi. Phase 7 does not
need httpx (dnspython is ISC). Before any phase makes httpx a runtime
dependency, R&D must either allow MPL-2.0 as an unmodified, dynamically used
runtime package with a notice, or choose another HTTP client. This phase makes
neither decision.

## Packages not yet read

- Development group (`requirements-dev.in`): pytest, pytest-asyncio, pytest-cov,
  mypy, ruff, pip-tools. Their LICENSE files have not been read. They never enter
  the image, and the audit runs with `--allow-mpl-dev` for them.
- Transitive runtime packages: `requirements.txt` is now produced by
  the lock mode of `ci.yml` and the licence audit (check 6) runs in CI on every
  installed package, runtime and development. A package whose metadata is
  ambiguous fails the audit and is resolved in `licence-exceptions.txt` after its
  LICENSE file is read; the exceptions recorded so far are the ones named in the
  tables above.

## Database driver spike: asyncpg with Alembic

Question: does SQLAlchemy 2 async on asyncpg work with Alembic's async
`env.py`, advisory locks, and the up, check, down, up migration cycle that
merge gate check 4 runs?

Decision: asyncpg (Apache-2.0, LICENSE file read above) is the driver.
`DATABASE_URL` uses `postgresql+asyncpg://`. pg8000 is the fallback only if the
spike fails, after reading its LICENSE file; it is not adopted.

Evidence: `tests/test_db_spike.py` runs, against PostgreSQL 16, `alembic upgrade
head`, `alembic check`, `alembic downgrade -1`, `alembic upgrade head`, and two
connections competing for the same advisory lock. The test is executed by the
merge gate (check 3, with a PostgreSQL 16 service container, and check 4 for the
migration cycle); the gate fails if any test is skipped, so the spike cannot pass
silently without a database. The decision stands on those checks being green on
the commit that is merged (CI run ids are recorded on the pull request).
