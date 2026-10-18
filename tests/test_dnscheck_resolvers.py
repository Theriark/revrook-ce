"""The two resolvers that ask the real DNS (phase 7), tested without the network.

dnspython is given a fake `Resolver` class and the DNS-over-HTTPS client a fake
connection, so nothing is sent; the last tests of each resolver show that without
the fakes the conftest guard stops the attempt before any packet leaves.
"""

import base64
import http.client
from typing import Any

import dns.exception
import dns.message
import dns.rcode
import dns.rdata
import dns.rdataclass
import dns.rdatatype
import dns.resolver
import dns.rrset
import pytest

from app.checks.dnscheck import RESOLVER_ERROR, SERVFAIL, TIMEOUT, LookupFailure
from app.dns_resolver import (
    DnsPythonResolver,
    DohResolver,
    make_resolver,
    rdata_text,
)


def rdata(rdtype: str, text: str) -> dns.rdata.Rdata:
    return dns.rdata.from_text(dns.rdataclass.IN, dns.rdatatype.from_text(rdtype), text)


def rrset(name: str, rdtype: str, *texts: str) -> dns.rrset.RRset:
    return dns.rrset.from_text(f"{name}.", 300, "IN", rdtype, *texts)


# --- the answer text ---------------------------------------------------------------


def test_the_strings_of_a_txt_record_are_joined() -> None:
    assert rdata_text(rdata("TXT", '"v=spf1 " "include:a.example.net -all"')) == (
        "v=spf1 include:a.example.net -all"
    )


def test_a_cname_is_its_target_without_the_final_dot() -> None:
    assert rdata_text(rdata("CNAME", "target.example.net.")) == "target.example.net"


def test_any_other_record_has_no_text() -> None:
    assert rdata_text(rdata("A", "192.0.2.1")) is None


def test_bytes_that_are_not_utf8_are_replaced_not_raised() -> None:
    odd = rdata("TXT", r'"caf\233"')
    assert rdata_text(odd) == "caf�"


# --- dnspython -----------------------------------------------------------------------


class FakeDnsResolver:
    """Stands in for dns.resolver.Resolver: records how it was made and asked."""

    made: list[dict[str, Any]] = []
    result: Any = []

    def __init__(self, configure: bool = True) -> None:
        self.configure = configure
        self.nameservers: list[str] = []
        self.lifetime = 0.0
        self.timeout = 0.0
        self.asked: list[tuple[str, str]] = []
        FakeDnsResolver.made.append({"configure": configure, "self": self})

    def resolve(self, name: str, rdtype: str) -> Any:
        self.asked.append((name, rdtype))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def fake_dns(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    FakeDnsResolver.made = []
    FakeDnsResolver.result = result
    monkeypatch.setattr(dns.resolver, "Resolver", FakeDnsResolver)


def test_dnspython_answers_are_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, [rdata("TXT", '"v=spf1 -all"'), rdata("A", "192.0.2.1")])
    resolver = DnsPythonResolver(nameserver="192.0.2.53")
    assert resolver.lookup("client.example", "TXT") == ("v=spf1 -all",)
    assert FakeDnsResolver.made[0]["self"].asked == [("client.example", "TXT")]


def test_dnspython_with_a_nameserver_does_not_read_the_system_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_dns(monkeypatch, [])
    DnsPythonResolver(nameserver="192.0.2.53", lifetime=2.5).lookup("a.example", "TXT")
    made = FakeDnsResolver.made[0]["self"]
    assert FakeDnsResolver.made[0]["configure"] is False
    assert made.nameservers == ["192.0.2.53"]
    assert (made.lifetime, made.timeout) == (2.5, 2.5)


def test_dnspython_without_a_nameserver_uses_the_system_resolvers_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_dns(monkeypatch, [])
    resolver = DnsPythonResolver()
    resolver.lookup("a.example", "TXT")
    resolver.lookup("b.example", "CNAME")
    assert len(FakeDnsResolver.made) == 1
    assert FakeDnsResolver.made[0]["configure"] is True
    assert FakeDnsResolver.made[0]["self"].lifetime == 5.0


def quiet(kind: type[Exception]) -> Exception:
    """An instance of a dnspython exception without its message formatting."""

    class Quiet(kind):  # type: ignore[valid-type, misc]
        def __init__(self) -> None:
            Exception.__init__(self, kind.__name__)

        def __str__(self) -> str:
            return kind.__name__

    return Quiet()


