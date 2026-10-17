"""The Microsoft importers through the evidence store (synthetic data only)."""

import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.evidence.assurance import Assurance
from app.evidence.errors import EvidenceError, EvidenceRejectedError
from app.evidence.service import EvidenceContext, NewEvidence
from app.importers.profiles import save_profile
from app.models import Fact
from app.settings import Settings
from helpers import (
    NOW,
    audit_baseline,
    audit_since,
    create_test_client,
    database_dump,
    issue_token,
    make_context,
    upload,
)
from tools import make_fixtures
from tools.make_fixtures import (
    CAPTURED_AT,
    DEVICE_NAME_PREFIX,
    DOMAIN,
    POLICY_NAMES,
    SENSITIVE_VALUES,
    Fixture,
)

UPLOADED_AT = NOW - timedelta(days=1)
MAIN = {fixture.source_code: fixture for fixture in make_fixtures.main_fixtures()}
EVERY = [*make_fixtures.main_fixtures(), *make_fixtures.variant_fixtures()]
PSEUDONYM = re.compile(r"[0-9a-f]{16}")
VENDOR_CSV = (
    "Account,Capable,Passwordless,Methods,Updated\n"
    f"user01@{DOMAIN},true,false,mobilePhone,2026-10-16T08:00:00Z\n"
).encode()
VENDOR_MAPPING = {
    "Account": "upn",
    "Capable": "mfa_capable",
    "Passwordless": "passwordless_capable",
    "Methods": "methods",
    "Updated": "updated",
}
NO_PROFILE = "no such mapping profile for this client and source"


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


def of(fixture: Fixture) -> NewEvidence:
    return export(fixture.source_code, fixture.data)


async def facts_of(engine: AsyncEngine, item_id: int) -> list[Fact]:
    query = select(Fact).where(Fact.evidence_item_id == item_id).order_by(Fact.id)
    async with async_sessionmaker(engine)() as session:
        return list((await session.execute(query)).scalars())


async def facts_in_database(engine: AsyncEngine) -> int:
    async with async_sessionmaker(engine)() as session:
        return len((await session.execute(select(Fact.id))).all())


def summary_of(facts: list[Fact]) -> dict[str, Any]:
    (found,) = [fact for fact in facts if fact.fact_key.endswith(".summary")]
    return found.value


