# Tasks

Acceptance: none — the serializer and the node that holds a unit are driven with a fake runner; tier-1 tests prove it.

Priority: 4

## 1. [agent-build-kit] [tier1] The held state is plain text and the test sees what nodes return

Done when the held state is stored as text and a test fails for any value a node returns that the checkpoint would block.

- [x] 1.1 Test: driving each path that ends in `BuildPath.hold()` with a fake runner stores the held state as text and logs no
      blocked-type warning when read back; a checkpoint holding the enum still loads and routes the unit as before.
- [x] 1.2 Test: every update a node returns and a state with every field populated, run through the real serializer
      with the allowed list, encode no type outside the list; a node that returns an enum off the list makes it fail.
      Extend `populated()` and `reachable()` in `tests/graph/test_checkpoint_allowlist.py` for this: they read the
      field annotations, and `hold_state` is annotated `str`, so the enum slips past them today.
- [x] 1.3 Store the enum's value for `hold_state` in `BuildPath.hold()` (`graph/nodes.py`), and add the test helper that collects node updates.
- [x] 1.4 Document the rule in `docs/architecture.md` and add a changelog entry.
