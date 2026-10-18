"""The generic importers through the evidence store and the API (synthetic data)."""

import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.evidence.assurance import Assurance
from app.evidence.errors import EvidenceRejectedError
from app.evidence.service import EvidenceContext, NewEvidence
from app.importers.profiles import save_profile
from app.models import Fact
from app.settings import Settings
from helpers import (
    NOW,
    create_test_client,
    database_dump,
    issue_token,
    make_context,
    upload,
)
from tools import make_generic_fixtures
from tools.make_fixtures import DOMAIN, Fixture, to_csv, user_name
from tools.make_generic_fixtures import UNREAD_VALUES

UPLOADED_AT = NOW - timedelta(days=1)
EVERY = make_generic_fixtures.generic_fixtures()
PSEUDONYM = re.compile(r"[0-9a-f]{16}")
VENDOR_HEADER = [
    "Computer",
    "Operating system",
    "Last check-in",
    "Patches",
    "Critical updates",
    "AV product",
    "AV state",
    "AV signatures",
    "Encrypted",
]
VENDOR_ROW = [
    "vendor-host-1",
    "Windows 11",
    "2026-10-16T08:00:00",
    "up_to_date",
    "0",
    "Synthetic Shield",
    "protected",
    "2026-10-15T08:00:00Z",
    "true",
]
VENDOR_MAPPING = {
    "Computer": "hostname",
    "Operating system": "os",
    "Last check-in": "last_seen",
    "Patches": "patch_status",
    "Critical updates": "pending_critical_updates",
    "AV product": "av_product",
    "AV state": "av_status",
    "AV signatures": "av_signature_date",
    "Encrypted": "disk_encrypted",
}


@pytest.fixture
def ctx(settings: Settings, tmp_path: Path) -> EvidenceContext:
    return make_context(settings, tmp_path)


def export(source: str, data: bytes, profile: int | None = None) -> NewEvidence:
    return NewEvidence(
        source_code=source,
        assurance=Assurance.AUTOMATIC_EXPORT,
        captured_at=UPLOADED_AT,
        data=data,
        profile_id=profile,
    )


async def facts_of(engine: AsyncEngine, item_id: int) -> list[Fact]:
    query = select(Fact).where(Fact.evidence_item_id == item_id).order_by(Fact.id)
    async with async_sessionmaker(engine)() as session:
        return list((await session.execute(query)).scalars())


def summary_of(facts: list[Fact]) -> dict[str, Any]:
    (found,) = [fact for fact in facts if fact.fact_key.endswith(".summary")]
    return found.value


