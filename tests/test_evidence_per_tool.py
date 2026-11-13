"""Several tools export one source for a client: the newest file of each counts.

A device, backup or network file may name the tool that wrote it (`tool`). The
checks read the newest file of each tool of such a source together (app/posture.py).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.checks.model import SourceFacts
from app.evidence.assurance import Assurance
from app.evidence.service import NewEvidence
from app.importers.generic import ADAPTERS
from app.posture import TOOL_WINDOW, load_sources, merged, newest_items, per_tool
from app.settings import Settings
from helpers import NOW as STORE_NOW
from helpers import create_test_client, make_context, upload

NETWORK = next(a for a in ADAPTERS if a.source_code == "network-export")
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
HEADER = "record_type,device_id,rule_enabled,direction,action,source,destination_port"


@dataclass(frozen=True)
class Item:
    name: str
    source_code: str
    captured_at: datetime


def at(days: float) -> datetime:
    return NOW - timedelta(days=days)


def summary(text: str) -> dict:
    result = NETWORK.parse(text.encode(), 100)
    return dict(result.facts[-1].value)


def test_a_file_names_its_tool_when_every_row_names_the_same() -> None:
    rule = "rule,sg-1,true,inbound,allow,any,22"
    assert summary(f"{HEADER},tool\n{rule},AWS\n{rule},aws\n")["tool"] == "aws"
    assert "tool" not in summary(f"{HEADER},tool\n{rule},aws\n{rule},gcp\n")
    assert "tool" not in summary(f"{HEADER}\n{rule}\n")


def test_the_newest_file_of_each_tool_counts() -> None:
    newest_first = [
        (Item("aws-new", "network-export", at(0)), "aws"),
        (Item("unifi", "network-export", at(3)), None),
        (Item("aws-old", "network-export", at(5)), "aws"),
        (Item("cloudflare", "network-export", at(6)), "cloudflare"),
        (Item("unifi-old", "network-export", at(9)), None),
        (Item("checkmk", "device-inventory", at(1)), None),
        (Item("checkmk-old", "device-inventory", at(2)), None),
    ]
    chosen = [item.name for item in per_tool(newest_first)]
    assert chosen == ["aws-new", "unifi", "cloudflare", "checkmk"]


def test_a_tool_no_longer_used_drops_out() -> None:
    newest_first = [
        (Item("aws", "backup-export", at(0)), "aws"),
        (Item("xo", "backup-export", at(TOOL_WINDOW.days)), "xo"),
        (Item("veeam", "backup-export", at(TOOL_WINDOW.days + 1)), "veeam"),
    ]
    assert [item.name for item in per_tool(newest_first)] == ["aws", "xo"]


def test_two_files_are_read_as_one_from_the_newer_capture() -> None:
    newer = SourceFacts.from_facts(
        at(0),
        [("network.rule", {"source": "any"}), ("network.summary", {"tool": "aws"})],
    )
    older = SourceFacts.from_facts(
        at(4),
        [("network.device", {"perimeter": True}), ("network.rule", {"source": None})],
    )
    both = merged(newer, older)
    assert both.captured_at == at(0)
    assert both.rows("rule") == ({"source": "any"}, {"source": None})
    assert both.rows("device") == ({"perimeter": True},)
    assert both.summary == {"tool": "aws"}


def network_file(tool: str | None, port: int, days: int) -> NewEvidence:
    head, cell = (f"{HEADER},tool", f",{tool}") if tool else (HEADER, "")
    rule = f"rule,fw,true,inbound,allow,any,{port}"
    return NewEvidence(
        source_code="network-export",
        assurance=Assurance.AUTOMATIC_EXPORT,
        captured_at=STORE_NOW - timedelta(days=days),
        data=f"{head}\n{rule}{cell}\n".encode(),
    )


async def test_the_checks_read_the_newest_file_of_each_tool(
    db_engine: AsyncEngine, settings: Settings, tmp_path: Path
) -> None:
    ctx = make_context(settings, tmp_path)
    client_id = await create_test_client(db_engine, ctx)
    stored = {}
    for name, tool, port, days in (
        ("cloudflare", "cloudflare", 443, TOOL_WINDOW.days + 5),
        ("aws-old", "aws", 22, 6),
        ("office", None, 25565, 3),
        ("aws", "aws", 51820, 1),
    ):
        stored[name] = await upload(
            db_engine, ctx, client_id, network_file(tool, port, days)
        )
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        items = await newest_items(session, client_id)
        sources = await load_sources(session, items)
    assert [item.id for item in items] == [
        stored["aws"].item_id,
        stored["office"].item_id,
    ]
    ports = [row["destination_port"] for row in sources["network-export"].rows("rule")]
    assert ports == [51820, 25565]
    assert sources["network-export"].captured_at == STORE_NOW - timedelta(days=1)
