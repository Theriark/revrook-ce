"""The DNS check through the API: run it, read PC-EML-01 to 03 with capture times.

These tests need PostgreSQL (DATABASE_URL), like the other API tests. The resolver of
the application is replaced by a fake one, and nothing reaches the network.
"""

from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.checks.dnscheck import TIMEOUT, LookupFailure
from app.dns_resolver import DnsPythonResolver, DohResolver
from app.main import create_app
from app.settings import Settings
from dns_helpers import StaticResolver, resolver_for, zone
from helpers import FakeClock, issue_token

DOMAIN = "client.example"
SPF = "v=spf1 include:spf.protection.outlook.com -all"
DMARC = "v=DMARC1; p=reject; rua=mailto:dmarc@client.example"
GOOD = zone(DOMAIN, spf=[SPF], dmarc=[DMARC], cnames=["selector1"])
DOWN = {**GOOD, (DOMAIN, "TXT"): LookupFailure(TIMEOUT)}


async def start(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> tuple[dict[str, str], int]:
    """A bearer header and the id of a new client."""
    token = {"Authorization": f"Bearer {await issue_token(db_engine)}"}
    created = await client.post(
        "/api/v1/clients", headers=token, json={"name": "Dns Client Ltd"}
    )
    return token, created.json()["id"]


def path_of(client_id: int) -> str:
    return f"/api/v1/clients/{client_id}/dns-check"


def use(web_app: FastAPI, resolver: StaticResolver) -> StaticResolver:
    web_app.state.dns_resolver = resolver
    return resolver


def by_id(controls: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(item["control_id"]): item for item in controls}


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("header", [{}, {"Authorization": "Bearer rvk_wrong"}])
async def test_the_dns_check_needs_a_valid_token(
    client: httpx.AsyncClient,
    db_engine: AsyncEngine,
    method: str,
    header: dict[str, str],
) -> None:
    _, client_id = await start(client, db_engine)
    response = await client.request(
        method, path_of(client_id), headers=header, json={"domains": [DOMAIN]}
    )
    # A POST with no credential at all is stopped by the CSRF check, before the token.
    refused = 403 if method == "POST" and not header else 401
    assert response.status_code == refused


async def test_a_run_is_stored_and_the_controls_show_their_capture_time(
    client: httpx.AsyncClient,
    db_engine: AsyncEngine,
    web_app: FastAPI,
    clock: FakeClock,
) -> None:
    token, client_id = await start(client, db_engine)
    resolver = use(web_app, resolver_for(GOOD))
    posted = await client.post(
        path_of(client_id), headers=token, json={"domains": [DOMAIN]}
    )
    assert posted.status_code == 201
    stored = posted.json()
    assert stored["source_code"] == "dns-check"
    assert stored["captured_at"] == clock.now.isoformat()
    assert resolver.queries, "the fake resolver was asked"
    read = await client.get(path_of(client_id), headers=token)
    assert read.status_code == 200
    controls = by_id(read.json()["controls"])
    assert list(controls) == ["PC-EML-01", "PC-EML-02", "PC-EML-03"]
    assert controls["PC-EML-01"]["status"] == "pass"
    assert controls["PC-EML-03"]["status"] == "pass"
    for control_id in ("PC-EML-01", "PC-EML-03"):
        assert controls[control_id]["evidence_at"] == clock.now.isoformat()


async def test_a_timeout_is_unknown_with_a_reason_and_not_a_fail(
    client: httpx.AsyncClient, db_engine: AsyncEngine, web_app: FastAPI
) -> None:
    token, client_id = await start(client, db_engine)
    use(web_app, resolver_for(DOWN))
    posted = await client.post(
        path_of(client_id), headers=token, json={"domains": [DOMAIN]}
    )
    assert posted.status_code == 201
    read = await client.get(path_of(client_id), headers=token)
    controls = by_id(read.json()["controls"])
    for control_id in ("PC-EML-01", "PC-EML-03"):
        assert controls[control_id]["status"] == "unknown"
        assert controls[control_id]["reason"] == "lookup_failed"


async def test_a_client_without_a_run_has_unknown_controls(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token, client_id = await start(client, db_engine)
    read = await client.get(path_of(client_id), headers=token)
    controls = read.json()["controls"]
    assert [item["status"] for item in controls] == ["unknown"] * 3
    assert all(item["evidence_at"] is None for item in controls)


@pytest.mark.parametrize(
    "body",
    [
        {"domains": []},
        {"domains": ["not a domain"]},
        {"domains": [DOMAIN], "selectors": ["bad selector"]},
        {"domains": [DOMAIN], "providers": ["nope"]},
        {"domains": [f"d{number}.example" for number in range(21)]},
        {"domains": ["x" * 300 + ".example"]},
        {},
    ],
    ids=[
        "none",
        "invalid",
        "selector",
        "provider",
        "too-many",
        "too-long",
        "missing",
    ],
)
async def test_a_refused_request_asks_the_dns_nothing(
    client: httpx.AsyncClient,
    db_engine: AsyncEngine,
    web_app: FastAPI,
    body: dict[str, object],
) -> None:
    token, client_id = await start(client, db_engine)
    resolver = use(web_app, resolver_for(GOOD))
    response = await client.post(path_of(client_id), headers=token, json=body)
    assert response.status_code == 422
    assert resolver.queries == []
    read = await client.get(path_of(client_id), headers=token)
    assert all(item["evidence_at"] is None for item in read.json()["controls"])


@pytest.mark.parametrize(
    ("setting", "kind"),
    [
        (None, DnsPythonResolver),
        ("9.9.9.9", DnsPythonResolver),
        ("https://dns.example/dns-query", DohResolver),
    ],
)
async def test_the_application_builds_its_resolver_from_dns_resolver(
    settings: Settings,
    db_engine: AsyncEngine,
    setting: str | None,
    kind: type[object],
) -> None:
    app = create_app(replace(settings, dns_resolver=setting), engine=db_engine)
    assert type(app.state.dns_resolver) is kind


async def test_a_bad_dns_resolver_setting_stops_the_start(
    settings: Settings, db_engine: AsyncEngine
) -> None:
    with pytest.raises(ValueError, match="DNS_RESOLVER"):
        create_app(replace(settings, dns_resolver="not an address"), engine=db_engine)


async def test_an_unknown_client_is_404_before_any_lookup(
    client: httpx.AsyncClient, db_engine: AsyncEngine, web_app: FastAPI
) -> None:
    token, _ = await start(client, db_engine)
    resolver = use(web_app, resolver_for(GOOD))
    posted = await client.post(
        path_of(987_654_321), headers=token, json={"domains": [DOMAIN]}
    )
    assert posted.status_code == 404
    assert (await client.get(path_of(987_654_321), headers=token)).status_code == 404
    assert resolver.queries == []
