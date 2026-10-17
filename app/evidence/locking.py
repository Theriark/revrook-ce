"""The per-client lock that keeps evidence writes, chain records and deletion apart."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.errors import ClientNotFoundError
from app.models import Client


async def lock_client(session: AsyncSession, client_id: int) -> Client:
    """Take the row lock of a client. It is held until the transaction ends.

    Everything that appends to a client's hash chain, adds evidence or deletes
    the client starts here, so those actions happen one at a time per client.
    """
    result = await session.execute(
        select(Client).where(Client.id == client_id).with_for_update()
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise ClientNotFoundError("There is no client with this id.")
    return client
