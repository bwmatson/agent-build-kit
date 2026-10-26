# Tasks

Acceptance: none — this is the pipeline's own planning and unit model, with no
surface a consumer drives; what proves it is tier-1 tests that build a joined
unit and that run the planner with a double returning each case.

## 1. [agent-build-kit] [tier1] A unit that carries task groups from more than one change

Needs: open-pr-ceiling group 1 — both change what the readiness rules and the
unit store read from a unit, in the same functions.

Done when a unit can record groups from other changes, is built, reviewed,
ticked, rendered and archived through all of them, a `Needs` on a carried group
resolves to it, and a unit that carries none behaves exactly as before. Nothing
here makes the planner produce one.

- [x] 1.1 Test: a unit recorded without carried groups loads and reports its
      members as its own change and groups; one with carried groups reports
      them in order after its own; its id and branch name do not change.
- [x] 1.2 Test: the build and review prompts for a unit carrying two changes
      name both change directories and each one's groups, and the scope note
      treats all of them as this unit's own.
- [x] 1.3 Test: when such a unit lands, each change's groups are ticked in its
      own tasks file and no other group is.
- [x] 1.4 Test: a change whose groups are all carried by another change's unit
      is not ready to archive while that unit is in review and is ready once it
      has merged; a change with one group carried and one in its own unit needs
      both.
- [x] 1.5 Test: a `Needs` line naming a carried group resolves to the unit that
      carries it.
- [x] 1.6 Test: the pull request body and the unit graph name every change the
      unit carries with its groups.
- [x] 1.7 Add the carried groups to the unit model and the store, with a single
      way to ask a unit for its members.
- [x] 1.8 Read members, not the unit's own change and groups, in the prompts,
      the scope note, task ticking, archive readiness, `Needs` resolution, the
      pull request body and the graph.
- [x] 1.9 Update `docs/architecture.md` where a unit is defined and where
      archiving is described.

## 2. [agent-build-kit] [tier1] The planner joins small related sequential work

Done when planning a change considers every unstarted unit — new and already
planned — and can join a new change's groups onto an existing unit or one
existing unit onto another, every rule for a join is checked and a violation
refuses the round, started and finished units are never part of a join, a unit
joined away is removed with its dependents repointed, a group can be marked
separate, and the join is logged.

- [x] 2.1 Test: a planner reply that adds a new change's group to an unstarted
      unit in the same repo and tier, in a straight line and under the ceiling,
      is accepted; the unit carries the group and no unit is created for it.
- [x] 2.2 Test: the same reply is refused when the repo or the tier differs,
      when another unit depends on the named unit, when the groups wait on
      something else unfinished, when any group involved is flagged acceptance,
      contract or narrowing, and when the combined estimate is over the
      ceiling — each in turn.
- [x] 2.3 Test: a join naming a unit that has a branch, a commit, a pull
      request or a step to resume at, or that is in review, merged or otherwise
      finished, is refused, whichever side of the join it is on; and when a
      unit starts between the plan and the write, that join is dropped, both
      units are untouched and the rest of the plan is written.
- [x] 2.4 Test: two existing unstarted units — of different changes, and of
      the same change — in a straight line and under the ceiling are joined:
      the earlier carries the later's groups, the later is removed from the
      store, and a unit that depended on the later depends on the earlier.
- [x] 2.5 Test: planning the joined-away unit's change again creates no unit
      for groups another unit carries; and three unstarted units in a line
      under the ceiling become one in a single round.
- [x] 2.6 Test: a group marked `Separate:` is never carried by another unit and
      nothing is added to its unit; `abk tags` rejects the line without a
      reason.
- [x] 2.7 Test: a unit joined to once is joined to again while unstarted and
      under the ceiling, and refused once the sum passes it.
- [x] 2.8 Test: an accepted join is logged with the groups, the unit and the
      combined estimate; and the planner is shown, for each in-flight unit,
      whether it is unstarted.
- [x] 2.9 Tell the planner which in-flight units are unstarted, that any two
      of them are candidates as well as the change being planned, when to join
      and when not to, and the reply shape for a join.
- [x] 2.10 Validate a join against the rules, write it under both units' locks
      with the unstarted check repeated, remove a unit joined away and repoint
      its dependents, and log it.
- [x] 2.11 Parse and validate `Separate:` alongside `Needs:` and `Acceptance:`.
- [x] 2.12 Update `docs/architecture.md` where planning is described, and the
      `abk-authoring` skill for `Separate:` and for when a small related
      requirement should be its own change.
