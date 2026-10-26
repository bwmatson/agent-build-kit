# Design

## What the habitat actually is

A build does not run in a checkout. It runs in a git worktree created off the repo, on a branch
named for the unit, with the repository's own pre-commit gate between it and every commit, inside
whatever workspace layout that repo uses. Three of those four are invisible to the existing suite,
and the failure they produced was instructive: a type checker configured perfectly well for a
checkout matched no files at all in a worktree, and the only symptom was a unit failing its tests
commit.

So the test is not "does the pipeline work end to end" — that is the pipeline's own job, and it
involves agents. It is narrower: **in a real worktree, does a commit pass the real gate?** Make a
worktree, write a trivially correct file, run the repo's gate, commit. If a hook cannot see the
files, or the formatter and linter disagree about the same line, the test fails and names which.

It is marked as an integration test because it needs the network to install hook environments, so
it runs where the framework's integration job runs rather than in the default suite. That is the
right trade: the default suite stays fast and hermetic, and the habitat is checked on every pull
request.

## Parsers, and the line between public and private

Four functions read text the framework does not control:

- the set of tests a commit range added — a diff;
- what a CLI said about how a run ended, as opposed to what the run printed on its way — a
  transcript;
- whether a refusal is a usage limit, and when it resets — a message;
- the adapt step's decisions — an agent's structured answer.

Three are already part of their module's interface. One — the test-set derivation — is private, and
it is the one that had the bug.

The rule applied here, and worth stating generally: **a test reaches a public surface.** If a
private helper holds behaviour worth pinning, there are two honest options, and importing the
private name is neither:

- **Promote it.** The question "which tests did this range define, delete, or edit inside?" is a
  real question with a real contract, asked by the adapt step and answerable independently. Naming
  it makes it testable, documentable and replaceable.
- **Test through its caller.** Where the helper is genuinely incidental — a formatting detail, a
  path calculation — the public function that uses it is the thing with the contract, and the test
  belongs there.

The reason is not purity. A test bound to a private name freezes an implementation: the next person
to improve it must either keep the shape or rewrite tests that never described the behaviour
anyone depends on. Testing the public surface leaves the inside free to change.

## What is deliberately not added

No integration test of a build, a review or a rework. They cost minutes and money per run, they
are non-deterministic, and the failures this change responds to were not there. The agent-driven
paths are already covered where it matters — the argv a runtime builds, the outcome it classifies,
the verdict a review returns — by fakes at the process boundary.
