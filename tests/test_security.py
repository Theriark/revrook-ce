"""Passwords, tokens, signed sessions and CSRF comparison (no database)."""

import re

import pytest

from app.security import (
    API_TOKEN_PREFIX,
    SessionCodec,
    SessionData,
    csrf_matches,
    dummy_password_hash,
    hash_api_token,
    hash_password,
    new_api_token,
    new_csrf_token,
    password_needs_rehash,
    verify_password,
)

SECRET = "test-only-secret-key-0123456789"


def test_passwords_are_hashed_with_argon2id_and_verify() -> None:
    stored = hash_password("a long synthetic passphrase")
    assert stored.startswith("$argon2id$")
    assert "synthetic" not in stored
    assert verify_password(stored, "a long synthetic passphrase")
    assert not verify_password(stored, "another passphrase entirely")
    assert not password_needs_rehash(stored)


def test_two_hashes_of_one_password_differ_by_salt() -> None:
    password = "same passphrase here"
    assert hash_password(password) != hash_password(password)


@pytest.mark.parametrize("stored", ["", "plain text", "$argon2id$broken"])
def test_a_damaged_stored_hash_never_verifies(stored: str) -> None:
    assert not verify_password(stored, "anything")


def test_the_dummy_hash_is_a_stable_argon2id_hash_nobody_can_match() -> None:
    assert dummy_password_hash() == dummy_password_hash()
    assert dummy_password_hash().startswith("$argon2id$")
    assert not verify_password(dummy_password_hash(), "")


def test_api_tokens_are_random_prefixed_and_stored_as_sha256() -> None:
    first, second = new_api_token(), new_api_token()
    assert first.token != second.token
    assert first.token.startswith(API_TOKEN_PREFIX)
    assert len(first.token) > 40
    assert first.token.startswith(first.prefix)
    assert first.prefix != first.token
    assert re.fullmatch(r"[0-9a-f]{64}", first.token_hash)
    assert first.token_hash == hash_api_token(first.token)
    assert first.token not in first.token_hash


def test_session_cookie_round_trips() -> None:
    codec = SessionCodec(SECRET)
    session = SessionData(csrf=new_csrf_token(), user_id=7)
    assert codec.decode(codec.encode(session)) == session
    anonymous = SessionData(csrf=new_csrf_token())
    assert codec.decode(codec.encode(anonymous)) == anonymous


def test_session_cookie_is_rejected_when_tampered_expired_or_foreign() -> None:
    codec = SessionCodec(SECRET)
    value = codec.encode(SessionData(csrf="token", user_id=1))
    assert codec.decode(value + "x") is None
    assert codec.decode(value[:-2]) is None
    assert codec.decode("") is None
    assert codec.decode("not a cookie") is None
    assert codec.decode(value, max_age=-1) is None
    assert SessionCodec("another-secret-key-0123456789").decode(value) is None


def test_session_cookie_with_a_wrong_shape_is_rejected() -> None:
    codec = SessionCodec(SECRET)
    serializer = codec._serializer
    for payload in (["list"], {"c": "", "u": None}, {"c": "t", "u": "1"}, {"u": 1}):
        assert codec.decode(serializer.dumps(payload)) is None
    assert codec.decode(serializer.dumps({"c": "t", "u": True})) is None


def test_csrf_tokens_are_random_and_compared_exactly() -> None:
    token = new_csrf_token()
    assert token != new_csrf_token()
    assert csrf_matches(token, token)
    assert not csrf_matches(token, token + "x")
    assert not csrf_matches(token, "")
