# Design

## What is wrong

`vocabulary.UNLABELLED` names the states given no label, because the host shows merged and closed itself. `StateLabels.set_state` begins with
`label = state_label(state)` and returns when there is none. The unit store calls `on_state` after every `set_state` (wired in `store_for` in
`cli/pipeline.py`, whose hook calls `StateLabels.follow` and then the draft follower), and `follow` ends in `set_state`, so a unit that goes to
`merged` or `closed` reaches a `set_state` that returns having done nothing. `set_exclusive_label`, the only thing that takes the old label off,
runs only for a state that has one. The module's own rule, "make `state` the one state label", is broken for exactly the unlabelled states.

The counts, over every non-open pull request: in the code repository 109 carry `in-review`, 2 `checking`, 1 `planned` and 1 `running` (113 in
all); in the platform repository 5 carry `in-review`; in the third repository 1 does. The same query, run again after the sweep has finished, is
the check that they are gone: it must return none in all three.

## Group 1: a unit that finishes has its state label taken off

**The rule.** When a unit's stored state becomes one of the finished states (`merged`, `closed`, `satisfied`, `unplanned`) and the unit has a pull
request, the pipeline removes every state label from that pull request: every name in `state_label_names()`, which is ten names (the labelled
states, `checking` and `paused-rework` among them). Change labels (`change_label`) and any label a person added are not in that set and stay. The
finished states are one named set beside `UNLABELLED` in `vocabulary.py`, not a second hand-kept list, so the two cannot drift. `StateLabels.follow`
calls a new `clear_state(repo, pr)` for those states where it now falls through to `set_state`; `set_state` for a labelled state is unchanged. A
unit with no pull request has nothing to carry a label and nothing happens.

**Where the trigger lives.** A merge the poll detects is recorded through `_dispatch(...)("merged", ...)`, which ends in the store's `set_state`,
so it fires `on_state` like every other change; a close, a satisfied outcome and an unplanned unit do the same. The hook is therefore the one place
where every route to a finished state already passes, and no second trigger is added in the poller, the merge recorder or the satisfied-close
retry. A unit re-delivered into the same finished state runs the same removal again, which is harmless (see below).

**Reading what is on the pull request.** Removing all ten names by name costs ten calls per pull request, and the forge protocol has no read of a
pull request's labels. `Forge` gains `labels_on(repo, pr) -> list[str]`:

- GitHub lists the issue's labels (the listing `set_exclusive_label` already makes, `list_labels_on_issue`, paged through `_pages`).
- Azure DevOps reads the labels resource of the pull request (`_labels`, which `set_exclusive_label` already uses), as names.
- The local forge keeps no labels: every label method there is a no-op, so `labels_on` returns an empty list.
- A host without labels raises `NotImplementedError`, as the protocol's label methods are documented to, so `StateLabels._try` says "this host keeps
  no labels" once rather than logging a fault.

`clear_state` reads once, removes with `remove_label` only the state labels that are present (compared as the host does: GitHub and Azure DevOps
match names without regard to case), and counts a label that is already gone as success (`remove_label` returns normally for one on both hosts).
It returns an outcome, a `StrEnum` `ClearOutcome` with `CLEARED` (at least one label removed), `NOTHING_TO_CLEAR` (none present, or a host that
keeps none) and `FAILED` (a read or a removal failed). The state-change hook ignores the result; the sweep below uses it.

`labels_on` takes an entry in `OPERATIONS` in `forges/operations.py` as a `read`, so the retrying wrapper in `forges/resilient.py` applies and the
test that every protocol method is declared stays true; `remove_label` is already declared. A forge test that asserts the table matches the
protocol methods covers the new one.

**The read is not a decision.** The pipeline's rule that nothing is decided by reading a state label back stands: what is removed is decided by
the unit's stored state, and the read only avoids removals that would find nothing. No unit's state, readiness or order is ever inferred from a
label.

**Best effort.** Like every label write: a failure to read or remove is logged once by `_try` ("label: ... failed") and never fails the unit, the
tick or the store write, which has already happened when `on_state` is called. A removal that fails leaves that label on until the sweep of group 2
retries it.

**Existing requirements.** The existing requirement that a state the host already shows gets no label is not contradicted: no label is added. Its
sentence that exactly one state label is present at a time is about open pull requests; the new requirement states the finished case, so the
existing requirement is not modified.

## Group 2: the pull requests that are already stale are cleaned once, by the pipeline itself

**No command, no store field.** A temporary command would outlive its purpose, and a new field in the unit store would be refused by an older
release reading the file. The tick heals instead.

**The sweep.** A step of `run_round`, after the poll and the other housekeeping (`_step("closing satisfied pull requests", ...)`) and before it
returns the units to start, so it never delays a build and a failure in it is only logged (`_step` contains it). For each unit whose state is a
finished one and that has a pull request not yet recorded as swept, it calls `clear_state` and, unless the outcome is `FAILED`, records the pull
request. The record is `labels-swept.json` in the state directory, `{repo: [pr, ...]}` keyed by the repo name the unit carries. It is a
machine-local file: it is read and written under `file_lock` (a `labels-swept.json.lock` beside it, as the other machine-local records do) and
replaced atomically by writing a `.tmp` file and renaming it over, as the unit store writes `units.json`. A file that is missing or unreadable
is an empty record, so deleting it is harmless: it costs one more pass, which finds the pull requests clean and records them again without a
removal.

**Bounded.** At most `limits.label_sweep_per_tick` pull requests are handled per tick (default 20, at least 1), so the first ticks after the change
do not spend the code host's rate limit on about 120 pull requests at once. A unit has no finish time recorded, so "oldest first" is the lowest
pull request number first within each repo, repos in the order the installation lists them. A line in the log says how many remain. A pull request
whose clear failed is not recorded and is picked up again on a later tick.

**Reaches every repo** the installation lists, each through its own forge (`Installation.forge_of`). A repo whose host keeps no labels gives
`NOTHING_TO_CLEAR` (via the once-only message from `_try`), so its pull requests are recorded and are not visited again.

**Expected effect (the verification fixture).** About 113 pull requests in the code repository, 5 in the platform repository and 1 in the third
lose a state label, over roughly 7 ticks at 20 per tick; 109 + 5 + 1 of them were `in-review`, and the other 4 in the code repository were
`checking` (2), `planned` (1) and `running` (1). The builder and a person confirm it with the same count of non-open pull requests that carry a
state label, which must be zero when the sweep has finished.

**A pull request that is reopened.** A closed unit whose pull request is reopened changes state through the store like any other change, so the
state label of its new state is set by `set_state` and group 1's rule applies on the next finish; a stale `labels-swept.json` record does not
matter because the sweep only visits units that are in a finished state.

## Documents

`docs/architecture.md` (the labels paragraph: finished states are cleared, and the sweep), `docs/code-forges.md` (the forge-operations table gains
`labels_on`; the note that a host without labels raises `NotImplementedError` now covers four methods), `docs/configuration.md` (the
`limits.label_sweep_per_tick` setting) and the changelog.
