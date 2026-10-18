"""Carry-overs of phase 4, fixed before any control relies on them (phase 5).

* The directory roles counts treat two spellings of one user as one user (NFKC,
  like every other distinct count), not just two cases of the same letters.
* A firewall rule whose source is the whole internet is `any` in every spelling
  (0.0.0.0/0, ::/0 and the rest), a source that is a known address, block or range
  is `restricted`, and a source revrook cannot read is unknown. It is never
  `restricted` by default, so a control that counts rules open to the internet
  cannot pass on a rule it did not understand.
"""

import pytest

from app.importers.base import ParseResult
from app.importers.generic import source_scope
from app.importers.registry import build_default_registry
from tools.make_fixtures import to_csv

REGISTRY = build_default_registry()
RULE_HEADER = ["record_type", "rule_enabled", "direction", "action", "source", "port"]


def parse(code: str, data: bytes) -> ParseResult:
    importer = REGISTRY.get(code)
    assert importer is not None
    return importer.parse(data, 1000)


def test_directory_roles_count_one_user_once_under_nfkc() -> None:
    header = ["User principal name", "Role"]
    rows = [
        ["alice@x.test", "Global Administrator"],
        ["ＡＬＩＣＥ@x.test", "Global Administrator"],
        ["Alice@X.test", "Exchange Administrator"],
        [" bob@x.test ", "Exchange Administrator"],
        ["bob@x.test", "Global Administrator"],
    ]
    summary = dict(parse("directory-roles", to_csv(header, rows)).facts[-1].value)
    assert summary["assignments"] == 5
    assert summary["users"] == 2
    assert summary["global_admins"] == 2
    assert summary["roles"] == 2


@pytest.mark.parametrize(
    "text",
    [
        "0.0.0.0/0",
        "::/0",
        " 0.0.0.0/0 ",
        "0.0.0.0/0.0.0.0",
        "0::/0",
        "::0/0",
        "0.0.0.0/0, 10.0.0.0/8",
        "10.0.0.0/8 ; ::/0",
        "ANY",
        "Internet",
        "0.0.0.0-255.255.255.255",
    ],
)
def test_a_source_that_reaches_the_whole_internet_is_any(text: str) -> None:
    assert source_scope(text) == "any"


@pytest.mark.parametrize(
    "text",
    [
        "203.0.113.0/24",
        "10.0.0.1",
        "192.0.2.1-192.0.2.9",
        "2001:db8::/32",
        "10.0.0.0/8, 192.168.0.0/16",
    ],
)
def test_a_known_address_block_or_range_is_restricted(text: str) -> None:
    assert source_scope(text) == "restricted"


@pytest.mark.parametrize(
    "text",
    [
        "LAN",
        "10.0.0.0/8, LAN",
        "office vpn",
        "not-an-address",
        "1.2.3",
        "192.0.2.9-192.0.2.1",
        "192.0.2.1-2001:db8::1",
        "10.0.0.0/33",
        "",
        "   ",
    ],
)
def test_a_source_revrook_cannot_read_is_unknown_never_restricted(text: str) -> None:
    assert source_scope(text) is None


@pytest.mark.parametrize(
    "text",
    [
        # NB3 (part 1 review): an unspecified address is the whole internet.
        "0.0.0.0",
        "::",
        "0::0",
        "::0",
        " 0.0.0.0 ",
        # NB3: words that are each restricted and together cover every address.
        "0.0.0.0/1, 128.0.0.0/1",
        "0.0.0.0/1 128.0.0.0/1",
        "128.0.0.0/1; 0.0.0.0/1",
        "0.0.0.0/2, 64.0.0.0/2, 128.0.0.0/1",
        "0.0.0.0-127.255.255.255, 128.0.0.0/1",
        "0.0.0.0/1, 100.0.0.0/8, 128.0.0.0/1",
        "::/1, 8000::/1",
        "0.0.0.0/1, 128.0.0.0/1, LAN",
        # L2: spaces around the dash of a range.
        "0.0.0.0 - 255.255.255.255",
        "0.0.0.0 -255.255.255.255",
        "0.0.0.0- 255.255.255.255",
        ":: - ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    ],
)
def test_the_whole_internet_in_its_other_spellings_is_any(text: str) -> None:
    assert source_scope(text) == "any"


@pytest.mark.parametrize(
    "text",
    [
        # A gap, another version, a range that starts after zero: not the internet.
        "0.0.0.0/1, 128.0.0.0/2",
        "0.0.0.0/1, ::/1",
        "1.0.0.0-255.255.255.255",
        "0.0.0.0-255.255.255.254",
        "0.0.0.1",
        "127.0.0.1",
        "10.0.0.1 - 10.0.0.9",
    ],
)
def test_a_source_that_leaves_addresses_out_is_still_restricted(text: str) -> None:
    assert source_scope(text) == "restricted"


def test_a_range_with_spaces_around_the_dash_in_a_wrong_order_is_unknown() -> None:
    assert source_scope("255.255.255.255 - 0.0.0.0") is None


def test_a_rule_open_to_the_whole_internet_in_another_spelling_counts_as_any() -> None:
    sources = ["0.0.0.0", "0.0.0.0/1, 128.0.0.0/1", "0.0.0.0 - 255.255.255.255"]
    rows = [["rule", "true", "inbound", "allow", item, "3389"] for item in sources]
    result = parse("network-export", to_csv(RULE_HEADER, rows))
    rules = [fact for fact in result.facts if fact.key == "network.rule"]
    assert [fact.value["source"] for fact in rules] == ["any", "any", "any"]
    assert dict(result.facts[-1].value)["rules_any_source"] == 3


def test_network_rules_carry_any_restricted_or_unknown_to_the_facts() -> None:
    sources = ["0.0.0.0/0", "::/0", "203.0.113.0/24", "LAN", "10.0.0.0/8, 0.0.0.0/0"]
    rows = [["rule", "true", "inbound", "allow", item, "3389"] for item in sources]
    result = parse("network-export", to_csv(RULE_HEADER, rows))
    rules = [fact for fact in result.facts if fact.key == "network.rule"]
    assert [fact.value["source"] for fact in rules] == [
        "any",
        "any",
        "restricted",
        None,
        "any",
    ]
    summary = dict(result.facts[-1].value)
    assert summary["rules"] == 5
    assert summary["rules_any_source"] == 3
