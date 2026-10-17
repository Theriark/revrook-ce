import socket

import pytest


def test_connecting_to_a_public_address_is_blocked() -> None:
    # 192.0.2.1 is TEST-NET-1: the guard raises before any packet is sent.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(RuntimeError, match="blocked in tests"):
            sock.connect(("192.0.2.1", 9))


def test_connect_ex_to_a_public_address_is_blocked() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(RuntimeError, match="blocked in tests"):
            sock.connect_ex(("192.0.2.1", 9))


def test_resolving_a_public_name_is_blocked() -> None:
    with pytest.raises(RuntimeError, match="blocked in tests"):
        socket.getaddrinfo("example.com", 443)


def test_loopback_stays_reachable() -> None:
    # Port 1 is closed: the guard lets the attempt through and the OS refuses it.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        assert sock.connect_ex(("127.0.0.1", 1)) != 0
