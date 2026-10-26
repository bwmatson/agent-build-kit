# Tasks

Acceptance: none — a planning rule inside the pipeline; tier-1 tests over the
grammar, the plan and the graph page prove it.

## 1. [agent-build-kit] [tier1] Groups that do not wait for the ones before them

Done when `Independent: <reason>` on a group makes its unit ready without its
predecessor, the chain closes around it, and a change without the line plans
exactly as it did.

- [x] 1.1 Test: `Independent: why` parses with its reason; the line with no
      reason, on group 1, or beside `[contract]`, `[narrow]` or `[acceptance]`
      is reported by `abk tags`.
- [x] 1.2 Test: a change of groups `[a] [a] [b, independent]` plans the third
      unit with no dependency and the second depending on the first.
- [x] 1.3 Test: `[a] [b, independent] [a]` plans the third unit depending on
      the first, and an `[acceptance]` group after them depends on all three.
- [x] 1.4 Test: an independent group is never joined into the unit before it,
      and a small group after it is not joined into its unit; a change with no
      declaration plans identically to before.
- [x] 1.5 Test: the graph page draws an independent unit with no edge from its
      predecessor.
- [x] 1.6 Parse the line, record the flag, plan with a separate chain tail,
      validate in `abk tags`, and draw it.
- [x] 1.7 Document it in the `abk-authoring` skill and `docs/architecture.md`,
      and add a changelog entry.