@pytest.mark.parametrize(
    "error",
    [quiet(dns.resolver.NXDOMAIN), quiet(dns.resolver.NoAnswer)],
    ids=["nxdomain", "no-answer"],
)
def test_no_such_record_is_an_empty_answer(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    fake_dns(monkeypatch, error)
    assert DnsPythonResolver("192.0.2.53").lookup("a.example", "TXT") == ()


FAILURES = [
    ("timeout", quiet(dns.exception.Timeout), TIMEOUT),
    ("lifetime", quiet(dns.resolver.LifetimeTimeout), TIMEOUT),
    ("no-nameservers", quiet(dns.resolver.NoNameservers), SERVFAIL),
    ("yxdomain", quiet(dns.resolver.YXDOMAIN), RESOLVER_ERROR),
    ("no-configuration", quiet(dns.resolver.NoResolverConfiguration), RESOLVER_ERROR),
    ("oserror", OSError("network is unreachable"), RESOLVER_ERROR),
]


@pytest.mark.parametrize(
    ("error", "reason"),
    [(item[1], item[2]) for item in FAILURES],
    ids=[item[0] for item in FAILURES],
)
def test_a_failure_is_a_lookup_failure_with_a_reason(
    monkeypatch: pytest.MonkeyPatch, error: Exception, reason: str
) -> None:
    fake_dns(monkeypatch, error)
    with pytest.raises(LookupFailure) as caught:
        DnsPythonResolver("192.0.2.53").lookup("a.example", "TXT")
    assert caught.value.reason == reason


def test_a_real_lookup_is_stopped_by_the_test_guard() -> None:
    resolver = DnsPythonResolver(nameserver="192.0.2.53", lifetime=0.2)
    with pytest.raises((RuntimeError, LookupFailure)):
        resolver.lookup("client.example", "TXT")


# --- DNS over HTTPS ------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body
        self.asked = 0

    def read(self, amount: int) -> bytes:
        self.asked = amount
        return self.body[:amount]


class FakeConnection:
    def __init__(
        self, response: FakeResponse | None = None, error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error
        self.sent: list[tuple[str, str, dict[str, str]]] = []
        self.closed = False

    def request(self, method: str, path: str, headers: dict[str, str]) -> None:
        self.sent.append((method, path, headers))
        if self.error is not None:
            raise self.error

    def getresponse(self) -> FakeResponse:
        assert self.response is not None
        return self.response

    def close(self) -> None:
        self.closed = True


def doh(connection: FakeConnection, url: str = "https://doh.example/dns-query") -> Any:
    seen: list[tuple[str, int, float]] = []

    def connect(host: str, port: int, timeout: float) -> Any:
        seen.append((host, port, timeout))
        return connection

    resolver = DohResolver(url, connect=connect)
    resolver.seen = seen
    return resolver


def reply(
    name: str,
    rdtype: str,
    *records: dns.rrset.RRset,
    code: int = dns.rcode.NOERROR,
) -> bytes:
    response = dns.message.make_response(dns.message.make_query(name, rdtype))
    response.set_rcode(code)
    response.answer.extend(records)
    return response.to_wire()


def answered(body: bytes, status: int = 200) -> FakeConnection:
    return FakeConnection(FakeResponse(status, body))


def test_the_question_is_a_get_with_the_query_in_the_url() -> None:
    connection = answered(reply("client.example", "TXT"))
    resolver = doh(connection)
    resolver.lookup("client.example", "TXT")
    [(method, path, headers)] = connection.sent
    assert method == "GET" and headers == {"Accept": "application/dns-message"}
    prefix, _, value = path.partition("?dns=")
    assert prefix == "/dns-query" and "=" not in value
    padded = value + "=" * (-len(value) % 4)
    sent = dns.message.from_wire(base64.urlsafe_b64decode(padded))
    assert sent.id == 0
    [question] = sent.question
    assert question.name.to_text() == "client.example."
    assert question.rdtype == dns.rdatatype.TXT
    assert resolver.seen == [("doh.example", 443, 5.0)]
    assert connection.closed


def test_txt_answers_are_texts_and_other_records_in_the_answer_are_skipped() -> None:
    body = reply(
        "client.example",
        "TXT",
        rrset("client.example", "CNAME", "other.example."),
        rrset("other.example", "TXT", '"v=spf1 -all"', '"v=spf1 ~all"'),
    )
    found = doh(answered(body)).lookup("client.example", "TXT")
    assert found == ("v=spf1 -all", "v=spf1 ~all")


def test_a_cname_question_returns_the_target() -> None:
    body = reply(
        "s._domainkey.client.example",
        "CNAME",
        rrset("s._domainkey.client.example", "CNAME", "key.example.net."),
    )
    found = doh(answered(body)).lookup("s._domainkey.client.example", "CNAME")
    assert found == ("key.example.net",)


def test_nxdomain_and_an_empty_answer_are_no_records() -> None:
    nxdomain = reply("a.example", "TXT", code=dns.rcode.NXDOMAIN)
    assert doh(answered(nxdomain)).lookup("a.example", "TXT") == ()
    assert doh(answered(reply("a.example", "TXT"))).lookup("a.example", "TXT") == ()


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        (dns.rcode.SERVFAIL, SERVFAIL),
        (dns.rcode.REFUSED, RESOLVER_ERROR),
        (dns.rcode.FORMERR, RESOLVER_ERROR),
    ],
)
def test_a_failing_rcode_is_a_lookup_failure(code: int, reason: str) -> None:
    with pytest.raises(LookupFailure) as caught:
        doh(answered(reply("a.example", "TXT", code=code))).lookup("a.example", "TXT")
    assert caught.value.reason == reason


