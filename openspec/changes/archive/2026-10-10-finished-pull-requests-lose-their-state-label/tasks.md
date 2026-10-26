# Tasks

Acceptance: none — label calls are driven with fake forges and the tick's round with a fake store; tier-1 tests prove every case.

Priority: 3

## 1. [agent-build-kit] [tier1] A unit that finishes has its state label taken off

Done when a unit that merges, is closed, is satisfied or is unplanned has no state label left on its pull request, and nothing else on it changed.

- [x] 1.1 Test: `follow` for a unit that becomes `merged` removes `in-review` from its pull request; one that becomes `closed` loses its state
      label whichever it was (`checking`, `running`, `held`); a `satisfied` or `unplanned` unit that has a pull request is cleared; a unit with no
      pull request makes no forge call.
- [x] 1.2 Test: the change labels and a label a person added stay; only the names in `state_label_names()` are removed, and only those the
      pull request carries (one `labels_on` read, no removal of an absent label); a state label that is already gone is success and the outcome is
      `NOTHING_TO_CLEAR`.
- [x] 1.3 Test: a host that raises `NotImplementedError` from `labels_on` is not a fault and is said once; a failed read or removal is logged
      once, the outcome is `FAILED`, and the unit's stored state is still the finished one; a merge delivered twice removes nothing the second
      time and raises nothing; `set_state` for a labelled state is unchanged.
- [x] 1.4 Test: `labels_on` on the GitHub forge returns the names from the issue's labels, on the Azure DevOps forge the names from the pull
      request's labels resource, on the local forge an empty list; the forge operations table declares it and the retrying wrapper repeats it on a
      transient failure.
- [x] 1.5 Add `labels_on` to the `Forge` protocol with the GitHub, Azure DevOps and local implementations and its `OPERATIONS` entry; add the
      finished-states set beside `UNLABELLED`, the `ClearOutcome` `StrEnum` and `StateLabels.clear_state`, and call it from `follow` for those
      states.
- [x] 1.6 Update `docs/architecture.md` (the labels paragraph) and `docs/code-forges.md` (the forge-operations table and the note on hosts
      without labels), and add a changelog entry.

## 2. [agent-build-kit] [tier1] Pull requests that already carry a stale state label are cleaned once

Done when every finished unit's pull request has been cleared within a few ticks and recorded, with no command, no new unit field and no delay to a build.

- [x] 2.1 Test: a merged unit's pull request still labelled `in-review` is cleared and recorded in `labels-swept.json`; an already clean pull
      request is recorded without a removal; a pull request recorded as swept is not visited again; units that are not finished are never
      visited.
- [x] 2.2 Test: at most `limits.label_sweep_per_tick` pull requests are handled in a tick, lowest number first within each repo, the log says how
      many remain, and the remainder is handled on the next tick; a failed clear is not recorded and is tried again.
- [x] 2.3 Test: the swept file is read and written under the file lock and replaced atomically; a missing or unreadable file reads as empty and a
      deleted one costs a pass and nothing else; a repo whose host keeps no labels is recorded and visited no more; a failure in the sweep does not
      stop the rest of the round or delay a build.
- [x] 2.4 Add the sweep as a step of `run_round` after the poll, the swept record with its lock, and the `limits.label_sweep_per_tick` setting
      (default 20, at least 1).
- [x] 2.5 Update `docs/configuration.md` and `docs/architecture.md` (the labels paragraph and the round's steps), and add a changelog entry.
