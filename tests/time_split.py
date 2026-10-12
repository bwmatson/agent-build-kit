"""A pytest plugin that splits a tier 2 test's time by agent role, checks and the rest.

Stub: the plugin is written by the implementation of its group.
"""

from __future__ import annotations

import time

# What the plugin reads time from: `monotonic()`; a test replaces it with a clock it moves.
clock = time
