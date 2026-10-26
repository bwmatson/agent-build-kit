# Proposal

## Why

The test step may write stubs today, but nothing makes it: a tests commit can import code that does not exist, and the push gate
skips type checking there for that reason, so a failure the agent could have fixed in a minute is found at push time, after the whole
build has run. The red run is also weaker evidence than it looks, because a missing module or attribute counts as red, and that is a
test that cannot be collected or a stub nobody wrote, not a test that failed for the missing behaviour.

A unit of several task groups is also built as one tests commit and one implementation commit, so a reviewer cannot read it group by
group, and a later change that splits a unit has no group-sized piece of built work to reuse: it would have to rebuild everything.

## What Changes

- **The test step writes stubs that pass static analysis.** Signatures that only raise `NotImplementedError` and model fields, so the
  tests import, and the files pass lint, format and types at the tests commit.
- **A check-and-fix loop runs before the tests commit.** The pipeline runs the profile's static checks over what the test agent wrote,
  hands a failure back to the test agent with a fix prompt, and repeats up to `global_limits.max_check_rounds` with its own counter. A
  unit still failing then stops, with the output kept, before any implementation is attempted. The tests are not run here.
- **The build commits per group.** For each task group in order, a `test: <group title>` commit with its stubs and tests, then a
  `feat: <group title>` commit with its implementation, each with a body saying why.
- **Each group's red is judged at its own tests commit, and for the right reason.** In a stubbed build only an assertion failure or
  `NotImplementedError` raised in a test body is red; an import, module or attribute error is not.
- **The push gate's clean check includes types** for a stubbed build, in the python-uv and node-npm profiles.
- **A profile declares whether it supports stubs.** One that does not keeps today's single pair and today's checks.
- **It is a setting, `builders.per_group_commits`,** off while the build-out is tried and on once the soak criterion in the design is met.

## Impact

With the setting off nothing changes. With it on, a build is longer (one agent call to write the tests of each group, and a fix call
when a static check fails) and its branch has more commits. The branch still reads as tests-then-implementation pairs, so the push
gate's rules still hold. Review, the PR body and the poller see the same unit, one branch and one pull request.
