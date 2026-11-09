"""Every agent call of a moved-base run in the lane is asked of the usage guard, the resolver of
the run's own move as well as the port and the review (spec: restack-conflicts, a restack in the
lane honours the usage guard for its agent step).

The guard is the real one over the faked usage endpoint; the move is faked at `restack_onto`'s
edge (`tests/lane_run_usage_support.py`).
"""

from __future__ import annotations

import json

from tests.lane_run_usage_support import MINUTE, Lane, make_lane  # noqa: F401 — fixture
from tests.usage_host import Host


def admitted(host: Host) -> list[str]:
    return json.loads(host.cache.read_text()).get("estimate_units", [])
