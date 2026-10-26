# per-unit-run-logs

Write each unit's run to a file of its own, named so that every run of one unit sorts together:
the unit's identity first, then when it ran, then which step.

A unit's log lives only in the system journal today. Every diagnosis this week meant
`journalctl` with a guessed time window, and after rotation those runs are simply gone — including
the ones that explain why a unit failed.
