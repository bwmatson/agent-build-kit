## Why

With `builders.per_group_commits` on (to be renamed `builders.stubbed_tdd_commits` by group 12 of `tests-are-stubbed-checked-and-committed-per-group`,
which is held; this change uses the current name and the rename carries through), a build commits for each task group a `test:` commit and then a
`feat:` commit, counts its pairs after the last group (`unpaired`, `src/agent_build_kit/graph/nodes.py:1398-1406`, called from `implement` at
`1446-1448`) and the push gate requires every `test:` commit to be followed directly by a `feat:` commit of the same title
(`_pair_problems`, `src/agent_build_kit/pipeline/commit_order.py:168-188`, mode switched on at `262-266`).

A group that builds nothing has no `feat:` commit to make. On 2026-10-21 unit `asr-streaming-service/10` (repo <redacted>) stopped at `implement`
with "the branch holds no tests and implementation pair for group 10 (Drive the service as a client)". Group 10 is
`[<redacted>] [e2e-test] [acceptance]`; tasks 10.1-10.4 add live-stack acceptance tests and test-support code against code that groups 1-9 already
built. The agent made the tests commit (`849149e`) and "made no implementation changes"; the pair count correctly found no pair and stopped the unit.
Every acceptance group has this shape (`abk-authoring`: it "drives what the change built the way its consumer does", comes after every group it
exercises, and "Do not write a task a builder cannot do" keeps its fixes out of it), so every change's acceptance unit would stop the same way. The
sibling change `e2e-groups-hold-tests-and-stand-alone` extends the shape to every `[e2e-test]` group, flagged or not: each holds only tests and test
support, and a product fix is made by a separate `[unit-test]` unit. So every e2e group is test-only in content, and a plain `[e2e-test]` group would
stop the same way.

Two more rules in the same code would refuse it even if the count passed:

- the gate's `no implementation commit, only tests` rule (`commit_order.py:254-255`) and `two tests commits in a row` rule (`257-262`) apply to a
  branch of `test:` commits with no `feat:` between them (a test-only group before another group, or a unit of one);
- the gate runs the red command at every tests commit (`src/agent_build_kit/pipeline/gate.py:101-139`) and rejects a run where nothing was collected
  or the failure is not an assertion, `NotImplementedError` or a missing name (`red_check.py:114-155`); live-stack tests cannot be run in the builder's
  session (they need the dev stack and a service key), so they cannot be shown red there.

This was found by the soak of `builders.per_group_commits`. It does not count against the soak's criterion of "no push-gate refusals" (the design of
`tests-are-stubbed-checked-and-committed-per-group`): the unit was stopped by the build's pair-count check, not refused by the push gate.

## What Changes

- **A test-only group is defined from its heading.** A group tagged `[e2e-test]`, flagged `[acceptance]` or not; `TaskGroup` exposes it as a property
  (`test_only`) and the per-group build step carries it, so the build, the resume and the gate all read one fact.
- **A test-only group makes one commit, `test: <group title>`, and no `feat:` commit.** The stub check loop still runs on it (lint, format, types),
  no stubs are required, no red run is demanded, and its implement step is skipped with no agent call.
- **The pair count counts it.** A test-only group is satisfied by its lone `test:` commit; a group that is not test-only and has no implementation
  still stops the unit.
- **The push gate accepts it, from the plan.** A `test:` commit with no `feat:` after it passes only when it is the commit of a test-only group; it
  is not asked for a red run (its static checks still run, with types); the "implementation commit" and "two tests commits in a row" rules take it
  into account; a unit whose groups are all test-only needs no implementation commit.
- **Resume is unchanged in kind.** A test-only group is done when its `test:` commit is on the branch.
- **Docs, the `abk-authoring` skill text and the changelog say so.**

## Impact

Units with an `[e2e-test]` group build and push where they stopped. Nothing changes for a build that is not stubbed (one pair for the whole unit, as
before), for a group that is not test-only, or for the red rule on any unit-test or integration-test group. No new setting; the rename of the
setting carries through.

## Not in this change

- An `[e2e-test]` group that builds product code: the sibling change `e2e-groups-hold-tests-and-stand-alone` forbids it (a guard stops such a unit),
  and this change relies on that; until the guard is built the risk is accepted (design, Risks).
- A `[unit-test]` or `[integration-test]` group of only tests: it is not test-only and still needs its `feat:` commit.
- Any change to `abk.yaml`, the setting's name or its default (group 12 of `tests-are-stubbed-checked-and-committed-per-group`).
