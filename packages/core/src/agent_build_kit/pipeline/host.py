"""The name of this machine, and whether a lock holder's record is its own."""

from __future__ import annotations

import socket


def this_host() -> str:
    return socket.gethostname()


def is_here(record_host: str | None) -> bool:
    """Whether a record's host is this machine's; a record without one predates host names
    and belongs to the one host that wrote it."""
    return not record_host or record_host == this_host()
