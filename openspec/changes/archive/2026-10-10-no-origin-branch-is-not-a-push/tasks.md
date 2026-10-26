# Tasks

Acceptance: none — a fix inside the pipeline's agent wrapper; tier-1 tests over it prove it.

Priority: 2

## 1. [agent-build-kit] [tier1] The agent-pushed guard has nothing to guard without an origin

Done when an agent step that commits in a repo with no `origin` passes, and the guard with an origin is unchanged.

- [x] 1.1 Test: with no `origin`, a stand-in agent that commits to the unit branch and does not push does not
      fail the step (it fails today with `AgentPushed`).
- [x] 1.2 Test: with a bare `origin`, an agent that commits and pushes still fails with `AgentPushed` and the
      unchanged message; the existing with-origin guard tests pass unchanged.
- [x] 1.3 Test: `remote_head` still returns the local branch head with no origin (its other callers, the push
      step and the restack, depend on it).
- [x] 1.4 Skip the guard in the agent wrapper in `pipeline/wiring.py` when `has_origin` is false; leave
      `remote_head` as it is.
- [x] 1.5 Update `docs/architecture.md` where it describes the guard, and add a changelog entry.
