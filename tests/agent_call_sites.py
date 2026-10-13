"""The guard over agent calls: every call that sends a prompt to an agent records a ledger row.

`check_sources` returns one message per problem: a call that records nothing and is not on the
allowlist names `path:line`; an allowlist entry whose site now records, or is gone, is reported
as a stale entry. An entry is `(path under the root, function name)` with its reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

SRC_ROOT = Path(__file__).parent.parent / "src" / "agent_build_kit"

# Sites not yet converted. It may only shrink.
ALLOWLIST: Mapping[tuple[str, str], str] = {}


def check_sources(root: Path, *, allowlist: Mapping[tuple[str, str], str]) -> list[str]:
    raise NotImplementedError
