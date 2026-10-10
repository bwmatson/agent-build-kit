"""The address the proxy tests use for an upstream that cannot be reached."""

import socket
from urllib.parse import urlsplit

import pytest

from tests.replay.support import refused_url


def test_the_address_refuses_connections_and_cannot_be_taken_while_in_use() -> None:
    with refused_url() as url:
        address = urlsplit(url)
        assert address.hostname is not None and address.port is not None
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection((address.hostname, address.port), timeout=5)
        with socket.socket() as other, pytest.raises(OSError):
            other.bind((address.hostname, address.port))
