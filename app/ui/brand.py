"""The approved brand files the layout may link to.

The files in app/static/brand are exact copies of the approved Nextcloud assets
(/Theriark/Revrook/Assets); they are never redrawn or regenerated here. The
layout links a file only when it is present, so a missing copy shows the text
wordmark instead of a broken image.
"""

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
BRAND_DIR = STATIC_DIR / "brand"

# Every file the brand guide places in app/static/brand.
BRAND_FILES = (
    "logo-horizontal-2400x800.png",
    "logo-horizontal-1200x400.png",
    "favicon-32x32.png",
    "favicon-180x180.png",
    "favicon-512x512.png",
    "logo-mark-512x512.png",
    "logo-mark-1024x1024.png",
    "social-og-1200x630.png",
    "wordmark.svg",
    "wordmark-dark.svg",
)


def available_brand_files(brand_dir: Path = BRAND_DIR) -> frozenset[str]:
    """The names of BRAND_FILES that exist in brand_dir."""
    return frozenset(name for name in BRAND_FILES if (brand_dir / name).is_file())
