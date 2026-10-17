"""Errors of the evidence store. Messages are readable by the person who caused them.

A message never repeats content from an uploaded file and never holds a key or
a personal identifier.
"""


class EvidenceError(Exception):
    """Base class of every evidence store error."""


class ClientNotFoundError(EvidenceError):
    """The client does not exist (or was deleted)."""


class ItemNotFoundError(EvidenceError):
    """The evidence item does not exist for this client."""


class DuplicateEvidenceError(EvidenceError):
    """The same file was already uploaded for this client."""

    def __init__(self, message: str, existing_item_id: int) -> None:
        super().__init__(message)
        self.existing_item_id = existing_item_id


class EvidenceTooLargeError(EvidenceError):
    """The file is bigger than the configured limit."""


class EvidenceRejectedError(EvidenceError):
    """The upload is not acceptable (missing field, bad value, unreadable file)."""


class PersonalIdentifierError(EvidenceRejectedError):
    """A fact value looks like a personal identifier; nothing was stored."""


class EvidenceStorageError(EvidenceError):
    """The evidence directory could not be written or cleaned."""
