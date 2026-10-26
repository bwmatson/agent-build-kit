# Tasks

Acceptance: none — labels are cosmetic by construction and read back by nothing;
what proves it is tier-1 tests over the forge's label calls, the shared vocabulary
and the poller's handling of its own labels.

## 1. [agent-build-kit] [tier1] A unit's state, on its pull request, in the graph's words

Done when a pull request carries exactly one state label that follows its unit and
matches the graph in name and colour, a rework instruction is consumed when acted
on, a hold is not, and no label failure can cost a unit.

- [x] 1.1 Test: as a unit goes from building to review to rework to held, its pull
      request carries exactly one state label at each point and the previous one is
      removed; merging or closing adds none.
- [x] 1.2 Test: every state the graph can draw has a label of the same name and the
      same colour as the graph's outline for that state, or is on the documented
      list of states deliberately left unlabelled — so adding a state cannot leave
      the two surfaces disagreeing. The states derived from history (waiting on a
      dependency, stopped before a rework, stopped for a spent usage window) each
      get their own label rather than sharing one.
- [x] 1.3 Test: a label the pipeline writes triggers no dispatch, and a label a
      person writes still does.
- [x] 1.4 Test: dispatching a rework asked for by label removes that label; adding
      it again dispatches again; a hold label is left in place.
- [x] 1.5 Test: a missing label is created once with its description; a failure to
      create, set or remove is logged once and changes nothing about the unit's
      state or progress; no decision path reads a state label.
- [x] 1.6 Move the state names and the palette out of the diagram into one
      vocabulary both it and the labels read — the derived states included — with
      each state's outline colour, fill and text colour in one place, and the
      diagram rendering from it unchanged.
- [x] 1.7 Add label writes to the forge behind its interface — create if missing,
      set exclusively within the state family, remove — and the change's own label,
      stable for the life of the pull request.
- [x] 1.8 Set the state label where a unit's state changes, and consume the rework
      label where that dispatch happens.
- [x] 1.9 Document both label families in `docs/architecture.md` and the
      `abk-pipeline` skill: which a person sets, which the pipeline maintains, that
      a rework label is consumed while a hold is not, that the names and colours are
      the graph's, and that the store is the source of truth either way.
