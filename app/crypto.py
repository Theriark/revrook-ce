"""Encryption of stored secrets with Fernet, using FERNET_KEY from the environment."""

import secrets

from cryptography.fernet import Fernet, InvalidToken

PSEUDONYM_KEY_BYTES = 32


class DecryptionError(Exception):
    """A stored value cannot be decrypted (wrong key or damaged data).

    The message never contains the value.
    """


class FieldCipher:
    """Encrypts and decrypts single values; tokens are URL-safe ASCII text."""

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode("ascii"))

    def encrypt(self, plaintext: bytes) -> str:
        return self._fernet.encrypt(plaintext).decode("ascii")

    def decrypt(self, token: str) -> bytes:
        try:
            return self._fernet.decrypt(token.encode("ascii"))
        except (InvalidToken, UnicodeEncodeError):
            raise DecryptionError("stored value cannot be decrypted") from None

    def encrypt_text(self, plaintext: str) -> str:
        return self.encrypt(plaintext.encode("utf-8"))

    def decrypt_text(self, token: str) -> str:
        return self.decrypt(token).decode("utf-8")


def new_pseudonym_key() -> bytes:
    """A fresh random per-client key for the HMAC pseudonyms of phase 2."""
    return secrets.token_bytes(PSEUDONYM_KEY_BYTES)
