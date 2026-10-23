"""Fetch and verify the pinned three.js build for the Evidence Explorer preview.

``app/static/vendor/three/PINNED.json`` records the npm tarball (integrity sha512 and
shasum) and the SHA-256 and size of the three files taken from it. The two large
JavaScript files are not committed: CI and the Docker build run this script, which
downloads exactly that tarball, checks it against the recorded values, checks every
file against its recorded SHA-256 and size, and only then writes the two files next to
PINNED.json. The licence file stays committed; the tarball copy must equal it.

Nothing is written when any check fails, and the script exits with status 1. The
browser never loads three.js from a CDN: the files are served from the application.

    python tools/fetch_three.py            # fetch what is missing, then verify
    python tools/fetch_three.py --check    # verify only, never touch the network
    python tools/fetch_three.py --dest DIR # DIR holds PINNED.json (and LICENSE)
"""

import argparse
import base64
import hashlib
import io
import json
import os
import sys
import tarfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_DEST = Path(__file__).resolve().parent.parent / "app/static/vendor/three"
REGISTRY_PREFIX = "https://registry.npmjs.org/"
# Files taken from the tarball, by name in this directory, and their tarball path.
MEMBERS = {
    "three.module.js": "package/build/three.module.js",
    "three.core.js": "package/build/three.core.js",
    "LICENSE": "package/LICENSE",
}
# The tarball is about 1.4 MB; a larger answer is not the pinned package.
MAX_TARBALL_BYTES = 16 * 1024 * 1024


class PinError(Exception):
    """A pinned value does not match what was downloaded or found on disk."""


def download(url: str) -> bytes:
    """Read the tarball over HTTPS, bounded in size."""
    request = urllib.request.Request(url, headers={"User-Agent": "revrook-ce-build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data: bytes = response.read(MAX_TARBALL_BYTES + 1)
    if len(data) > MAX_TARBALL_BYTES:
        raise PinError("the tarball is larger than the allowed size")
    return data


def load_pins(dest: Path) -> dict[str, Any]:
    pins: dict[str, Any] = json.loads((dest / "PINNED.json").read_text("utf-8"))
    if pins.get("name") != "three" or set(pins.get("files", {})) != set(MEMBERS):
        raise PinError("PINNED.json does not describe the expected three.js files")
    if not str(pins.get("tarball", "")).startswith(REGISTRY_PREFIX):
        raise PinError("the pinned tarball is not on the npm registry")
    return pins


def check_file(name: str, data: bytes, record: dict[str, Any]) -> None:
    if len(data) != record["bytes"]:
        raise PinError(f"{name}: {len(data)} bytes, pinned {record['bytes']}")
    digest = hashlib.sha256(data).hexdigest()
    if digest != record["sha256"]:
        raise PinError(f"{name}: sha256 {digest}, pinned {record['sha256']}")


def check_tarball(data: bytes, pins: dict[str, Any]) -> None:
    shasum = hashlib.sha1(data, usedforsecurity=False).hexdigest()
    if shasum != pins["tarballShasum"]:
        raise PinError(f"tarball shasum {shasum}, pinned {pins['tarballShasum']}")
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
    if integrity != pins["tarballIntegrity"]:
        raise PinError("tarball integrity (sha512) does not match PINNED.json")


def read_members(tarball: bytes) -> dict[str, bytes]:
    """The pinned members, read in memory; nothing is extracted to disk."""
    found: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        for name, member in MEMBERS.items():
            try:
                info = archive.getmember(member)
            except KeyError:
                raise PinError(f"{member} is not in the tarball") from None
            handle = archive.extractfile(info) if info.isfile() else None
            if handle is None:
                raise PinError(f"{member} is not a regular file in the tarball")
            found[name] = handle.read()
    return found


def file_ok(path: Path, record: dict[str, Any]) -> bool:
    try:
        check_file(path.name, path.read_bytes(), record)
    except (OSError, PinError):
        return False
    return True


def verify_dir(dest: Path, pins: dict[str, Any]) -> list[str]:
    """Names of pinned files that are missing or wrong in dest (empty: all good)."""
    return [n for n, r in pins["files"].items() if not file_ok(dest / n, r)]


def fetch(
    dest: Path = DEFAULT_DEST,
    read_url: Callable[[str], bytes] = download,
) -> list[str]:
    """Make dest hold the verified build; return the names that were written."""
    pins = load_pins(dest)
    if not verify_dir(dest, pins):
        return []
    tarball = read_url(pins["tarball"])
    check_tarball(tarball, pins)
    members = read_members(tarball)
    for name, record in pins["files"].items():
        check_file(name, members[name], record)
    committed = dest / "LICENSE"
    if committed.exists() and committed.read_bytes() != members["LICENSE"]:
        raise PinError("the committed LICENSE differs from the one in the tarball")
    written: list[str] = []
    for name in MEMBERS:
        path = dest / name
        if file_ok(path, pins["files"][name]):
            continue
        partial = path.with_name(f".{name}.partial")
        partial.write_bytes(members[name])
        os.replace(partial, path)
        written.append(name)
    left = verify_dir(dest, pins)
    if left:
        raise PinError(f"after writing, {', '.join(left)} still fail verification")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument(
        "--check", action="store_true", help="verify the files on disk, no network"
    )
    args = parser.parse_args(argv)
    try:
        if args.check:
            bad = verify_dir(args.dest, load_pins(args.dest))
            if bad:
                raise PinError(f"missing or not as pinned: {', '.join(bad)}")
            print("three.js 0.186.1: every pinned file present and verified")
        else:
            written = fetch(args.dest)
            print(f"three.js 0.186.1 verified; written: {', '.join(written) or 'none'}")
    except (PinError, OSError, ValueError, tarfile.TarError) as error:
        print(f"fetch_three: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
