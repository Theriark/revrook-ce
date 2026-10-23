"""The build step that fetches the pinned three.js files (tools/fetch_three.py).

The step must fail the build, and write nothing, when the tarball or any file differs
from PINNED.json. These tests use a small synthetic tarball: they never reach the
network. The real files are checked by tests/test_evidence_explorer.py.
"""

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from tools import fetch_three

REPO_PINNED = (
    Path(__file__).resolve().parent.parent / "app/static/vendor/three/PINNED.json"
)
URL = "https://registry.npmjs.org/three/-/three-0.0.0.tgz"
FILES = {
    "three.module.js": b"// module\nexport {};\n",
    "three.core.js": b"// core\nexport {};\n",
    "LICENSE": b"The MIT License\n",
}


def make_tarball(files: dict[str, bytes], skip: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, member in fetch_three.MEMBERS.items():
            if name == skip:
                continue
            info = tarfile.TarInfo(member)
            info.size = len(files[name])
            archive.addfile(info, io.BytesIO(files[name]))
    return buffer.getvalue()


def make_pins(tarball: bytes, files: dict[str, bytes]) -> dict[str, object]:
    sha512 = base64.b64encode(hashlib.sha512(tarball).digest()).decode()
    return {
        "name": "three",
        "version": "0.0.0",
        "tarball": URL,
        "tarballShasum": hashlib.sha1(tarball).hexdigest(),
        "tarballIntegrity": f"sha512-{sha512}",
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in files.items()
        },
    }


def make_dest(tmp_path: Path, pins: dict[str, object]) -> Path:
    dest = tmp_path / "three"
    dest.mkdir()
    (dest / "PINNED.json").write_text(json.dumps(pins), encoding="utf-8")
    (dest / "LICENSE").write_bytes(FILES["LICENSE"])
    return dest


def test_the_pinned_files_are_written_after_every_check_passes(tmp_path: Path) -> None:
    tarball = make_tarball(FILES)
    dest = make_dest(tmp_path, make_pins(tarball, FILES))
    asked: list[str] = []

    def read_url(url: str) -> bytes:
        asked.append(url)
        return tarball

    written = fetch_three.fetch(dest, read_url)
    assert written == ["three.module.js", "three.core.js"]
    assert asked == [URL]
    for name, data in FILES.items():
        assert (dest / name).read_bytes() == data
    names = sorted(path.name for path in dest.iterdir())
    assert names == sorted([*FILES, "PINNED.json"])


def test_a_second_run_with_the_files_in_place_does_not_touch_the_network(
    tmp_path: Path,
) -> None:
    tarball = make_tarball(FILES)
    dest = make_dest(tmp_path, make_pins(tarball, FILES))
    fetch_three.fetch(dest, lambda url: tarball)

    def refuse(url: str) -> bytes:
        raise AssertionError("no download expected")

    assert fetch_three.fetch(dest, refuse) == []


def test_a_wrong_file_on_disk_is_replaced_by_the_verified_one(tmp_path: Path) -> None:
    tarball = make_tarball(FILES)
    dest = make_dest(tmp_path, make_pins(tarball, FILES))
    (dest / "three.core.js").write_bytes(b"// tampered\n")
    assert fetch_three.fetch(dest, lambda url: tarball) == [
        "three.module.js",
        "three.core.js",
    ]
    assert (dest / "three.core.js").read_bytes() == FILES["three.core.js"]


def assert_nothing_written(dest: Path) -> None:
    assert sorted(path.name for path in dest.iterdir()) == ["LICENSE", "PINNED.json"]


def test_a_tarball_that_is_not_the_pinned_one_fails_and_writes_nothing(
    tmp_path: Path,
) -> None:
    tarball = make_tarball(FILES)
    dest = make_dest(tmp_path, make_pins(tarball, FILES))
    other = make_tarball({**FILES, "three.core.js": b"// other\n"})
    with pytest.raises(fetch_three.PinError, match="tarball shasum"):
        fetch_three.fetch(dest, lambda url: other)
    assert_nothing_written(dest)