@pytest.mark.parametrize("fixture", EVERY, ids=lambda fixture: fixture.file_name)
async def test_each_fixture_is_stored_with_its_expected_counts_and_flags(
    db_engine: AsyncEngine, ctx: EvidenceContext, fixture: Fixture
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    stored = await upload(db_engine, ctx, client_id, of(fixture))
    assert stored.facts == fixture.facts
    facts = await facts_of(db_engine, stored.item_id)
    assert len(facts) == fixture.facts
    assert summary_of(facts) == fixture.expected
    if fixture.expected["capture_time_source"] == "file":
        assert stored.captured_at != UPLOADED_AT
    else:
        assert stored.captured_at == UPLOADED_AT


async def test_the_capture_time_comes_from_the_file_and_is_flagged_when_it_does_not(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    with_time = await upload(db_engine, ctx, client_id, of(MAIN["entra-registration"]))
    assert with_time.captured_at == CAPTURED_AT
    assert with_time.expires_at == CAPTURED_AT + timedelta(days=35)

    without = await upload(db_engine, ctx, client_id, of(MAIN["conditional-access"]))
    assert without.captured_at == UPLOADED_AT
    summary = summary_of(await facts_of(db_engine, without.item_id))
    assert summary["capture_time_source"] == "upload"
    assert summary["timezone_assumed_utc"] is False

    # A file that gives a time without a zone is read as UTC and says so.
    intune = await upload(db_engine, ctx, client_id, of(MAIN["intune-devices"]))
    flagged = summary_of(await facts_of(db_engine, intune.item_id))
    assert flagged["timezone_assumed_utc"] is True


async def test_no_sensitive_field_and_no_free_text_reaches_the_database(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    for fixture in EVERY:
        await upload(db_engine, ctx, client_id, of(fixture))
    dump = await database_dump(db_engine)
    assert "intune.device" in dump
    for value in SENSITIVE_VALUES:
        assert value not in dump, value
    # The field names are searched in the facts only: the other tables hold random
    # encrypted keys in which a short word could appear by chance.
    async with async_sessionmaker(db_engine)() as session:
        stored_facts = (await session.execute(select(Fact.fact_key, Fact.value))).all()
    text = json.dumps([[key, value] for key, value in stored_facts]).lower()
    assert "intune.device" in text
    for word in ("imei", "phonenumber", "activationlockbypasscode"):
        assert word not in text, word
    assert DOMAIN not in dump
    assert DEVICE_NAME_PREFIX not in dump
    assert "Fixture User" not in dump
    for name in POLICY_NAMES:
        assert name not in dump


async def test_one_person_has_one_pseudonym_per_client_across_the_sources(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    first = await create_test_client(db_engine, ctx, "First Client")
    second = await create_test_client(db_engine, ctx, "Second Client")

    async def users(client_id: int, source: str, key: str) -> set[str]:
        stored = await upload(db_engine, ctx, client_id, of(MAIN[source]))
        found = await facts_of(db_engine, stored.item_id)
        return {fact.value["user"] for fact in found if fact.fact_key == key}

    in_entra = await users(first, "entra-registration", "entra.user")
    in_roles = await users(first, "directory-roles", "roles.assignment")
    elsewhere = await users(second, "entra-registration", "entra.user")
    assert len(in_entra) == 12
    assert in_roles
    assert in_roles <= in_entra
    assert all(PSEUDONYM.fullmatch(pseudonym) for pseudonym in in_entra)
    assert not in_entra & elsewhere


async def test_a_wrong_file_is_rejected_naming_the_missing_column(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    intune = MAIN["intune-devices"].data
    with pytest.raises(EvidenceRejectedError) as csv_error:
        await upload(db_engine, ctx, client_id, export("entra-registration", intune))
    assert "missing the column User principal name" in str(csv_error.value)
    assert "This looks like an Intune devices export" in str(csv_error.value)

    entra = MAIN["entra-registration"].data
    with pytest.raises(EvidenceRejectedError) as json_error:
        await upload(db_engine, ctx, client_id, export("conditional-access", entra))
    assert "missing the field state, conditions" in str(json_error.value)
    assert "This looks like an Entra authentication-methods" in str(json_error.value)
    assert await facts_in_database(db_engine) == 0


async def test_hostile_files_are_rejected_or_neutralised_by_the_store(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    formula = (
        "User principal name,Role,Enabled\n"
        f'user01@{DOMAIN},"=HYPERLINK(""http://x.invalid"")",true\n'
    ).encode()
    stored = await upload(db_engine, ctx, client_id, export("directory-roles", formula))
    (assignment,) = [
        fact
        for fact in await facts_of(db_engine, stored.item_id)
        if fact.fact_key == "roles.assignment"
    ]
    assert assignment.value["role"].startswith("'=")

    deep = json.dumps({"value": []})
    for _ in range(40):
        deep = f'{{"value": [{deep}]}}'
    with pytest.raises(EvidenceRejectedError, match="nested deeper"):
        await upload(
            db_engine, ctx, client_id, export("entra-registration", deep.encode())
        )

    huge = b"User principal name,Role\n" + b"x" * 200_000 + b",admin\n"
    with pytest.raises(EvidenceRejectedError, match="not a readable CSV"):
        await upload(db_engine, ctx, client_id, export("directory-roles", huge))

    bom = (
        b"\xef\xbb\xbfUser principal name,Role\r\n"
        + f"user02@{DOMAIN},Global Administrator\r\n".encode()
    )
    kept = await upload(db_engine, ctx, client_id, export("directory-roles", bom))
    assert summary_of(await facts_of(db_engine, kept.item_id))["global_admins"] == 1


async def test_a_file_in_which_no_row_can_be_read_stores_nothing(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    data = b"User principal name,Role\n,Global Administrator\n,Exchange Administrator\n"
    with pytest.raises(EvidenceRejectedError, match="No row of the file could be read"):
        await upload(db_engine, ctx, client_id, export("directory-roles", data))
    assert await facts_in_database(db_engine) == 0


async def test_a_saved_mapping_lets_a_vendor_style_file_in(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    other_client = await create_test_client(db_engine, ctx, "Other Client")
    plain = export("entra-registration", VENDOR_CSV)
    with pytest.raises(EvidenceRejectedError, match="missing the column"):
        await upload(db_engine, ctx, client_id, plain)

    baseline = await audit_baseline(db_engine)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        profile = await save_profile(
            session,
            ctx.importers,
            client_id,
            name=" Vendor export ",
            source_code="entra-registration",
            mapping={f" {header} ": key for header, key in VENDOR_MAPPING.items()},
            actor_user_id=None,
        )
    assert profile.name == "Vendor export"
    assert profile.mapping == VENDOR_MAPPING
    events = await audit_since(db_engine, baseline)
    assert [event.action for event in events] == ["import_profile.created"]
    assert events[0].detail == {
        "client_id": client_id,
        "source_code": "entra-registration",
    }

    entra = export("entra-registration", VENDOR_CSV, profile.id)
    stored = await upload(db_engine, ctx, client_id, entra)
    summary = summary_of(await facts_of(db_engine, stored.item_id))
    assert (summary["users"], summary["mfa_capable"]) == (1, 1)

    # Another client, another source and an unknown profile are all refused.
    with pytest.raises(EvidenceRejectedError, match=NO_PROFILE):
        await upload(db_engine, ctx, other_client, entra)
    roles = export("directory-roles", VENDOR_CSV + b"\n", profile.id)
    with pytest.raises(EvidenceRejectedError, match=NO_PROFILE):
        await upload(db_engine, ctx, client_id, roles)
    unknown = export("entra-registration", VENDOR_CSV + b"\n\n", 987_654_321)
    with pytest.raises(EvidenceRejectedError, match=NO_PROFILE):
        await upload(db_engine, ctx, client_id, unknown)


async def test_a_profile_is_for_an_automatic_export_only(
    db_engine: AsyncEngine, ctx: EvidenceContext
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    statement = NewEvidence(
        source_code="training-statement",
        assurance=Assurance.ATTESTATION,
        captured_at=UPLOADED_AT,
        reviewer="Sam Reviewer",
        reviewed_on=UPLOADED_AT.date(),
        note="Staff training was completed",
        profile_id=1,
    )
    with pytest.raises(EvidenceRejectedError, match="applies to an automatic export"):
        await upload(db_engine, ctx, client_id, statement)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"source_code": "no-such-source"}, "There is no importer"),
        ({"source_code": "reference-csv"}, "does not read CSV files"),
        ({"source_code": "conditional-access"}, "does not read CSV files"),
        ({"name": "  "}, "profile name must be 1 to 100"),
        ({"name": "bad\x00name"}, "must be printable text"),
        ({"mapping": {}}, "at least one column"),
        ({"mapping": {"A": "nope"}}, "which this source does not have"),
        ({"mapping": {"": "upn"}}, "file column name must be 1 to 100"),
        ({"mapping": {"A": "upn", "B": "upn"}}, "mapped to the same column"),
        ({"mapping": {f"C{n}": "upn" for n in range(101)}}, "at most 100 columns"),
        ({"client_id": 987_654_321}, "no client with this id"),
    ],
)
async def test_a_mapping_that_cannot_be_used_is_refused(
    db_engine: AsyncEngine,
    ctx: EvidenceContext,
    changes: dict[str, Any],
    message: str,
) -> None:
    client_id = await create_test_client(db_engine, ctx)
    arguments: dict[str, Any] = {
        "client_id": client_id,
        "name": "Vendor export",
        "source_code": "entra-registration",
        "mapping": {"Account": "upn"},
        **changes,
    }
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    with pytest.raises(EvidenceError, match=message):
        async with factory() as session, session.begin():
            await save_profile(session, ctx.importers, actor_user_id=None, **arguments)


async def test_the_api_saves_a_mapping_and_an_upload_names_it(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token = {"Authorization": f"Bearer {await issue_token(db_engine)}"}
    created = await client.post(
        "/api/v1/clients", headers=token, json={"name": "Api Client Ltd"}
    )
    client_id = created.json()["id"]
    profiles = f"/api/v1/clients/{client_id}/import-profiles"
    body = {
        "name": "Vendor export",
        "source_code": "entra-registration",
        "mapping": VENDOR_MAPPING,
    }

    refused = await client.post(profiles, headers=token, json={**body, "mapping": {}})
    assert refused.status_code == 422
    assert "at least one column" in refused.json()["detail"]
    missing = await client.post(
        "/api/v1/clients/987654321/import-profiles", headers=token, json=body
    )
    assert missing.status_code == 404
    assert (await client.post(profiles, json=body)).status_code == 401
    saved = await client.post(profiles, headers=token, json=body)
    assert saved.status_code == 201
    assert saved.json()["mapping"] == VENDOR_MAPPING
    profile_id = saved.json()["id"]

    uploads = f"/api/v1/clients/{client_id}/evidence"
    form = {
        "source_code": "entra-registration",
        "captured_at": UPLOADED_AT.isoformat(),
    }
    files = {"file": ("export.csv", VENDOR_CSV, "text/csv")}
    without = await client.post(uploads, headers=token, data=form, files=files)
    assert without.status_code == 422
    assert "missing the column" in without.json()["detail"]
    for bad in ("abc", "-1", "1.5"):
        wrong = await client.post(
            uploads, headers=token, data={**form, "profile_id": bad}, files=files
        )
        assert wrong.status_code == 422, bad
        assert "must be a whole number" in wrong.json()["detail"]
    accepted = await client.post(
        uploads,
        headers=token,
        data={**form, "profile_id": str(profile_id)},
        files=files,
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["facts"] == 2
