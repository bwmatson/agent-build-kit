# Design

## Context

`tests()` and `implement()` in `graph/nodes.py` each make one agent call for the whole unit and one commit (`test: <unit title>` and
`feat: <unit title>`). `TESTS_PROMPT` permits stubs and asks for lint and format to pass; the profile's `clean_command()` that the push
gate runs at the tests commit skips types (python-uv sets `SKIP=pyrefly-check`; node-npm runs lint and the format check only), and
`interpret_red` accepts `ModuleNotFoundError`, `ImportError` and `AttributeError` as red. `checks()` and `fix_checks()` already form a
check-and-fix loop over the whole branch, bounded by `global_limits.max_check_rounds` and counted in `UnitRun.fix_rounds`; the loop here
is its counterpart before the first commit.

## Decisions

- **One setting, in `builders`.** `builders.per_group_commits` (a boolean) goes in `BuildersConfig`, which is "what a builder run may
  do beyond writing files" and is where the build's own behaviour switches live; `global_limits` holds numbers and ceilings, `tests`
  holds test kinds. The switch covers stubs, the check loop and per-group commits together, since the loop and the per-group red are
  only meaningful when the tests commit is stubbed, and one switch is one thing to soak and one thing to roll back. It is workspace
  wide: whether a toolchain can stub is the profile's declaration, not another key. A *stubbed build* below is one with the setting on
  and a unit whose profile supports stubs; anything else is today's build.
- **A profile declares `supports_stubs`.** Read through one helper that treats a profile without the attribute as not supporting them,
  so a third-party profile keeps working. python-uv and node-npm both declare it true, since both already have `stub_violations` and a
  red reading that knows what a stub is.
- **`clean_command` takes a `types` flag, off by default.** The brief says the gate's clean check now includes types, but it cannot
  include them while the setting is off: a tests commit that imports code not yet written would fail the type check, and that is
  today's expected state. So `clean_command(types=True)` is what a stubbed build runs, and `clean_command()` is unchanged. python-uv
  drops the `SKIP=pyrefly-check`; node-npm appends the project's `tsc --noEmit`. The loop and the gate run the same command, so what
  the loop satisfies is what the gate will check.
- **`interpret_red` takes a `stubbed` flag.** Stubbed, only an assertion failure or `NotImplementedError` raised in a test body (or by
  a fixture at setup) is red. A test that fails with an import, module or attribute error means a stub is missing, which the loop
  should have caught and which the implementation would not fix. Unstubbed, the reading is as it is today. node-npm already judges
  this way (a file that failed to load is rejected, "not implemented" is accepted), so its stubbed reading is its present one.
- **The loop is two nodes after `tests`, not a loop inside it.** `stub_checks` runs the clean command with types over the working
  tree, with the new files staged so the checks see them, and commits when it passes; `fix_stub_checks` hands the output to the test
  agent. Every agent call in the graph is a node with its own checkpoint, so a run killed in a fix is resumed there, and the counter
  (`stub_rounds`, on the run state) survives. The tests commit is made only after the checks pass, never amended: the policy forbids
  `--amend`, and a `fix:` commit between a tests commit and its implementation would make the commit read as neither.
- **The failure is saved as feedback with a new source.** `FeedbackSource.STUB_CHECKS` is kept the way a failed tier-1 is, so a stop
  leaves the output on the unit. A requeue finds feedback, which routes to rework today; `after_prepare` sends feedback whose source
  is `STUB_CHECKS` back to `tests`, which sees the saved output and goes straight to the fix.
- **The loop is bounded by `max_check_rounds`, counted apart.** `stub_rounds` starts at zero for each group's tests and is not
  `fix_rounds`, so a stubbed build gets its full allowance at both points. `max_check_rounds: null` is no limit (a fix that changes
  nothing still stops it) and 0 stops at the first failure, as for the build's checks.
- **Per group, in order.** The graph's path becomes `tests`, `stub_checks`, `implement`, and then back to `tests` for the next group
  while groups remain, and on to `checks` after the last. A node reads which group it is on from the branch, not from a counter: group
  `k` is the first group, in the order `r.scope()` lists them (the unit's own change first, then carried ones), whose `feat: <title>`
  commit is not on the branch. A killed run, a restack or a requeue therefore resumes at the right group with no state to lose, which
  is how `tests()` already tells that its commit exists (`r.head(tree) != state.head`).
- **Messages and bodies come from the group, with no model call.** The subject is the group's heading title (`TaskGroup.title`), the
  body the group's "Done when" sentence (`TaskGroup.goal`) after a fixed line saying what the commit holds, and the `Unit:` trailer
  stays. A group with no goal gets only the fixed line. A model-written body would be the review brief's work; this is the floor.
- **The push gate learns the pairs.** `commit_order.check_structure` gains a paired mode: every `test:` commit is followed directly
  by a `feat:` commit with the same title. The other rules stand (a tests commit may carry stubs and nothing else, the first commit is
  tests, there is an implementation commit). `check_branch` takes whether the build is stubbed and, for it, runs the clean command with
  types and reads the red run as stubbed, at every tests commit, so each group's red is judged at its own commit. The patch-id cache
  is keyed with the mode, so a result cached from an unstubbed run, which never ran types, is not reused.
- **The unit still checks its count.** After the last group the build counts the pairs on the branch against the groups; a short
  count stops the unit with the groups named, as `produced_nothing` stops a build that wrote nothing.
- **The name.** The setting ships as `builders.per_group_commits`, which names only the commit shape; it also turns on stubs, the check loop and the stricter red reading, so the last group renames it to `builders.stubbed_tdd_commits`. The old key keeps loading with a deprecation notice and `abk config --migrate` moves it, as for `limits`; a file setting both is refused. The capability, the commit shape and the soak's counts are unchanged by the rename.
- **Soak and the default.** The setting ships off. It is turned on in the installation that builds this framework, and the last group
  makes it the default once, with it on, at least 30 units have been built with at least 10 of them holding two or more groups, no unit
  was refused by the push gate for a type or red reason, and no more than one in ten stopped at the loop's round limit. That group
  changes the default, the tests of the default, the documents and the `abk init` template, and records the figures in the changelog.
  Turning the setting off remains the rollback.

## Risks

- **A longer, dearer build.** One more agent call for each group's tests and a fix call when a static check fails. The soak
  criterion bounds the loop's share, and a profile or installation that finds the cost too high leaves the setting off.
- **Toolchains where stubs are awkward.** A profile opts in; one that does not keeps the single pair. node-npm's `tsc` runs over the
  whole project, so a type error elsewhere fails the loop: the fix prompt names it, and the output is kept like any other.
- **A type check that fails for reasons outside the stubs.** The loop would spend its rounds on a failure the test agent did not cause.
  The same `max_check_rounds` bounds it and the stop keeps the output, so a person sees it was the base.
- **Switching while units are in flight.** The gate reads the setting when it runs. A branch whose tests commit was made before the
  switch already satisfies the paired rule (one `test:` and one `feat:` commit with the same title), but its tests commit may fail the
  types check it never had to pass; such a unit is rebuilt with `abk requeue --restart`. The default is flipped when few units are in
  flight, as the rename of the test kinds was.