def test_a_wrong_tarball_integrity_alone_fails(tmp_path: Path) -> None:
    tarball = make_tarball(FILES)
    pins = make_pins(tarball, FILES)
    pins["tarballIntegrity"] = "sha512-" + base64.b64encode(b"x" * 64).decode()
    dest = make_dest(tmp_path, pins)
    with pytest.raises(fetch_three.PinError, match="integrity"):
        fetch_three.fetch(dest, lambda url: tarball)
    assert_nothing_written(dest)


def test_a_file_whose_sha256_differs_from_the_pin_fails(tmp_path: Path) -> None:
    tarball = make_tarball(FILES)
    pins = make_pins(tarball, FILES)
    files = pins["files"]
    assert isinstance(files, dict)
    files["three.module.js"]["sha256"] = "0" * 64
    dest = make_dest(tmp_path, pins)
    with pytest.raises(fetch_three.PinError, match=r"three\.module\.js: sha256"):
        fetch_three.fetch(dest, lambda url: tarball)
    assert_nothing_written(dest)


def test_a_file_whose_size_differs_from_the_pin_fails(tmp_path: Path) -> None:
    tarball = make_tarball(FILES)
    pins = make_pins(tarball, FILES)
    files = pins["files"]
    assert isinstance(files, dict)
    files["three.core.js"]["bytes"] += 1
    dest = make_dest(tmp_path, pins)
    with pytest.raises(fetch_three.PinError, match=r"three\.core\.js: .* bytes"):
        fetch_three.fetch(dest, lambda url: tarball)
    assert_nothing_written(dest)


def test_a_tarball_without_a_pinned_member_fails(tmp_path: Path) -> None:
    tarball = make_tarball(FILES, skip="three.core.js")
    dest = make_dest(tmp_path, make_pins(tarball, FILES))
    with pytest.raises(fetch_three.PinError, match="is not in the tarball"):
        fetch_three.fetch(dest, lambda url: tarball)
    assert_nothing_written(dest)


def test_a_committed_licence_that_differs_from_the_tarball_fails(
    tmp_path: Path,
) -> None:
    tarball = make_tarball(FILES)
    dest = make_dest(tmp_path, make_pins(tarball, FILES))
    (dest / "LICENSE").write_bytes(b"changed licence\n")
    with pytest.raises(fetch_three.PinError):
        fetch_three.fetch(dest, lambda url: tarball)
    assert (dest / "LICENSE").read_bytes() == b"changed licence\n"
    assert not (dest / "three.module.js").exists()


def test_only_the_npm_registry_is_accepted_as_the_source(tmp_path: Path) -> None:
    tarball = make_tarball(FILES)
    pins = make_pins(tarball, FILES)
    pins["tarball"] = "https://cdn.example.com/three.tgz"
    dest = make_dest(tmp_path, pins)
    with pytest.raises(fetch_three.PinError, match="npm registry"):
        fetch_three.fetch(dest, lambda url: tarball)


def test_the_command_exits_non_zero_when_a_check_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tarball = make_tarball(FILES)
    dest = make_dest(tmp_path, make_pins(tarball, FILES))
    assert fetch_three.main(["--dest", str(dest), "--check"]) == 1
    assert "three.module.js" in capsys.readouterr().err
    for name in ("three.module.js", "three.core.js"):
        (dest / name).write_bytes(FILES[name])
    assert fetch_three.main(["--dest", str(dest), "--check"]) == 0


def test_the_repository_pins_describe_exactly_the_files_the_step_fetches() -> None:
    pins = fetch_three.load_pins(REPO_PINNED.parent)
    assert pins["version"] == "0.186.1"
    assert pins["tarball"] == "https://registry.npmjs.org/three/-/three-0.186.1.tgz"
    assert set(pins["files"]) == set(fetch_three.MEMBERS)
    licence = (REPO_PINNED.parent / "LICENSE").read_bytes()
    assert hashlib.sha256(licence).hexdigest() == pins["files"]["LICENSE"]["sha256"]
