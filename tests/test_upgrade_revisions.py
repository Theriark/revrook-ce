"""The upgrade test seeds every schema revision that holds tables (phase 11).

`tests/test_upgrade.py` lists the revisions it seeds by hand. This test keeps that list
equal to the revisions of the repository, so a new migration cannot be skipped by the
upgrade test without a test failing. Files only: no database.
"""

from alembic.config import Config
from alembic.script import ScriptDirectory
from test_upgrade import ROOT, SEEDED_REVISIONS, newest_revision

BASELINE = "0001"


def test_seeded_revisions_are_all_but_the_baseline_and_the_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    head = newest_revision()
    revisions = [revision.revision for revision in script.walk_revisions()]
    assert head in revisions
    assert len({revision[:4] for revision in revisions}) == len(revisions)
    expected = sorted(
        revision[:4]
        for revision in revisions
        if revision != head and not revision.startswith(BASELINE)
    )
    assert sorted(SEEDED_REVISIONS) == expected
