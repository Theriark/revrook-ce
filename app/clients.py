"""Clients and their per-client pseudonym key (decision I6)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit_event
from app.crypto import FieldCipher, new_pseudonym_key
from app.models import Client
from app.textcheck import control_character, describe

MAX_CLIENT_NAME_LENGTH = 200


async def create_client(
    session: AsyncSession,
    cipher: FieldCipher,
    name: str,
    actor_user_id: int | None = None,
) -> Client:
    """Create a client with its own random 32-byte key, stored Fernet-encrypted.

    The key is never logged and never returned to a page. Deleting the client
    deletes the key, so its pseudonyms cannot be reversed afterwards.
    """
    cleaned = name.strip()
    if not cleaned or len(cleaned) > MAX_CLIENT_NAME_LENGTH:
        raise ValueError(
            f"client name must be 1 to {MAX_CLIENT_NAME_LENGTH} characters"
        )
    bad = control_character(cleaned)
    if bad is not None:
        raise ValueError(
            f"client name must not contain a control character ({describe(bad)})"
        )
    client = Client(
        name=cleaned,
        pseudonym_key_encrypted=cipher.encrypt(new_pseudonym_key()),
    )
    session.add(client)
    await session.flush()
    add_audit_event(
        session,
        "client.created",
        actor_user_id=actor_user_id,
        target_type="client",
        target_id=client.id,
    )
    return client


def pseudonym_key(cipher: FieldCipher, client: Client) -> bytes:
    """The decrypted HMAC key of the client, for the pseudonym helper of phase 2."""
    return cipher.decrypt(client.pseudonym_key_encrypted)
