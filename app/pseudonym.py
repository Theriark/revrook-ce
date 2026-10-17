"""Per-client pseudonyms: HMAC-SHA-256 of an identifier, cut to 16 hex characters.

The key is the random 32-byte key of one client (decision I6). The same person
gets the same pseudonym within a client, so joins between sources work; another
client's key gives a different value; and once the client is deleted its key is
gone, so its pseudonyms cannot be recomputed from an identifier any more.
A pseudonym is still personal data under GDPR (see docs/evidence.md).
"""

import hashlib
import hmac
import unicodedata

PSEUDONYM_HEX_LENGTH = 16
PSEUDONYM_KEY_LENGTH = 32


def normalise_identifier(identifier: str) -> str:
    """Case, width and surrounding blanks never make a different person."""
    return unicodedata.normalize("NFKC", identifier).strip().casefold()


def pseudonymise(key: bytes, identifier: str) -> str:
    """The pseudonym of one identifier under one client key."""
    if len(key) != PSEUDONYM_KEY_LENGTH:
        raise ValueError(f"the pseudonym key must be {PSEUDONYM_KEY_LENGTH} bytes")
    normalised = normalise_identifier(identifier)
    if not normalised:
        raise ValueError("an empty identifier cannot be pseudonymised")
    digest = hmac.new(key, normalised.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:PSEUDONYM_HEX_LENGTH]


class Pseudonymiser:
    """Pseudonyms under one client key. The key never appears in repr or logs."""

    __slots__ = ("_key",)

    def __init__(self, key: bytes) -> None:
        if len(key) != PSEUDONYM_KEY_LENGTH:
            raise ValueError(f"the pseudonym key must be {PSEUDONYM_KEY_LENGTH} bytes")
        self._key = key

    def __call__(self, identifier: str) -> str:
        return pseudonymise(self._key, identifier)

    def __repr__(self) -> str:
        return "Pseudonymiser()"
