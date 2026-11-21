"""Whether the words a failed agent run ended on say the network was down."""

from __future__ import annotations

import re
from typing import Literal

Strength = Literal["strong", "weak"]

# A name or route that cannot be resolved or reached: the run itself saw the network fail.
STRONG = (
    "eai_again",
    "enotfound",
    "enetunreach",
    "ehostunreach",
    "getaddrinfo",
    "temporary failure in name resolution",
    "network is unreachable",
)

# What a live network can also produce: a host that is down, refusing or slow.
WEAK = (
    "can't reach the api server",
    "econnrefused",
    "etimedout",
    "connect timed out",
    "connection reset",
)

# An answer from a reachable service: the status belongs to the service, not the network.
STATUS = re.compile(r"\b(?:api error:?|http/?[\d.]*|status(?: code)?:?)\s*[1-5]\d\d\b", re.I)


def network_failure(text: str) -> Strength | None:
    """`strong` for a name or route that cannot be resolved or reached, `weak`
    for a failure a live network can also produce, None for anything else."""
    if STATUS.search(text):
        return None
    lowered = text.lower().replace("’", "'")
    if any(word in lowered for word in STRONG):
        return "strong"
    if any(word in lowered for word in WEAK):
        return "weak"
    return None
