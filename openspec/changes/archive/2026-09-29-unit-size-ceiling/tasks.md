# Tasks

Acceptance: none — the ceiling is internal to planning, with no surface a consumer
drives; what proves it is tier-1 tests over the packer and the planner's
rejection path.

## 1. [agent-build-kit] [tier1] A ceiling on what the planner puts in one unit

Done when a workspace can configure the ceiling, the packer cannot combine groups
past it, a plan that exceeds it is re-asked, and a change whose own task group is
too large is named as such rather than planned badly.

- [x] 1.1 Test: the ceiling defaults to 1000; a floor at or above the ceiling
      fails to load with both values named.
- [x] 1.2 Test: the packer splits consecutive same-repo groups rather than
      combining them past the ceiling, and still respects the floor below it.
- [x] 1.3 Test: a returned plan containing a unit estimated over the ceiling is
      rejected with that reason and the planner is asked again within the existing
      attempt budget.
- [x] 1.4 Test: a change with one task group estimated over the ceiling is left
      unplanned, with a message naming the group and saying its tasks must be
      split — and no planning attempt is spent retrying it.
- [x] 1.5 Add the ceiling to the configuration with its validation, and pass it to
      both the planner's prompt and the packer.
- [x] 1.6 Document the ceiling in `docs/configuration.md` and the `abk-config`
      skill, and say in `docs/architecture.md`, where unit sizing is described,
      that it shapes plans only — an estimate is not checked against the branch,
      so a unit can still land larger than the ceiling.
