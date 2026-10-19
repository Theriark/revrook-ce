# Contributing

revrook-ce is pre-release. Contributions are welcome once the first application phase has landed; until then, expect rapid change.

## Licence of contributions

By submitting a contribution you agree that it is licensed under the [MIT licence](LICENSE) of this repository.

## Branches and pull requests

- Never commit directly to `development`, `stage`, `production` or `main`.
- Work on a feature branch named `feat/revrook-ce-<phase or topic>` and open a draft pull request into `development` (or into another feature branch when stacked).
- Keep one pull request to one reviewable change.
- Mark the pull request ready only when the CI merge gate (`Merge gate summary`) is green and the checklist in the pull request template is complete.
- The author of a pull request does not review it.

## Local checks

The merge gate runs ruff, mypy, pytest with PostgreSQL 16, alembic migration checks, pip-audit, a licence audit, a docker build and a compose smoke test. See [docs/ci-cd.md](docs/ci-cd.md) for the details and for which checks are active.

## Documentation

The pages are in `docs/` and indexed in the [README](README.md). `tests/test_docs.py` checks that every link between pages works, that [docs/configuration.md](docs/configuration.md) matches `app/settings.py` and that the README keeps its statements, so a change to a setting or a page comes with its test run. Add a line to the [CHANGELOG](CHANGELOG.md) under Unreleased for a change that a user would notice.

A mapping row to an outside framework is marked verified only by a person who has read its source and added a line to the register in [docs/mapping-verification.md](docs/mapping-verification.md); `python -m app.cli verify-mappings` checks that the two agree.

## Security

Report vulnerabilities privately, see [SECURITY.md](SECURITY.md). Never commit secrets, credentials or real client data.
