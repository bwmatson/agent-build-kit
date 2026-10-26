# Tasks

Acceptance: none — the only hosts that merge are real ones, and a scripted run against one would merge real code that cannot be unmerged; each behaviour is proved by a unit-test instead, through the real GitHub and Azure DevOps adapters against their HTTP fakes and the stand-in forge, end to end through the landing step, the merge record and the poller, over temporary state directories and temporary git repositories, and the doctor warning comes before any class can be enabled.

Priority: 1

## 1. [agent-build-kit] [unit-test] The policy names what may land, audit and demote

Done when the `review` section accepts `auto_land.classes`, `audit.sample_rate` and `demotion.window` and `min_agreement` with the defaults and ranges the spec names, an unknown class or an out-of-range value fails loading naming the key, and an empty list is the off switch. Estimate: about 270 changed lines.

Needs: units-are-triaged-by-review-tier group 12 — auto-land reads the calibrated history, the outcomes, the forge's read of a merge commit and the tier ordering

- [x] 1.1 Test: in `tests/config/test_review_auto_land_config.py`, a workspace with none of the keys loads with no class listed, a sample rate of 0.1, a window of 30 and a minimum agreement of 0.9; each key loads when set; a class that `review.classes` does not name, a rate of 2 or -0.1, a window of 0 and an unknown key each fail naming the key; a repo's `review` block still accepts only `protected_paths`.
- [x] 1.2 Add the three groups of keys to the `review` section in `config.py` with their validation, and document the keys in `docs/configuration.md`, the `abk-config` skill and the `abk init` template. (First part of the old task: the keys; the doctor warnings are in the next group.)

## 2. [agent-build-kit] [unit-test] `abk doctor` warns about the guard when a class may land

Done when `abk doctor` warns for each repo with no branch protection when the list is not empty and when review is disabled with the list set, and reports the guard as information when the list is empty. Estimate: about 230 changed lines.

- [x] 2.1 Test: in `tests/cli/test_doctor_auto_land_guard.py`, with a class listed and a stand-in forge reporting no branch protection `abk doctor` warns for that repo and says the policy hook is then the only guard; with protection there is no warning; with the list empty the guard is information as before; with the list set and `review.enabled` false there is a warning that it has no effect; each repo is reported on its own.
- [x] 2.2 Add the guard warning and the ineffective-list warning to the merge-guard check in `cli/doctor.py`. (Second part of the old task: the warnings.)

## 3. [agent-build-kit] [unit-test] A forge can squash-merge a pull request at a given head, on GitHub

Done when the forge protocol has a merge operation that squash-merges at an expected head and returns the merge commit, a refusal carries the host's reason, a forge declares whether it merges (not unless it says so), GitHub squashes with the head as a guard, the operation is retried only after the commit read shows the merge did not happen, the stand-in forge can answer or refuse it, and the agent's deny lists are the same as before. Estimate: about 400 changed lines.

