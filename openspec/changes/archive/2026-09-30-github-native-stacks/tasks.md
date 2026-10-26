# Tasks

Acceptance: none — the surface is the code host's own API, and a tier-1 test
cannot prove a real stack appeared. The first chain built after this lands shows
it, on the host, where the reviewer looks; and because registration is advisory,
being wrong about availability costs nothing.

## 1. [agent-build-kit] [tier1] Register the chain the pipeline already builds

Needs: adapt-counts-the-units-own-tests group 1 — this unit is 43 commits behind
main and its restack therefore runs the adapt step, which fails it for not deciding the
fate of tests it never wrote. It cannot pass until that list is derived correctly.

Done when a chain of pull requests becomes one stack on a host that has them, a
host that does not is unaffected, a refusal costs nothing, and the body stops
restating what the host renders.

- [x] 1.1 Test: the forge declares whether the host has stacks; with it false,
      opening a pull request registers nothing and the body reads as it does
      today.
- [x] 1.2 Test: opening a unit's pull request against a base unit whose pull
      request is in no stack creates a stack with both, bottom first; against one
      already in a stack appends to it; against one in a stack that cannot be
      extended starts a new stack.
- [x] 1.3 Test: a refusal to register — feature unavailable, repository
      ineligible, chain rejected — leaves the unit's state, its pull request and
      every later step unchanged, with the reason on the unit's record and logged
      once; a refusal for concurrent modification is retried.
- [x] 1.4 Test: a branch whose head no longer matches the recorded approval is
      re-reviewed before any push, and nothing is merged on the old approval,
      whether or not a run of that unit moved it.
- [x] 1.5 Test: on a host with stacks the body omits the unit's position and what
      is beneath it and states linearity; on a host without them the body is
      unchanged; a chain the pipeline left non-linear says so either way.
- [x] 1.6 Add the capability flag and the stack calls to the forge — read which
      stack a pull request is in, create a stack from an ordered list of pull
      request numbers, append to one — behind the forge interface, so no other
      module names the host.
- [x] 1.7 Register the stack at the step that opens a pull request, after the
      approved-commit check and the push, and record a refusal on the unit.
- [x] 1.8 Make the body's stack prose conditional on the capability, and add the
      linearity line.
- [x] 1.9 Say in `docs/architecture.md`, where stacking and the push step are
      described, that the chain is registered with the host where it can be, that
      the pipeline still owns rebasing because there is no API for it, and that
      the host may rebase branches itself after a stack merge.
