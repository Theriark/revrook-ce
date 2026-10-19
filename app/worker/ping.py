"""The optional outbound heartbeat: a GET to HEARTBEAT_URL while the worker is healthy.

A dead-man's-switch service (the MSP's own uptime monitor) expects a request every
few minutes and alerts when it stops coming. The worker sends one at most once a
minute, only from the worker that holds the advisory lock and only after a tick that
worked. The request carries nothing but itself: no body, no client data, no header
beyond a fixed user agent. The URL may hold a secret, so it is never logged.
"""

import asyncio
import http.client
import logging
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

logger = logging.getLogger("revrook.worker")

PING_INTERVAL_SECONDS = 60.0
PING_TIMEOUT_SECONDS = 10.0
USER_AGENT = "revrook-heartbeat"


def valid_heartbeat_url(url: str) -> bool:
    """Only an http:// or https:// address with a host is used.

    A space or control character, or a port that is not a number, cannot be sent:
    urllib refuses such an address when it opens it, so it is refused here.
    """
    if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and (port is None or port > 0)
    )


def _get(url: str) -> bool:
    request = urllib.request.Request(
        url, method="GET", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=PING_TIMEOUT_SECONDS) as response:
            return bool(200 <= response.status < 300)
    except (
        urllib.error.URLError,
        http.client.HTTPException,
        OSError,
        ValueError,
        OverflowError,
    ):
        # InvalidURL (a bad port or a character urllib will not send) is an
        # HTTPException and a port above 65535 an OverflowError: neither may stop
        # the worker over an optional setting.
        return False


class Pinger:
    """Sends the heartbeat request at most once per interval."""

    def __init__(
        self, url: str | None, interval: float = PING_INTERVAL_SECONDS
    ) -> None:
        self.url = url
        self.interval = interval
        self._last: float | None = None
        self._warned = False

    async def ping_if_due(self) -> bool | None:
        """Send the request when one is due. None when nothing was sent.

        True when the monitor answered 2xx, False when it did not (logged once until
        it answers again). A URL that is not http or https is refused, also once.
        """
        if not self.url:
            return None
        now = time.monotonic()
        if self._last is not None and now - self._last < self.interval:
            return None
        self._last = now
        if not valid_heartbeat_url(self.url):
            if not self._warned:
                logger.warning("HEARTBEAT_URL must be an http:// or https:// address")
                self._warned = True
            return False
        delivered = await asyncio.to_thread(_get, self.url)
        if not delivered and not self._warned:
            logger.warning("the heartbeat request was not accepted")
            self._warned = True
        elif delivered:
            self._warned = False
        return delivered
