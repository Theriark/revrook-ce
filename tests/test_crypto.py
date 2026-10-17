"""The Fernet helper and the per-client pseudonym key generator."""

import base64

import pytest
from cryptography.fernet import Fernet

from app.crypto import DecryptionError, FieldCipher, new_pseudonym_key

KEY = Fernet.generate_key().decode()


def test_encryption_round_trips_bytes_and_text() -> None:
    cipher = FieldCipher(KEY)
    data = b"\x00\x01 synthetic"
    text = "synthetic text é"
    assert cipher.decrypt(cipher.encrypt(data)) == data
    assert cipher.decrypt_text(cipher.encrypt_text(text)) == text


def test_ciphertext_hides_the_value_and_differs_every_time() -> None:
    cipher = FieldCipher(KEY)
    first, second = cipher.encrypt(b"same value"), cipher.encrypt(b"same value")
    assert first != second
    assert "same value" not in first
    assert base64.urlsafe_b64decode(first.encode()) != b"same value"


def test_another_key_cannot_decrypt() -> None:
    token = FieldCipher(KEY).encrypt(b"secret")
    other = FieldCipher(Fernet.generate_key().decode())
    with pytest.raises(DecryptionError):
        other.decrypt(token)


@pytest.mark.parametrize("token", ["", "not a token", "gAAAA", "é"])
def test_damaged_or_foreign_tokens_raise_a_clean_error(token: str) -> None:
    with pytest.raises(DecryptionError) as error:
        FieldCipher(KEY).decrypt(token)
    assert str(error.value) == "stored value cannot be decrypted"


def test_pseudonym_keys_are_32_random_bytes() -> None:
    first, second = new_pseudonym_key(), new_pseudonym_key()
    assert len(first) == len(second) == 32
    assert first != second
