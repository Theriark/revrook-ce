"""The evidence directory: content-addressed files, one folder per client."""

import hashlib
from pathlib import Path

import pytest

from app.evidence.errors import EvidenceStorageError
from app.evidence.files import FileStore, sha256_hex, storage_key

DATA = b"synthetic evidence file\n"
DIGEST = hashlib.sha256(DATA).hexdigest()


def test_a_file_is_stored_under_its_hash_in_the_client_folder(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    key = store.put(7, DATA)
    assert key == f"7/{DIGEST[:2]}/{DIGEST}"
    assert key == storage_key(7, DIGEST)
    assert (tmp_path / key).read_bytes() == DATA
    assert store.read(key) == DATA
    assert store.exists(key)
    assert sha256_hex(DATA) == DIGEST


def test_the_same_bytes_for_two_clients_are_two_files(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    assert store.put(1, DATA) != store.put(2, DATA)
    assert store.count_client_files(1) == store.count_client_files(2) == 1


def test_storing_the_same_file_twice_keeps_one_file(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    store.put(1, DATA)
    store.put(1, DATA)
    assert store.count_client_files(1) == 1


def test_no_temporary_file_is_left_behind(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    store.put(1, DATA)
    names = [path.name for path in (tmp_path / "1").rglob("*") if path.is_file()]
    assert names == [DIGEST]


def test_one_file_can_be_removed(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    key = store.put(1, DATA)
    assert store.remove(key) is True
    assert not store.exists(key)
    assert store.remove(key) is False


@pytest.mark.parametrize(
    "key",
    [
        "../outside",
        "1/../../etc/passwd",
        "1/ab/not-a-hash",
        f"1/xx/{DIGEST}",
        f"/1/{DIGEST[:2]}/{DIGEST}",
        f"one/{DIGEST[:2]}/{DIGEST}",
        "",
    ],
)
def test_a_key_outside_the_layout_is_refused(tmp_path: Path, key: str) -> None:
    store = FileStore(tmp_path)
    for action in (store.read, store.exists, store.remove):
        with pytest.raises(EvidenceStorageError, match="not valid"):
            action(key)


def test_reading_a_missing_file_is_a_storage_error(tmp_path: Path) -> None:
    with pytest.raises(EvidenceStorageError, match="unreadable"):
        FileStore(tmp_path).read(storage_key(1, DIGEST))


def test_a_client_folder_is_removed_with_everything_in_it(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    store.put(4, DATA)
    store.put(4, b"another file")
    store.put(5, DATA)
    assert store.remove_client(4) == 2
    assert not (tmp_path / "4").exists()
    assert store.count_client_files(5) == 1
    assert store.remove_client(4) == 0


def test_the_clients_with_a_folder_are_listed(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    assert FileStore(tmp_path / "missing").client_ids_on_disk() == []
    store.put(12, DATA)
    store.put(3, DATA)
    (tmp_path / "not-a-client").mkdir()
    (tmp_path / "stray-file").write_text("x")
    assert store.client_ids_on_disk() == [3, 12]


def test_a_root_that_cannot_hold_a_folder_is_a_storage_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("this is a file, not a folder")
    with pytest.raises(EvidenceStorageError, match="could not be stored"):
        FileStore(blocker).put(1, DATA)


def test_a_directory_in_place_of_a_file_cannot_be_removed(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    key = storage_key(1, DIGEST)
    (tmp_path / key).mkdir(parents=True)
    with pytest.raises(EvidenceStorageError, match="could not be removed"):
        store.remove(key)


def test_a_file_in_place_of_a_client_folder_cannot_be_removed(tmp_path: Path) -> None:
    (tmp_path / "9").write_text("not a folder")
    with pytest.raises(EvidenceStorageError, match="could not be removed"):
        FileStore(tmp_path).remove_client(9)
