"""Expiry reminders use the age the checklist uses (no database)."""

from datetime import UTC, datetime, timedelta

from app.checks.library import load_library
from app.evidence.assurance import Assurance
from app.sources import source_max_ages
from app.worker.reminders import effective_expiry

AGES = source_max_ages(load_library())
CAPTURED = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
STORE = CAPTURED + timedelta(days=35)
AUTOMATIC = Assurance.AUTOMATIC_EXPORT.value


def test_a_device_export_goes_stale_at_the_strictest_control_age() -> None:
    assert AGES["device-inventory"] == 7
    expiry = effective_expiry("device-inventory", AUTOMATIC, CAPTURED, STORE, AGES)
    assert expiry == CAPTURED + timedelta(days=7)


def test_a_source_read_at_35_days_keeps_the_store_expiry() -> None:
    expiry = effective_expiry("entra-registration", AUTOMATIC, CAPTURED, STORE, AGES)
    assert expiry == STORE


def test_a_manual_item_and_an_unknown_source_keep_their_own_expiry() -> None:
    manual = Assurance.MANUAL_ARTEFACT.value
    assert effective_expiry("device-inventory", manual, CAPTURED, STORE, AGES) == STORE
    assert effective_expiry("unknown-source", AUTOMATIC, CAPTURED, STORE, AGES) == STORE
    assert effective_expiry("device-inventory", AUTOMATIC, CAPTURED, STORE, {}) == STORE
