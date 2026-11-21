"""A thread parked at `prepare` is run by the lane past it, to the next wait or the end, in the
unit's recorded build session (spec: unit-scheduling, the lane runs the whole moved-base run).

The scene is the one of `test_restack_lane_prepare`: the unit is `running` with `base_changed`
and its thread at `prepare`. What follows the move used to be left for a build worker; here the
lane's worker goes on, so the thread is read where it is left and from which worker each node ran.
"""

from __future__ import annotations
