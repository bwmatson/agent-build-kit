# needs-gate-started-units

A `Needs:` line added to a unit's task group after the unit has started. Today it is recorded and
then ignored for any unit that has left `planned`: a requeued failed unit runs again past an unmerged
prerequisite. This makes the gate hold it, visibly, and release it when the prerequisite merges.
