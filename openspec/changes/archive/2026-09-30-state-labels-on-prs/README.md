# state-labels-on-prs

Put a unit's state on its pull request as a label, so the pull request list says
where everything is without opening anything or running a command — and consume
the labels a person adds, so an instruction stops looking like a standing request.

Labels are read-only to the pipeline today: it acts on `agent:hold` and
`agent:rework` and writes nothing back. A pull request therefore looks the same
whether its unit is building, waiting for review, being reworked or held for a
person.
