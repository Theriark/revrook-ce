"""The synthetic files of the Development seed (app/devdata.py; THE-953).

No database is used: every file is read by the real importer of its source, so a
change to an importer that the seed no longer fits fails here, and a new source that
has no seed file fails too.
"""

import re
from datetime import UTC, datetime, timedelta

import pytest

from app import devdata
from app.checks.dnscheck import render_document, run_checks
from app.evidence.files import sha256_hex
from app.importers.dnscheck import DnsCheckImporter
from app.importers.registry import build_default_registry
from app.sources import DNS_SOURCE, SOURCE_NAMES

CAPTURED = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)
ADDRESS = re.compile(r"[\w.+-]+@([\w.-]+)")
# A word that names a secret, followed by a value (the field isPasswordlessCapable
# is a flag, not a password).
SECRET = re.compile(
    r"\b(password|secret|token|api_?key)\b[\"']?\s*[:=]|begin [a-z ]*key"
)
MAX_ROWS = 1000


def test_every_source_of_the_product_has_a_seed_file_or_is_the_dns_check() -> None:
    imported = set(build_default_registry().source_codes())
    assert imported | {DNS_SOURCE} == set(SOURCE_NAMES)
    assert set(devdata.BUILDERS) == imported
    assert set(devdata.SOURCES) == set(SOURCE_NAMES)
    for profile in devdata.PROFILES:
        codes = [seed.source_code for seed in devdata.seed_files(profile, CAPTURED)]
        assert codes == list(devdata.BUILDERS)


@pytest.mark.parametrize("profile", devdata.PROFILES)
def test_every_file_is_read_by_the_importer_of_its_source(profile: str) -> None:
    registry = build_default_registry()
    for seed in devdata.seed_files(profile, CAPTURED):
        importer = registry.get(seed.source_code)
        assert importer is not None, seed.source_code
        result = importer.parse(seed.data, MAX_ROWS)
        assert result.facts, seed.source_code
        for fact in result.facts:
            assert fact.value.get("rows_rejected", 0) == 0, seed.source_code


def test_the_files_depend_only_on_the_profile_and_the_capture_time() -> None:
    again = devdata.seed_files(devdata.TIDY, CAPTURED)
    assert again == devdata.seed_files(devdata.TIDY, CAPTURED)
    later = devdata.seed_files(devdata.TIDY, CAPTURED + timedelta(days=1))
    for before, after in zip(again, later, strict=True):
        assert before.data != after.data, before.source_code


def test_the_two_profiles_differ_for_every_source() -> None:
    tidy = devdata.seed_files(devdata.TIDY, CAPTURED)
    gaps = devdata.seed_files(devdata.GAPS, CAPTURED)
    for left, right in zip(tidy, gaps, strict=True):
        assert left.data != right.data, left.source_code


def test_no_file_of_a_client_repeats_another_round_of_the_same_client() -> None:
    # The evidence store refuses a file the client already has (same SHA-256), so
    # each round of one client must be different bytes in every source.
    seen: set[str] = set()
    for days in (60, 30, 0):
        captured = CAPTURED - timedelta(days=days)
        for seed in devdata.seed_files(devdata.GAPS, captured):
            digest = sha256_hex(seed.data)
            assert digest not in seen, (days, seed.source_code)
            seen.add(digest)


def test_the_files_hold_no_real_address_and_no_secret() -> None:
    for profile in devdata.PROFILES:
        for seed in devdata.seed_files(profile, CAPTURED):
            text = seed.data.decode("utf-8")
            for domain in ADDRESS.findall(text):
                assert domain.endswith(".invalid"), (seed.source_code, domain)
            assert SECRET.search(text.lower()) is None, seed.source_code


def test_an_unknown_profile_is_refused() -> None:
    with pytest.raises(ValueError, match="profile must be one of"):
        devdata.seed_files("nonsense", CAPTURED)


def test_the_dns_check_reads_a_table_and_the_profiles_differ() -> None:
    values = {}
    for profile in devdata.PROFILES:
        resolver = devdata.SeedResolver(profile)
        check = run_checks(
            resolver,
            [devdata.MAIL_DOMAINS[profile]],
            devdata.SELECTORS,
            (),
            captured_at=CAPTURED,
        )
        result = DnsCheckImporter().parse(render_document(check), MAX_ROWS)
        assert len(result.facts) == 2
        values[profile] = result.facts[0].value
    assert values[devdata.TIDY]["dmarc_policy"] == "reject"
    assert values[devdata.TIDY]["dkim_found"] == len(devdata.SELECTORS)
    assert values[devdata.GAPS]["dmarc_records"] == 0
    assert values[devdata.GAPS]["dkim_found"] == 0
