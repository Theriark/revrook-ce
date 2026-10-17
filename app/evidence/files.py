"""The evidence directory: files named by their SHA-256, one folder per client.

Layout: <EVIDENCE_DIR>/<client id>/<first two hex characters>/<sha256>.
A key is that path relative to EVIDENCE_DIR. Keeping a client's files in their
own folder makes deleting a client one recursive removal, and never lets two
clients share (or learn about) a file.
"""

import contextlib
import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path

from app.evidence.errors import EvidenceStorageError

KEY_PATTERN = re.compile(r"^(\d{1,19})/([0-9a-f]{2})/([0-9a-f]{64})$")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def storage_key(client_id: int, sha256: str) -> str:
    return f"{client_id}/{sha256[:2]}/{sha256}"


class FileStore:
    """Writes, reads and removes evidence files below one root directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        """The path of a key. A key that is not exactly our layout is refused."""
        if KEY_PATTERN.match(key) is None:
            raise EvidenceStorageError("the storage key is not valid")
        return self.root / key

    def client_dir(self, client_id: int) -> Path:
        return self.root / str(int(client_id))

    def put(self, client_id: int, data: bytes) -> str:
        """Store the bytes under their hash (atomic) and return the key."""
        key = storage_key(client_id, sha256_hex(data))
        path = self._path(key)
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as error:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise EvidenceStorageError(
                "the evidence file could not be stored"
            ) from error
        return key

    def read(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except OSError as error:
            raise EvidenceStorageError("the evidence file is unreadable") from error

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def remove(self, key: str) -> bool:
        """Remove one file. False when it was already gone."""
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise EvidenceStorageError(
                "the evidence file could not be removed"
            ) from error
        return True

    def count_client_files(self, client_id: int) -> int:
        folder = self.client_dir(client_id)
        if not folder.is_dir():
            return 0
        return sum(1 for entry in folder.rglob("*") if entry.is_file())

    def remove_client(self, client_id: int) -> int:
        """Remove every file of one client. Returns how many files were removed."""
        folder = self.client_dir(client_id)
        removed = self.count_client_files(client_id)
        try:
            shutil.rmtree(folder, ignore_errors=False)
        except FileNotFoundError:
            return 0
        except OSError as error:
            raise EvidenceStorageError(
                "the files of the client could not be removed"
            ) from error
        return removed

    def client_ids_on_disk(self) -> list[int]:
        """The client ids that have a folder (used to find leftovers)."""
        if not self.root.is_dir():
            return []
        return sorted(
            int(entry.name)
            for entry in self.root.iterdir()
            if entry.is_dir() and entry.name.isdecimal()
        )