@pytest.mark.parametrize("fixture", EVERY, ids=lambda fixture: fixture.file_name)
async def test_each_fixture_is_stored_with_its_expected_counts_and_flags(
    db_engine: AsyncEngine, ctx: EvidenceContext, fixture: Fixture
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    evidence = export(fixture.source_code, fixture.data)
    stored = await upload(db_engine, ctx, client_id, evidence)
    assert stored.facts == fixture.facts
    assert stored.captured_at == UPLOADED_AT
    facts = await facts_of(db_engine, stored.item_id)
    assert summary_of(facts) == fixture.expected


async def test_no_identifier_and_no_free_text_reaches_the_database(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    for fixture in EVERY:
        evidence = export(fixture.source_code, fixture.data)
        await upload(db_engine, ctx, client_id, evidence)
    dump = await database_dump(db_engine)
    assert "inventory.device" in dump
    for value in UNREAD_VALUES:
        assert value not in dump, value
    for number in range(1, 9):
        assert user_name(number).split("@")[0] not in dump


async def test_one_person_has_one_pseudonym_across_the_generic_sources(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    by_file = {fixture.file_name: fixture for fixture in EVERY}
    names = {
        "training": ("training-csv", "training.csv", "training.completion"),
        "device": ("device-inventory", "device-inventory.csv", "inventory.device"),
    }
    people: dict[str, set[str]] = {}
    for label, (source, file_name, key) in names.items():
        stored = await upload(
            db_engine, ctx, client_id, export(source, by_file[file_name].data)
        )
        found = await facts_of(db_engine, stored.item_id)
        people[label] = {f.value["user"] for f in found if f.fact_key == key}
    assert len(people["training"]) == 5
    assert people["training"] == people["device"] & people["training"]
    assert all(PSEUDONYM.fullmatch(pseudonym) for pseudonym in people["training"])


async def test_an_email_like_text_rejects_the_row_and_not_the_upload(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    data = (
        "User principal name,Role\n"
        f"{user_name(1)},Global Administrator\n"
        f"{user_name(2)},admin@{DOMAIN}\n"
    ).encode()
    stored = await upload(db_engine, ctx, client_id, export("directory-roles", data))
    summary = summary_of(await facts_of(db_engine, stored.item_id))
    assert (summary["assignments"], summary["rows_rejected"]) == (1, 1)
    assert DOMAIN not in await database_dump(db_engine)


async def test_a_wrong_file_is_rejected_naming_the_missing_column(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    leavers = next(f for f in EVERY if f.source_code == "leavers-csv")
    with pytest.raises(EvidenceRejectedError, match="missing the column course"):
        await upload(
            db_engine, ctx, client_id, export("training-csv", leavers.data + b"\n")
        )


async def test_a_saved_mapping_lets_a_vendor_style_file_in(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    data = to_csv(VENDOR_HEADER, [VENDOR_ROW])
    with pytest.raises(EvidenceRejectedError, match="missing the column"):
        await upload(db_engine, ctx, client_id, export("device-inventory", data))
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        profile = await save_profile(
            session,
            ctx.importers,
            client_id,
            name="Vendor devices",
            source_code="device-inventory",
            mapping=VENDOR_MAPPING,
            actor_user_id=None,
        )
    evidence = export("device-inventory", data, profile.id)
    stored = await upload(db_engine, ctx, client_id, evidence)
    summary = summary_of(await facts_of(db_engine, stored.item_id))
    assert (summary["devices"], summary["windows"]) == (1, 1)
    assert summary["timezone_assumed_utc"] is True


async def test_every_generic_source_accepts_a_mapping(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    for fixture in EVERY:
        importer = ctx.importers.get(fixture.source_code)
        assert importer is not None
        columns = importer.columns
        async with factory() as session, session.begin():
            profile = await save_profile(
                session,
                ctx.importers,
                client_id,
                name=f"Map {fixture.source_code}",
                source_code=fixture.source_code,
                mapping={"Vendor name": columns[0].key},
                actor_user_id=None,
            )
        assert profile.mapping == {"Vendor name": columns[0].key}


async def test_the_api_saves_a_mapping_and_an_upload_names_it(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = {"Authorization": f"Bearer {await issue_token(db_engine)}"}
    created = await client.post(
        "/api/v1/clients", headers=token, json={"name": "Vendor Api Client"}
    )
    client_id = created.json()["id"]
    body = {
        "name": "Vendor devices",
        "source_code": "device-inventory",
        "mapping": VENDOR_MAPPING,
    }
    profiles = f"/api/v1/clients/{client_id}/import-profiles"
    saved = await client.post(profiles, headers=token, json=body)
    assert saved.status_code == 201, saved.text
    assert saved.json()["mapping"] == VENDOR_MAPPING
    bad = {"mapping": {"Computer": "no_such_column"}}
    refused = await client.post(profiles, headers=token, json={**body, **bad})
    assert refused.status_code == 422
    assert "which this source does not have" in refused.json()["detail"]

    form = {
        "source_code": "device-inventory",
        "captured_at": UPLOADED_AT.isoformat(),
    }
    files = {"file": ("vendor.csv", to_csv(VENDOR_HEADER, [VENDOR_ROW]), "text/csv")}
    uploads = f"/api/v1/clients/{client_id}/evidence"
    without = await client.post(uploads, headers=token, data=form, files=files)
    assert without.status_code == 422
    assert "missing the column" in without.json()["detail"]
    named = {**form, "profile_id": str(saved.json()["id"])}
    accepted = await client.post(uploads, headers=token, data=named, files=files)
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["facts"] == 2
