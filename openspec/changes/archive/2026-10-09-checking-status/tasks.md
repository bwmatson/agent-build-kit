# Tasks

Acceptance: none — forge parsing from recorded host answers and display over the unit store; tier-1
tests prove it.

## 1. [agent-build-kit] [tier1] Checks are one list with a status

Done when both forges return the list, the failing and cancelled name lists are gone, and the poller
uses the list.

- [x] 1.1 Test: recorded GitHub check-run answers map to every status in the table, with an unknown
      conclusion pending and a missing conclusion pending.
- [x] 1.2 Test: recorded Azure DevOps statuses (several postings per context, latest wins, not
      applicable omitted) and build-policy evaluations (approved, rejected, broken, a rejected build
      whose result is cancelled, queued, running) map to every status in the table.
- [x] 1.3 Test: the overall result is failed, pending, passed or none as specified, a cancelled-only
      list reads pending, and the failing and cancelled name helpers return what the old lists did.
- [x] 1.4 Test: the poller sends a unit back when a pending check fails, re-runs cancelled checks as
      before, and records a snapshot with the old keys afresh without sending anything back.
- [x] 1.5 Add the check model and status set, the per-host mappings and the helpers; replace the two
      name lists in the poller, the rework paths and both forges.
- [x] 1.6 Update `docs/code-forges.md` for the model and mappings, and add a changelog entry.

## 2. [agent-build-kit] [tier1] The checking status

Needs: dependents-follow-their-parent group 1 merged — both add derived statuses to the same vocabulary module
Needs: unit-size-off-the-graph group 1 merged — both change the node `label` line in `diagram.py`

Done when a unit in review with pending checks reads `checking` and is shown with its pull request link.

- [x] 2.1 Test: a unit in review is `checking` for pending checks and for no checks within the window
      after its last push, and `in_review` for passed checks or no checks after the window; the stored
      state is `in_review` for both.
- [x] 2.2 Test: the status command lists a checking unit with its pull request link and a unit awaiting
      review separately; the graph and the state label show the new name and colour.
- [x] 2.3 Test: the poll that records a pull request's checks changes its state label from `in_review` to `checking` and back as the
      checks go pending and pass, without a change of stored state; `pushed_at` is written with `pushed` and an old store without
      it reads `in_review` for a pull request with no checks.
- [x] 2.4 Test: a checking unit holds a queue place and releases its dependents as one in review does.
- [x] 2.5 Add the derived status with its inputs (the snapshot lookup and `pushed_at`), the label refresh on poll, the
      `limits.checks_register_seconds` setting and its documentation, and the status command (`cmd_status`, beside "awaiting
      review"), graph and label output; decide at each `serve/` consumer (`server.py`, `metrics.py`) which name it shows.
- [x] 2.6 Update `docs/unit-graph.md`, `docs/configuration.md`, the pipeline skill and add a changelog
      entry.
