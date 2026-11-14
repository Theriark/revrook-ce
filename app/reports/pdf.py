"""A report as a PDF file: the HTML file of the report, printed by a headless Chromium.

The report is designed for print (print.css: A4, the cover on its own sheet, sheet
numbers, colours kept), so the PDF is what "Save as PDF" of a browser gives, made on
the server. The image carries `chromium-headless-shell` for it (Dockerfile); an
installation without a browser has no PDF, and the page says how to print one.

The browser gets one file and nothing else: a policy in the file forbids scripts and
every address but the `data:` font and logo the report carries, no host name is
resolved, and the profile lives in a directory that is removed with the file.
`pdf_of` blocks for a few seconds, so a caller on the event loop runs it in a thread.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The names a headless Chromium goes by: the Debian package of the image first.
BROWSERS = ("chromium-headless-shell", "chromium", "chromium-browser", "google-chrome")
TIMEOUT_SECONDS = 60
# What the preview of a report allows (app/ui/reports.py), as the file's own policy.
POLICY = (
    b'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
    b"style-src 'unsafe-inline'; font-src data:; img-src data:\">"
)


class PdfError(RuntimeError):
    """The browser did not make the file."""


def find_browser() -> str | None:
    """The path of a headless Chromium on this machine, or None."""
    for name in BROWSERS:
        found = shutil.which(name)
        if found:
            return found
    return None


def pdf_of(html: bytes, browser: str) -> bytes:
    """The PDF of a rendered report. Blocking: call it in a thread."""
    if html.count(b"<head>") != 1:
        raise PdfError("the report has no single head to carry the policy")
    with tempfile.TemporaryDirectory(
        prefix="revrook-pdf-", ignore_cleanup_errors=True
    ) as folder:
        source = Path(folder, "report.html")
        target = Path(folder, "report.pdf")
        source.write_bytes(html.replace(b"<head>", b"<head>" + POLICY))
        command = [
            browser,
            "--headless",
            # A container gives the browser no user namespace to sandbox itself in.
            # What it reads is the report revrook wrote, under the policy above.
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--host-resolver-rules=MAP * ~NOTFOUND",
            f"--user-data-dir={Path(folder, 'profile')}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={target}",
            source.as_uri(),
        ]
        try:
            done = subprocess.run(  # a fixed command, no shell
                command,
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
                # What the browser keeps beside its profile goes to the same folder:
                # the root of a container is read-only and its user has no home.
                env={**os.environ, "HOME": folder},
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise PdfError(type(error).__name__) from error
        if not target.is_file():
            tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
            raise PdfError(f"exit {done.returncode}: {' | '.join(tail)}")
        return target.read_bytes()


if __name__ == "__main__":  # HTML on stdin, PDF on stdout (scripts/e2e/phase_00.sh)
    sys.stdout.buffer.write(pdf_of(sys.stdin.buffer.read(), find_browser() or ""))
