# Tasks

Acceptance: none — scheduling and display behaviour over the unit store and a fake host; tier-1 tests
prove it.

## 1. [agent-build-kit] [tier1] Display statuses and drafts that follow planned

Done when a running unit reads as building, reworking or rebasing, and a planned unit's pull request is
a draft.

- [x] 1.1 Test: a running unit reads `rebasing` for a conflict feedback source or the base changed,
      restack conflict and restack deferred causes, `reworking` for review and check feedback, and
      `running` otherwise; the stored state is `running` in all three.
- [x] 1.2 Test: status, the graph and the state label show the derived name and colour.
- [x] 1.3 Test: a unit going to planned with an open pull request makes it a draft, a unit in review
      publishes it, and a host without drafts or a failed call is logged and the state still changes.
- [x] 1.4 Add the derived statuses to the vocabulary and show them; extend the draft follower for
      planned.
- [x] 1.5 Update `docs/unit-graph.md`, the pipeline skill and `docs/architecture.md`, and add a
      changelog entry.

## 2. [agent-build-kit] [tier1] An in-review unit follows its predecessor

Done when a unit in review goes back to planned when its predecessor's branch is changing and returns
when the predecessor is back.

- [x] 2.1 Test: with a predecessor that has a commit beyond its pushed head, is rebasing, or failed or
      held with such a commit, the dependent in review is set to `planned` with the cause
      `upstream_went_back` and a note naming the predecessor; approval, branch, pull request and
      thread are kept.
- [x] 2.2 Test: a predecessor reworking with an unchanged head, or failed or held with an unchanged
      head, leaves the dependent in review.
- [x] 2.3 Test: a chain of dependents moves in one pass; a merged or satisfied predecessor, a
      cross-repo predecessor, a deferred restack and a busy branch claim do nothing or defer.
- [x] 2.4 Test: when the predecessor is back in review on a new head the dependent is released, restacks
      and keeps its approval if the restack is clean, and restacks nothing when the head is unchanged.
- [x] 2.5 Write the predicate with an injectable head reader beside the build-time check, run the pass
      after the poll and refresh in the tick and each round, and log once per unit and predecessor.
- [x] 2.6 Update `docs/architecture.md`, `docs/unit-graph.md` and the pipeline skill, and add a
      changelog entry.

## 3. [agent-build-kit] [tier1] The parked unit's thread and the readers of the derived names

Done when a dependent parked by its predecessor keeps its place in the graph run, and the chat, the
server and the metrics read the stored state, not the derived name.

- [x] 3.1 Test: parking a unit in review is a new event kind that sets `planned` with the cause
      `upstream_went_back`, keeps approval, branch, pull request and thread, and leaves the thread
      waiting at `await_review`; no other event kind sets `planned`.
- [x] 3.2 Test: the pass runs in `run_round` after `_refresh`, beside `gate_sent_back` and
      `release_gated`, and the check sits beside `build_upstream_incomplete`.
- [x] 3.3 Test: the chat's running check is true for a stored `running` unit that reads `reworking` or
      `rebasing`; the server's unit summary keeps the stored state in `state` and carries the derived name
      beside it; the `abk.units` gauge has one series per stored state.
- [x] 3.4 Add the event kind to `EventKind` and its handler in `on_event`, move the pass to `run_round`
      as above, and ask the stored state at `serve/chat.py` (`running`), `serve/server.py` (`summary`) and
      `serve/metrics.py` (`_unit_series`).
- [x] 3.5 Update `docs/architecture.md`, `docs/unit-graph.md` and the pipeline skill for the event and the
      readers, and add a changelog entry.