@pytest.mark.parametrize(
    "connection",
    [
        answered(b"", status=500),
        answered(b"not a dns message"),
        answered(b"x" * 70_000),
        FakeConnection(error=OSError("connection refused")),
        FakeConnection(error=http.client.BadStatusLine("junk")),
    ],
    ids=["http-500", "garbage", "too-large", "oserror", "http-error"],
)
def test_a_bad_answer_or_connection_is_a_resolver_error(
    connection: FakeConnection,
) -> None:
    with pytest.raises(LookupFailure) as caught:
        doh(connection).lookup("a.example", "TXT")
    assert caught.value.reason == RESOLVER_ERROR
    assert connection.closed


def test_a_timeout_is_a_timeout() -> None:
    connection = FakeConnection(error=TimeoutError("timed out"))
    with pytest.raises(LookupFailure) as caught:
        doh(connection).lookup("a.example", "TXT")
    assert caught.value.reason == TIMEOUT
    assert connection.closed


def test_the_answer_size_is_read_with_a_bound() -> None:
    response = FakeResponse(200, reply("a.example", "TXT"))
    doh(FakeConnection(response)).lookup("a.example", "TXT")
    assert response.asked == 65_536


def test_a_name_that_cannot_be_written_is_a_resolver_error_and_asks_nothing() -> None:
    connection = answered(reply("a.example", "TXT"))
    with pytest.raises(LookupFailure) as caught:
        doh(connection).lookup("a" * 70 + ".example", "TXT")
    assert caught.value.reason == RESOLVER_ERROR
    assert connection.sent == []


@pytest.mark.parametrize(
    "url",
    [
        "http://doh.example/dns-query",
        "doh.example",
        "https://",
        "https://user:secret@doh.example/dns-query",
        "https://doh.example/dns-query?ct=application/dns-message",
        "https://doh.example/dns-query#top",
    ],
)
def test_only_a_plain_https_address_is_accepted(url: str) -> None:
    with pytest.raises(ValueError, match="DNS-over-HTTPS URL"):
        DohResolver(url)


def test_the_default_path_and_a_custom_port() -> None:
    connection = answered(reply("a.example", "TXT"))
    resolver = doh(connection, "https://doh.example:8443")
    resolver.lookup("a.example", "TXT")
    assert connection.sent[0][1].startswith("/dns-query?dns=")
    assert resolver.seen[0][:2] == ("doh.example", 8443)
    custom = answered(reply("a.example", "TXT"))
    doh(custom, "https://doh.example/q").lookup("a.example", "TXT")
    assert custom.sent[0][1].startswith("/q?dns=")


def test_a_real_https_lookup_is_stopped_by_the_test_guard() -> None:
    resolver = DohResolver("https://doh.example/dns-query")
    with pytest.raises(RuntimeError, match="blocked in tests"):
        resolver.lookup("client.example", "TXT")


# --- DNS_RESOLVER ---------------------------------------------------------------------


def test_no_setting_means_the_system_resolvers() -> None:
    resolver = make_resolver(None)
    assert isinstance(resolver, DnsPythonResolver)
    assert resolver._nameserver is None


@pytest.mark.parametrize("address", ["192.0.2.53", "2001:db8::53"])
def test_an_ip_address_is_one_nameserver(address: str) -> None:
    resolver = make_resolver(address)
    assert isinstance(resolver, DnsPythonResolver)
    assert resolver._nameserver == address


@pytest.mark.parametrize(
    "url", ["https://doh.example/dns-query", "HTTPS://doh.example"]
)
def test_an_https_url_is_a_dns_over_https_server(url: str) -> None:
    assert isinstance(make_resolver(url), DohResolver)


@pytest.mark.parametrize("setting", ["resolver.example", "http://doh.example", "1.1"])
def test_anything_else_is_refused_with_a_readable_message(setting: str) -> None:
    with pytest.raises(ValueError, match="DNS_RESOLVER must be"):
        make_resolver(setting)
