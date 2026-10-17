"""Clients and their encrypted per-client pseudonym key (decision I6)."""

import base64

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.clients import create_client, pseudonym_key
from app.crypto import DecryptionError, FieldCipher
from app.models import Client
from helpers import audit_baseline, audit_since

KEY = Fernet.generate_key().decode()


async def make_client_row(
    engine: AsyncEngine, cipher: FieldCipher, name: str = "Synthetic Client Ltd"
) -> Client:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        return await create_client(session, cipher, name)


async def test_every_client_gets_its_own_random_32_byte_key_stored_encrypted(
    db_engine: AsyncEngine,
) -> None:
    cipher = FieldCipher(KEY)
    baseline = await audit_baseline(db_engine)
    first = await make_client_row(db_engine, cipher, "  Client One  ")
    second = await make_client_row(db_engine, cipher, "Client Two")
    assert first.name == "Client One"
    first_key, second_key = pseudonym_key(cipher, first), pseudonym_key(cipher, second)
    assert len(first_key) == len(second_key) == 32
    assert first_key != second_key

    async with db_engine.connect() as connection:
        rows = (
            await connection.execute(
                text("SELECT pseudonym_key_encrypted FROM client ORDER BY id")
            )
        ).scalars()
        stored = list(rows)
    assert len(stored) == 2
    for value, key in zip(stored, (first_key, second_key), strict=True):
        assert key not in value.encode()
        assert base64.b64encode(key).decode() not in value
        assert key.hex() not in value
        assert cipher.decrypt(value) == key

    events = await audit_since(db_engine, baseline)
    assert [event.action for event in events] == ["client.created"] * 2
    assert all(
        first_key.hex() not in str(event.detail) and event.target_type == "client"
        for event in events
    )


async def test_the_key_cannot_be_read_with_another_encryption_key(
    db_engine: AsyncEngine,
) -> None:
    client = await make_client_row(db_engine, FieldCipher(KEY))
    other = FieldCipher(Fernet.generate_key().decode())
    with pytest.raises(DecryptionError):
        pseudonym_key(other, client)


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
async def test_a_client_name_must_be_1_to_200_characters(
    db_engine: AsyncEngine, name: str
) -> None:
    with pytest.raises(ValueError, match="1 to 200 characters"):
        await make_client_row(db_engine, FieldCipher(KEY), name)


async def test_deleting_a_client_deletes_its_key_and_leaves_the_audit_entry(
    db_engine: AsyncEngine,
) -> None:
    baseline = await audit_baseline(db_engine)
    client = await make_client_row(db_engine, FieldCipher(KEY))
    async with db_engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM client WHERE id = :id"), {"id": client.id}
        )
        remaining = await connection.execute(text("SELECT count(*) FROM client"))
        assert remaining.scalar_one() == 0
    events = await audit_since(db_engine, baseline)
    assert [event.action for event in events] == ["client.created"]
