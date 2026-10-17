"""Per-client pseudonyms: stable inside a client, different between clients."""

import random
import re
import secrets

import pytest

from app.pseudonym import Pseudonymiser, normalise_identifier, pseudonymise

KEY_ONE = secrets.token_bytes(32)
KEY_TWO = secrets.token_bytes(32)
UPN = "alice.synthetic@example.test"


def test_a_pseudonym_is_16_lowercase_hex_characters() -> None:
    assert re.fullmatch(r"[0-9a-f]{16}", pseudonymise(KEY_ONE, UPN))


def test_the_same_person_gets_the_same_pseudonym_within_a_client() -> None:
    first = pseudonymise(KEY_ONE, UPN)
    assert pseudonymise(KEY_ONE, UPN) == first
    assert pseudonymise(KEY_ONE, "  ALICE.Synthetic@Example.TEST ") == first


def test_another_client_gets_a_different_pseudonym() -> None:
    assert pseudonymise(KEY_ONE, UPN) != pseudonymise(KEY_TWO, UPN)


def test_different_people_get_different_pseudonyms() -> None:
    assert pseudonymise(KEY_ONE, UPN) != pseudonymise(KEY_ONE, "bob@example.test")


def test_the_pseudonym_does_not_contain_the_identifier() -> None:
    pseudonym = pseudonymise(KEY_ONE, UPN)
    assert "alice" not in pseudonym
    assert "example" not in pseudonym


def test_identifiers_are_normalised_before_hashing() -> None:
    assert normalise_identifier("  Ａlice@Example.Test ") == "alice@example.test"


@pytest.mark.parametrize("key", [b"", b"short", bytes(31), bytes(33)])
def test_the_key_must_be_32_bytes(key: bytes) -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        pseudonymise(key, UPN)
    with pytest.raises(ValueError, match="32 bytes"):
        Pseudonymiser(key)


@pytest.mark.parametrize("identifier", ["", "   ", "\t\n"])
def test_an_empty_identifier_is_refused(identifier: str) -> None:
    with pytest.raises(ValueError, match="empty identifier"):
        pseudonymise(KEY_ONE, identifier)


def test_the_pseudonymiser_matches_the_function_and_hides_its_key() -> None:
    pseudonymiser = Pseudonymiser(KEY_ONE)
    assert pseudonymiser(UPN) == pseudonymise(KEY_ONE, UPN)
    assert repr(pseudonymiser) == "Pseudonymiser()"
    assert KEY_ONE.hex() not in repr(pseudonymiser)


def test_random_identifiers_always_give_stable_distinct_pseudonyms() -> None:
    generator = random.Random(2026)
    identifiers = {
        f"user{generator.randrange(10**9)}@tenant{generator.randrange(50)}.test"
        for _ in range(500)
    }
    seen: dict[str, str] = {}
    for identifier in identifiers:
        pseudonym = pseudonymise(KEY_ONE, identifier)
        assert re.fullmatch(r"[0-9a-f]{16}", pseudonym)
        assert pseudonymise(KEY_ONE, identifier) == pseudonym
        assert pseudonym not in seen, "a collision in 500 identifiers is not expected"
        seen[pseudonym] = identifier
