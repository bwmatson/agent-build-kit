# Category: Lint/type regressions (zero-tolerance)

Weekly-cadence category (run via `improve.md`) — this doesn't change hour
to hour, so a daily check would just be wasted budget. A project is
expected to be maintained at a zero-violation baseline for whatever its
own `.pre-commit-config.yaml` runs — read it for the actual tool list
and scope rather than assuming (a formatter and a linter, a type checker
on some subset of packages, a JavaScript linter on frontend packages).
CI normally blocks any PR that introduces a new violation, so under
normal operation this category should find nothing.

Run `pre-commit run --all-files` in this run's project and report anything
it flags. If it's clean (expected), say so plainly rather than
manufacturing a finding — this category existing is about catching drift
between CI runs (e.g. a direct push that bypassed a PR, or a pre-commit
hook version bump that surfaces previously-passing code as
newly-violating), not about finding work every run. (If a hook resolves
imports from a sibling checkout of another repo in this workspace, a
failure that's really "the sibling checkout is missing or stale" is an
environment problem, not a code finding; say which.)

If the type checker's scope could usefully expand to more of the
project's packages, note that as a finding, but don't do it unprompted —
it's a larger, deliberate scope expansion, not a "regression fix."