- [x] 3.1 Test: in `tests/forges/test_forge_operations.py`, the merge operation has an entry that declares it a create whose landing read is the read of the commit a merged pull request produced, and the check that every protocol method has an entry still passes.
- [x] 3.2 Test: in `tests/forges/test_merge_retry.py`, with a stand-in forge that fails once after merging the call returns the commit the read finds and merges nothing again; one that fails before doing anything is tried again; a refusal is raised on the first call and never repeated; a host that stays unavailable raises the same error the other creates raise.
- [x] 3.3 Test: in `tests/forges/test_github_merge.py`, against the GitHub host fake the request names the squash method and the approved head, a merge returns the merge commit, an answer that the head has moved, that the pull request is not mergeable or that a rule blocks it each raise a refusal carrying the message, a closed pull request raises a refusal, and any other failure is the ordinary transport failure.
- [x] 3.4 Add the merge operation, its refusal and the declaration of whether a forge merges (false unless a forge says so) to `forges/base.py`, its entry to `forges/operations.py`, the GitHub implementation to `forges/github.py`, and an answer or refusal the test can set to `tests/forges/stand_in.py`. (First part of the old task; the local forge's refusal is in the next group.)

## 4. [agent-build-kit] [unit-test] The local forge refuses a merge and the merge denial is unchanged

Done when the local forge declares that it does not merge and its merge operation raises a refusal saying a merge is a person's, with the repository unchanged, and the policy hook's, command policy's, forges' and runtime's deny lists are what they were before this change. Estimate: about 200 changed lines.

- [x] 4.1 Test: in `tests/forges/test_local_merge.py`, the local forge declares that it does not merge and its merge operation raises a refusal saying a merge is a person's, with the repository unchanged.
- [x] 4.2 Test: in `tests/hooks/test_policy_merge_denial_unchanged.py`, the policy hook's deny list, the command policy's list, each forge's denied commands and requests and the runtime's disallowed tools equal what they were before this change, and a source search finds no caller of the merge operation outside the landing step and the forges' tests.
- [x] 4.3 Add the refusal to `forges/local.py`. (Second part of the old task.)

## 5. [agent-build-kit] [unit-test] Azure DevOps completes a pull request by squash

Done when the Azure DevOps forge completes a pull request with the squash strategy and the approved head as the last merge source commit and returns the commit of the completed merge, a host that refuses or leaves the pull request active raises a refusal carrying the reason, and the forge declares that it merges. Estimate: about 400 changed lines.

- [x] 5.1 Test: in `tests/forges/test_azure_merge.py`, against the Azure DevOps REST fake the request completes the pull request with the squash strategy and the approved head, a completed answer returns the merge commit, a pull request left active with a reason raises a refusal carrying it, an abandoned or already completed pull request raises a refusal, a head that moved raises a refusal, and a transient failure is retried only after the commit read shows the merge did not happen.
- [x] 5.2 Test: in `tests/forges/test_azure_rest_parity.py`, the Azure forge's merge operation takes the same arguments and raises the same refusal as GitHub's, and the forge declares that it merges.
- [x] 5.3 Add the completion call to `forges/azure_devops.py` with its response model in `forges/azure_models.py`, and describe the merge operation in `docs/code-forges.md` for each forge.

## 6. [agent-build-kit] [unit-test] A unit can be recorded merged with the cause `auto_landed`, once

Done when a unit can be recorded `merged` with a new cause `auto_landed` through the path a person's merge takes, restack and cleanup run unchanged, and an event for a unit already recorded merged changes nothing. Estimate: about 330 changed lines.

- [x] 6.1 Test: in `tests/pipeline/test_events_auto_landed.py`, recording a unit merged with the cause `auto_landed` sets its state and cause, restacks and retargets its children as a person's merge does, removes its worktree and branch, and releases a child held for depth, all with the same results as a recorded merge by a person.
- [x] 6.2 Test: in `tests/pipeline/test_events_merge_idempotent.py`, a merged event for a unit already `merged` adds no history entry, restacks and cleans nothing a second time and returns true, whichever of the landing and the poller recorded it first; a merged event for a unit being built still reports itself deferred as before.
- [x] 6.3 Add `auto_landed` to the causes in `pipeline/unit_store.py` and let the merge record in `pipeline/events.py` take the cause and return at once for a unit already recorded merged. (First part of the old task; the intent record is in the next group.)

## 7. [agent-build-kit] [unit-test] An intent record names a landing in progress

Done when an intent record names a landing in progress and makes a later merged event for that pull request carry the cause `auto_landed`, and a failed intent write stops the landing before any merge. Estimate: about 230 changed lines.

- [x] 7.1 Test: in `tests/pipeline/test_landing_intent.py`, an intent is written before a merge and removed once the merge is recorded, a merged event for a pull request with an intent is recorded with the cause `auto_landed`, an intent for another pull request or repo is ignored, an intent that cannot be written stops the landing with the reason recorded, and the file is replaced atomically and listed with the other state files in `docs/architecture.md`.
- [x] 7.2 Add the intent record to a new module under `pipeline/` read by `on_merged` when it chooses the cause. (Second part of the old task.)

## 8. [agent-build-kit] [unit-test] The landing decision names the conditions a unit must meet

Done when a function says for a unit either that it may land or why it may not, from the unit, its recorded verdict, the policy, the demotions, its forge and its pull request, by every condition the spec names except the checks, giving the same answer for the same facts; the checks are taken as given until the next group. Estimate: about 320 changed lines.

- [x] 8.1 Test: in `tests/pipeline/test_landing_conditions.py`, a table of units each missing one condition (review disabled, not in review, feedback pending, held, tier not `auto`, class not listed, class demoted, a forge that does not merge, a draft, a known conflict, a hold label, a request for changes, a head that is not the approved commit, an unmerged parent) is declined naming that condition and the unit with every condition holding may land; an empty list declines every unit; the reasons are words a person can read.
- [x] 8.2 Test: in `tests/pipeline/test_landing_policy_now.py`, a unit approved while its class was listed is declined once the class is removed from the list, a class listed after approval lands the unit on the next pass, and a unit with no recorded verdict is declined as having none.
- [x] 8.3 Add the decision to a new module under `pipeline/` taking only plain facts and reading no state itself. (First part of the old task; the checks are in the next group.)

## 9. [agent-build-kit] [unit-test] The landing decision reads the checks as evidence

Done when the decision treats no checks as no evidence, pending checks as waiting and a failed check as left to rework, and never depends on the host naming a check as required. Estimate: about 150 changed lines.

- [x] 9.1 Test: in `tests/pipeline/test_landing_checks.py`, three passed checks may land; one failed does not and is left to rework; a pending or cancelled one waits and the unit is not declined for good; no check registered declines with a reason saying there is no evidence; the answer never depends on the host naming a check as required.
- [x] 9.2 Add the checks, read through the forge's list of pull requests by the caller and passed in, to the decision. (Second part of the old task.)

## 10. [agent-build-kit] [unit-test] The pipeline lands a unit and records it

Done when a pipeline pass lands each unit the decision allows by writing an intent, calling the forge's merge at the approved head, recording the unit merged with the cause `auto_landed` and removing the intent, and a refusal leaves the unit in review with the reason recorded. Estimate: about 360 changed lines.

- [x] 10.1 Test: in `tests/pipeline/test_landing_execution.py`, with the stand-in forge a unit that may land is merged once at its approved head, recorded `merged` with cause `auto_landed`, its intent removed and its children restacked; a refusal leaves it in review with the refusal's reason recorded and its intent removed; a second pass over the landed unit merges nothing; a pull request already merged by a person is recorded and not merged again.
- [x] 10.2 Test: in `tests/cli/test_tick_landing.py`, a pass with review enabled and a class listed runs the landing step after the poll, a pass with the list empty or review disabled never calls the forge's merge, and an error landing one unit is logged and the others are still tried.
- [x] 10.3 Add the landing pass to `cli/pipeline.py` running the decision, the intent, the forge merge and the merge record in that order inside a guard that logs and swallows any error per unit, and a note in `docs/architecture.md` and `docs/code-forges.md` that the `acp` runtime ignores the deny lists so only the server-side guard stands. (First part of the old task; the comment, label and status are in the next group.)

## 11. [agent-build-kit] [unit-test] A landing says so on the pull request, shows in `abk status`, and is proved through GitHub

Done when a landing comments on the pull request and labels it, `abk status` shows why a unit did not land, and the landing is proved end to end through the GitHub adapter and the poller. Estimate: about 340 changed lines.

- [x] 11.1 Test: in `tests/pipeline/test_landing_comment.py`, a landing comments on the pull request with the class and the verdict's reason and adds the label `auto-landed`, a failing comment or label is logged and leaves the record as it was, and a unit that did not land gets neither.
- [x] 11.2 Test: in `tests/pipeline/test_landing_through_github_host.py`, against the GitHub host fake and the poller a unit of a listed class with green checks lands with a squash request at its approved head, the poller's later merged event for the pull request changes nothing, a stacked child of the landed unit is retargeted and restacked, and verify and archive treat the change as merged; with no checks registered nothing is sent to the merge route.
- [x] 11.3 Test: in `tests/cli/test_status_landing.py`, `abk status` shows for each unit in review that was declined the reason in words, shows nothing for a unit that is waiting only on pending checks beyond that it is waiting, and shows nothing for a unit the landing step is not concerned with.
- [x] 11.4 Add the comment and the label to the landing pass, a label for `auto-landed` to `pipeline/vocabulary.py`, and the declined reasons to `abk status`. (Second part of the old task.)

## 12. [agent-build-kit] [unit-test] A digest card says what landed, and an auto unit that will not land is not hidden

Done when one digest card lists the units that auto-landed in the last 24 hours and is shown once without a reminder and cleared when none remain, no card is raised per landed unit, an `auto` unit in review raises a review card unless the landing step will land it, and a unit waiting only on pending checks raises none. Estimate: about 420 changed lines.

- [x] 12.1 Test: in `tests/notify/test_cards_digest.py`, two units landed this morning give one digest card listing both with their classes and a link each and no other card for either, a landing a day and an hour old is not listed, no landing in the window gives no card, and the card's id changes with the date of the newest landing in the window.
- [x] 12.2 Test: in `tests/notify/test_reconcile_digest.py`, a digest card is shown once, is not shown again when the reminder interval passes, is cleared when the window empties, and a review card still reminds as before.
- [x] 12.3 Test: in `tests/notify/test_cards_auto_unit.py`, an `auto` unit in review whose class is not listed, whose class is demoted, whose forge does not merge or which was declined for having no checks has a review card; one of a listed class waiting for pending checks has none; a `light` or `full` unit and a unit with no verdict are as before.
- [x] 12.4 Add the digest card kind and a no-reminder flag on a card to `notify/provider.py`, `notify/cards.py` and `notify/reconcile.py`, read what landed from the landing record, and change the rule for `auto` units to depend on whether the landing step will land them.

## 13. [agent-build-kit] [unit-test] A sampled share of landed units is recorded as awaiting audit

Done when a landed unit is picked for audit by a deterministic share of `audit.sample_rate`, a picked unit is recorded awaiting audit, a result can be recorded, a unit not awaiting audit is refused, and an auto-landed unit enters the rates only when audited or reverted. Estimate: about 380 changed lines.

- [x] 13.1 Test: in `tests/pipeline/test_audit_sampling.py`, a rate of 0 picks no unit and 1 picks every one, the same unit id, landed commit and rate always give the same answer, and over a fixed set of a thousand ids a rate of 0.1 picks between 8 and 12 percent.
- [x] 13.2 Test: in `tests/pipeline/test_audit_record.py`, landing a picked unit records it awaiting audit with its class and the time, a result replaces the waiting record with the result and the time, a result for a unit not awaiting audit is refused, and the file is replaced atomically and listed with the state files.
- [x] 13.3 Test: in `tests/pipeline/test_review_rates_auto_landed.py`, an auto-landed unit never audited or reverted is no sample, one audited `ok` is one accepted sample, one audited `wrong` is one sample not accepted and not clean, one reverted is one sample not accepted and not clean, and a unit a person merged is counted as before.
- [x] 13.4 Add the sampling to a module under `pipeline/` and call it where a landing is recorded, the audit record beside the landing record, and the rule for auto-landed units to the rates. (First part of the old task; the command, card and status are in the next group.)

## 14. [agent-build-kit] [unit-test] `abk review audit` records a result, and an audit waiting has a card

Done when a picked unit raises an audit card, `abk review audit <unit> ok|wrong` records the result and clears the card, a unit not awaiting audit is refused, and `abk status` lists audits waiting. Estimate: about 300 changed lines.

- [x] 14.1 Test: in `tests/cli/test_review_audit.py`, `abk review audit <unit> ok` and `wrong` record the result and report it, an unknown unit or one not awaiting audit is refused with a message and a non-zero exit, and the command changes nothing else.
- [x] 14.2 Test: in `tests/notify/test_cards_audit.py`, a unit awaiting audit has an audit card with a link to its pull request, the card is cleared once the result is recorded, and `abk status` lists each audit waiting with its unit and class.
- [x] 14.3 Add the `review audit` subcommand to the review command module under `cli/`, the audit card kind to `notify/`, and the status lines to `cmd_status`. (Second part of the old task.)

## 15. [agent-build-kit] [unit-test] A demotion is recorded, holds a class at light, and is not landed

Done when a demotion is recorded in `runs/` with its class, trigger, unit and time and never in abk.yaml, a later trigger is added to the existing demotion, the verdict holds a demoted class at `light` as one more floor, and the landing step does not land a demoted class. Estimate: about 380 changed lines.

- [x] 15.1 Test: in `tests/pipeline/test_demotion_record.py`, demoting a class writes one record with the class, trigger, unit and time, a second trigger on a demoted class is added to the same record and logged, lifting marks it lifted with the time and a new trigger afterwards makes a new demotion, abk.yaml is byte for byte unchanged, and the file is replaced atomically and listed with the state files.
- [x] 15.2 Test: in `tests/pipeline/test_verdict_demotion_floor.py`, a class that clears every other floor and is demoted gives `light` with a reason naming the demotion, the floor never lowers a higher tier, a verdict computed after a lift is not held, and the verdict function itself reads no file, taking the demoted classes as an input.
- [x] 15.3 Test: in `tests/pipeline/test_landing_demoted.py`, an `auto` unit approved before its class was demoted is declined by the landing step, and lands again only after a lift.
- [x] 15.4 Add the demotion record to a module under `pipeline/`, the input and floor to `pipeline/verdict.py` and its recording caller, and the check to the landing decision. (First part of the old task; the command, card and status are in the next group.)

## 16. [agent-build-kit] [unit-test] `abk review reinstate` lifts a demotion, which is carded and listed

Done when `abk review reinstate <class>` is the only way to lift a demotion, every demotion and lift is logged and carded, and `abk status` lists demoted classes. Estimate: about 270 changed lines.

- [x] 16.1 Test: in `tests/cli/test_review_reinstate.py`, `abk review reinstate <class>` lifts the demotion, logs it and reports it, is refused for a class that is not demoted, never lifts by itself with time or results, and edits nothing else.
- [x] 16.2 Test: in `tests/notify/test_cards_demotion.py`, a standing demotion has a card until it is lifted, a lift shows a notice once for 24 hours with no reminder, and `abk status` lists each demoted class with its trigger, the unit and since when.
- [x] 16.3 Add the `review reinstate` subcommand to the review command module, the demotion card kind to `notify/`, and the status lines to `cmd_status`. (Second part of the old task.)

## 17. [agent-build-kit] [unit-test] A revert or low agreement demotes the class

Done when the pipeline demotes a class on a revert of an auto-landed unit and on agreement below `demotion.min_agreement` over the most recent `demotion.window` samples with the minimum sample count, and demotes nothing for a revert of a unit a person merged or a class with too few samples. Estimate: about 340 changed lines.

- [x] 17.1 Test: in `tests/pipeline/test_demotion_revert.py`, an auto-landed unit whose outcome becomes `reverted` demotes its class with the trigger `revert` and the unit named, a reverted unit a person merged demotes nothing, and evaluating again once demoted adds no second demotion.
- [x] 17.2 Test: in `tests/pipeline/test_demotion_agreement.py`, with a window of 10 and a minimum of 0.9 eight accepted of the last ten demotes with the trigger `agreement`, nine of ten does not, three samples none accepted does not with the default minimum sample count, records without the brief are not counted, and only the most recent ten samples are considered.
- [x] 17.3 Test: in `tests/cli/test_tick_demotions.py`, a pass evaluates the demotions after the outcome sweep, with review disabled evaluates none, and an error evaluating one class is logged and the others are still evaluated.
- [x] 17.4 Add the revert and agreement triggers to a module beside the demotion record, and call them after the outcome sweep in the pipeline pass, inside a guard that logs and swallows any error. (First part of the old task; the verify and audit triggers are in the next group.)

## 18. [agent-build-kit] [unit-test] A failed verify or a failed audit demotes the class

Done when the pipeline demotes a class on a failed verify of a change holding an auto-landed unit and on an audit recorded `wrong`, and demotes nothing for a passing verify, a passing audit or a change with no auto-landed unit. Estimate: about 190 changed lines.

- [x] 18.1 Test: in `tests/pipeline/test_demotion_verify.py`, a failed verify for a change with an auto-landed unit of class `docs` and a unit a person merged demotes `docs` only, a change with no auto-landed unit demotes nothing, a passing verify demotes nothing, and verify's own recording and retry rules are unchanged.
- [x] 18.2 Test: in `tests/pipeline/test_demotion_audit.py`, an audit recorded `wrong` demotes the unit's class with the trigger `audit` and `ok` demotes nothing.
- [x] 18.3 Add the verify and audit triggers beside the others, the verify trigger where a failed verification is recorded in `pipeline/verify.py` and the audit trigger where a result is recorded, each inside a guard that logs and swallows any error. (Second part of the old task.)
