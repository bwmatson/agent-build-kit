## From `release-on-hold-label-removed/1`

- on_release's resume path logs 'waiting for review again' whatever the graph node did with the release. Read the stored unit after resume and log a restored depth hold or a restack truthfully (events.py:952).
- The graph test for a taken-over depth hold released within the cap stops at RUNNING and next node PREPARE. Tick on through prepare to pin that the branch is moved off the merged-away parent.
- src/agent_build_kit/pipeline/events.py:952 — When a thread takes the release, on_release always logs 'waiting for review again', even if the graph node has just put the unit back on its depth hold or resumed it at prepare.
- tests/graph/test_release_event.py:129 — The graph test for a release within the cap stops at state RUNNING and next node PREPARE. Nothing checks that prepare then moves a branch that is still on a merged-away parent onto the new base.
