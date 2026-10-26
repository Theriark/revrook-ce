"""The approved brand files the layout may link to, and the version of the assets.

The files in app/static/brand are exact copies of the approved Nextcloud assets
(/Theriark/Revrook/Assets); they are never redrawn or regenerated here. The
layout links a file only when it is present, so a missing copy shows the text
wordmark instead of a broken image.
"""

import hashlib
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
BRAND_DIR = STATIC_DIR / "brand"

# Every file of the approved Nextcloud asset set copied into app/static/brand.
BRAND_FILES = (
    "logo-horizontal-2400x800.png",
    "logo-horizontal-1200x400.png",
    "logo-horizontal-dark-2400x800.png",
    "logo-horizontal-dark-1200x400.png",
    "logo-stacked-1000x1000.png",
    "logo-stacked-dark-1000x1000.png",
    "favicon-32x32.png",
    "favicon-180x180.png",
    "favicon-512x512.png",
    "logo-mark-512x512.png",
    "logo-mark-1024x1024.png",
    "app-icon-1024x1024.png",
    "social-og-1200x630.png",
    "social-avatar-400x400.png",
    "wordmark.svg",
    "wordmark-dark.svg",
    "wordmark-1200x300.png",
    "wordmark-dark-1200x300.png",
)
# The stylesheets and scripts base.html links, under app/static. Their addresses
# carry asset_version() as the `v` query, so a changed file has a new address.
ASSET_FILES = (
    "vendor/pico/pico.min.css",
    "css/revrook.css",
    "css/revrook-retest.css",
    "css/charts.css",
    "css/scenes.css",
    "css/revamp.css",
    "vendor/htmx/htmx.min.js",
    "js/revrook.js",
    "js/charts.js",
    "js/scenes.js",
)
# The stylesheet and the script of the filter chips of the clients list. They are
# not in the shell: clients.html links them itself, with their own digest
# (asset_version of these files) as the `v` query, for the same reason.
FILTER_CHIP_FILES = ("css/filter-chips.css", "js/filter-chips.js")
# The stylesheet of the score drivers of Home (home.html links it, THE-1189).
DRIVER_FILES = ("css/drivers.css",)
# The stylesheet and the script of the bulk actions of the clients list
# (clients.html links them, THE-1189).
BULK_ACTION_FILES = ("css/bulk-actions.css", "js/bulk-actions.js")


def available_brand_files(brand_dir: Path = BRAND_DIR) -> frozenset[str]:
    """The names of BRAND_FILES that exist in brand_dir."""
    return frozenset(name for name in BRAND_FILES if (brand_dir / name).is_file())


def asset_version(
    static_dir: Path = STATIC_DIR, files: tuple[str, ...] = ASSET_FILES
) -> str:
    """A 12-character digest of `files` (the shell's ASSET_FILES unless others are
    named), the `v` query of their links.

    A browser, and any cache in front of the installation, keeps a static file for
    hours. With the digest in the address a new version of a stylesheet or script
    has a new address, so no page is shown with the old one after an upgrade. A
    missing file counts as empty, so the layout still renders without it.
    """
    digest = hashlib.sha256()
    for name in files:
        path = static_dir / name
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes() if path.is_file() else b"")
    return digest.hexdigest()[:12]
