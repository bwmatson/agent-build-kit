# commit-gate-rework

When a repo's own commit gate rejects a unit's commit, show the agent what the
gate said and let it fix it, instead of ending the unit.

Found the hard way: a unit that had written all thirteen of its tests, and
verified each failed for the right reason, was ended by one 105-character line —
which the formatter in the same hook run had already rewrapped. The work was
correct and on disk; nothing was wrong that a second look would not have fixed.
