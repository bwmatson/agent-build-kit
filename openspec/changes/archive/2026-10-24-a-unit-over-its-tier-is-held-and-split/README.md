# a-unit-over-its-tier-is-held-and-split

Phase 7 of the risk-tiered review work (design: `docs/risk-tiered-review-design.md`, philosophy:
`docs/agent-efficient-coding-philosophy.md`, both in the framework repo). A unit that earns a higher review tier than it was sized for,
or that grows past its tier's ceiling by more than a buffer, is not sent to a person as it stands: it is held, superseded by units the
planner makes from its groups under a constraint, and each of those is built and reviewed on its own. The work already built is reused
when the build committed per group. The last group turns per-tier sizing on by default, so the 5000 and 2000 ceilings take effect.
