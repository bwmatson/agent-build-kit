"""The lane's two counts are gauges of their own, set where the slot gauges are, with no unit or
change attribute; a restack in the lane counts toward the slot gauges' occupancy.

A tick is driven as `test_restack_lane_tick` drives it: the poll hands the lane a restack that
blocks on an event, and the pass sets it when it next asks the lane to say when a restack ends,
which it does once the first sample's gauges are set, so they are read with the restack running.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("scripted_engine")
