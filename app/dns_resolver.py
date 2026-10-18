"""The resolvers behind the public DNS check (phase 7).

`app/checks/dnscheck.py` asks a `Resolver`; these are the two that ask the real DNS.

* `DnsPythonResolver` uses dnspython (ISC licence, see docs/licences.md): the
  system's resolvers, or the one nameserver whose IP address is in `DNS_RESOLVER`.
* `DohResolver` sends DNS over HTTPS (RFC 8484) to the `https://` URL in
  `DNS_RESOLVER`. It uses the standard library (`http.client`, certificates checked
  against the system store, no redirect followed) and dnspython only to write the
  question and read the answer, so httpx, which would bring certifi into the
  runtime lock, is not needed.

Every lookup has a deadline of five seconds. NXDOMAIN and an empty answer are `()`;
a timeout, SERVFAIL, a refused or unreadable answer is a `LookupFailure`, which the
check stores as a failed lookup and never as a failed domain.
"""

import base64
import http.client
import ipaddress
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import dns.exception
import dns.message
import dns.rcode
import dns.rdata
import dns.rdatatype
import dns.rdtypes.ANY.CNAME
import dns.rdtypes.ANY.TXT
import dns.resolver

from app.checks.dnscheck import (
    RESOLVER_ERROR,
    SERVFAIL,
    TIMEOUT,
    LookupFailure,
    Resolver,
)

LOOKUP_LIFETIME = 5.0
MAX_ANSWER_BYTES = 65_535
DEFAULT_DOH_PATH = "/dns-query"

Connect = Callable[[str, int, float], http.client.HTTPSConnection]


def rdata_text(rdata: dns.rdata.Rdata) -> str | None:
    """The text of a TXT record (its strings joined) or the target of a CNAME."""
    if isinstance(rdata, dns.rdtypes.ANY.TXT.TXT):
        return b"".join(rdata.strings).decode("utf-8", "replace")
    if isinstance(rdata, dns.rdtypes.ANY.CNAME.CNAME):
        return str(rdata.target.to_text(omit_final_dot=True))
    return None


class DnsPythonResolver:
    """Asks the system's resolvers, or one nameserver, through dnspython."""

    def __init__(
        self, nameserver: str | None = None, lifetime: float = LOOKUP_LIFETIME
    ) -> None:
        self._nameserver = nameserver
        self._lifetime = lifetime
        self._resolver: dns.resolver.Resolver | None = None

    def _get(self) -> dns.resolver.Resolver:
        if self._resolver is None:
            # Typed as Any: dnspython's nameservers property reads and writes
            # different types, which the type checker cannot follow.
            resolver: Any = dns.resolver.Resolver(configure=self._nameserver is None)
            if self._nameserver is not None:
                resolver.nameservers = [self._nameserver]
            resolver.lifetime = self._lifetime
            resolver.timeout = self._lifetime
            self._resolver = resolver
        return self._resolver

    def lookup(self, name: str, rdtype: str) -> tuple[str, ...]:
        try:
            answer = self._get().resolve(name, rdtype)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return ()
        except dns.exception.Timeout:
            raise LookupFailure(TIMEOUT) from None
        except dns.resolver.NoNameservers:
            raise LookupFailure(SERVFAIL) from None
        except (OSError, dns.exception.DNSException):
            raise LookupFailure(RESOLVER_ERROR) from None
        texts = (rdata_text(rdata) for rdata in answer)
        return tuple(text for text in texts if text is not None)


def _https_connection(
    host: str, port: int, timeout: float
) -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(host, port, timeout=timeout)


class DohResolver:
    """Asks a DNS-over-HTTPS server (RFC 8484, GET with the question in the URL)."""

    def __init__(
        self,
        url: str,
        timeout: float = LOOKUP_LIFETIME,
        connect: Connect = _https_connection,
    ) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError("the DNS-over-HTTPS URL must start with https://")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("the DNS-over-HTTPS URL must be a plain address")
        self._host = parts.hostname
        self._port = parts.port or 443
        self._path = parts.path or DEFAULT_DOH_PATH
        self._timeout = timeout
        self._connect = connect

    def lookup(self, name: str, rdtype: str) -> tuple[str, ...]:
        try:
            question = dns.message.make_query(name, rdtype)
            question.id = 0
            wire = base64.urlsafe_b64encode(question.to_wire()).rstrip(b"=")
        except (dns.exception.DNSException, UnicodeError):
            raise LookupFailure(RESOLVER_ERROR) from None
        connection = self._connect(self._host, self._port, self._timeout)
        try:
            connection.request(
                "GET",
                f"{self._path}?dns={wire.decode('ascii')}",
                headers={"Accept": "application/dns-message"},
            )
            response = connection.getresponse()
            status = response.status
            body = response.read(MAX_ANSWER_BYTES + 1)
        except TimeoutError:
            raise LookupFailure(TIMEOUT) from None
        except (OSError, http.client.HTTPException):
            raise LookupFailure(RESOLVER_ERROR) from None
        finally:
            connection.close()
        if status != 200 or len(body) > MAX_ANSWER_BYTES:
            raise LookupFailure(RESOLVER_ERROR)
        return self._texts(body, rdtype)

    @staticmethod
    def _texts(body: bytes, rdtype: str) -> tuple[str, ...]:
        try:
            message = dns.message.from_wire(body)
        except dns.exception.DNSException:
            raise LookupFailure(RESOLVER_ERROR) from None
        code = message.rcode()
        if code == dns.rcode.NXDOMAIN:
            return ()
        if code != dns.rcode.NOERROR:
            failed = code == dns.rcode.SERVFAIL
            raise LookupFailure(SERVFAIL if failed else RESOLVER_ERROR)
        wanted = dns.rdatatype.from_text(rdtype)
        texts: list[str] = []
        for rrset in message.answer:
            if rrset.rdtype != wanted:
                continue
            for rdata in rrset:
                text = rdata_text(rdata)
                if text is not None:
                    texts.append(text)
        return tuple(texts)


def make_resolver(setting: str | None) -> Resolver:
    """The resolver for `DNS_RESOLVER`: unset, an IP address, or an https:// URL."""
    if setting is None:
        return DnsPythonResolver()
    if setting.lower().startswith("https://"):
        return DohResolver(setting)
    try:
        ipaddress.ip_address(setting)
    except ValueError:
        raise ValueError(
            "DNS_RESOLVER must be an IP address or an https:// URL"
        ) from None
    return DnsPythonResolver(nameserver=setting)
