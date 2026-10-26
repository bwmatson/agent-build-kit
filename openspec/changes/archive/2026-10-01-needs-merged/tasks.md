# Tasks

Acceptance: none — this is a planning and scheduling rule inside the pipeline,
with no surface a consumer drives; tier-1 tests over the grammar, the plan, the
readiness rules and the graph page prove it.

## 1. [agent-build-kit] [tier1] A dependency that must merge first

Done when `Needs: <change> group <n> merged — <reason>` makes the dependent wait
for the merge in the same repo as across repos, the plan records which
dependencies are merge-gated, the graph page draws them distinctly, and every
existing `Needs:` line means what it did.

- [x] 1.1 Test: `Needs: c group 2 merged — why` parses with the qualifier and
      the reason; `Needs: c group 2 — merged later` does not take the qualifier;
      a qualified line naming its own change is reported by `abk tags`.
- [x] 1.2 Test: re-planning a change whose group carries a qualified `Needs:`
      records the dependency in both `depends_on` and `merge_before`, and a
      stored unit without `merge_before` loads unchanged.
- [x] 1.3 Test: a same-repo merge-gated dependency in `planned`, `running`,
      `in_review` or `held` keeps the dependent waiting; once it is `merged`, or
      `satisfied` with its work landed, the dependent is ready and its base is
      the trunk. The unqualified same-repo case still lets the dependent start
      on a dependency in review.
- [x] 1.4 Test: the graph page draws a merge-gated edge as `==>|merged|` and
      shows the waiting dependent as blocked; the legend explains it.
- [x] 1.5 Parse the qualifier, record `merge_before`, apply it in `waiting_on`,
      and draw it.
- [x] 1.6 Document it in the `abk-authoring` skill and `docs/architecture.md`,
      and add merge-gated dependencies to `docs/unit-graph.md`'s table of what
      stays outside the graph.
