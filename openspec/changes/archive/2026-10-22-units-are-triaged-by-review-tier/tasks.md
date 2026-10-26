# Tasks

Acceptance: none — every behaviour here is a label, an ordering, a card, an answer from a route, a forge read, a derivation over stored history and a temporary git repository, and a report over stored records, each proved by a unit-test over fake units, a stand-in forge, temporary repositories and temporary state directories; nothing a consumer drives is built beyond what those tests drive, and nothing here merges or decides a state.

Priority: 1

## 1. [agent-build-kit] [unit-test] The pull request carries a label for its review tier

Done when, with review enabled, a unit with a pull request and a recorded verdict has exactly one of three hyphenated review-tier labels on it on both forges, a new verdict swaps it, a host with no labels or a failing call is logged and never raises, and clearing a finished unit's state labels leaves the review labels alone. Estimate: about 450 changed lines.

Needs: reviewers-are-told-where-to-look group 6 — calibration starts only once the new git descriptions exist, so the brief and its flag land first

- [x] 1.1 Test: in `tests/pipeline/test_vocabulary_review_labels.py`, the vocabulary has one label for each of the three tiers with a name made of lower-case words joined by hyphens, a description and a colour, the review labels are a family of their own, and no review label is in the state labels' names nor any state label in the review family.
- [x] 1.2 Test: in `tests/pipeline/test_review_tier_labels.py`, with a stand-in forge, a unit with a recorded `light` verdict gets the `light` label exclusively, a later `full` verdict replaces it, a unit with no verdict or no pull request gets none, a forge that keeps no labels produces one log line and no error, a failing label call is logged and not raised, and clearing a merged unit's state labels leaves the review label on it; with review disabled no label is written.
- [x] 1.3 Test: in `tests/forges/test_review_tier_labels_hosts.py`, against the GitHub host fake and the Azure DevOps fake each review label is created and set exclusively through the forge's own label calls, the name reaches the host unchanged, and replacing one leaves the other review labels off the pull request.
- [x] 1.4 Add the review-tier family to `pipeline/vocabulary.py`, a method on `StateLabels` in `pipeline/labels.py` that sets the unit's review label with the same containment as the state labels, and call it where a unit's labels are brought in line once a verdict is recorded.

## 2. [agent-build-kit] [unit-test] The queue is ordered by tier

Done when `abk status` lists units in review with the tier first-ranked highest and shows each one's tier, a unit with an `auto` verdict is listed as awaiting review, and ordering never changes which unit the pipeline works on next. Estimate: about 250 changed lines.

- [x] 2.1 Test: in `tests/pipeline/test_review_order.py`, units in review sort `full`, then `light`, then no verdict, then `auto`, stable within a rank by arrival order; units not in review are untouched; the same input always gives the same order.
- [x] 2.2 Test: in `tests/cli/test_status_review_order.py`, with a store of units in review of mixed tiers `abk status` prints them in that order each with its tier, a unit with no verdict prints as it does today, a unit with an `auto` verdict prints as awaiting review, and with review disabled the output is what it was before this change.
- [x] 2.3 Test: in `tests/pipeline/test_scheduling_ignores_review_tier.py`, the unit a pass picks next is the same for a store of units with every combination of tiers as for the same store with no verdicts.
- [x] 2.4 Add the ordering to a small module under `pipeline/` that reads a unit's recorded tier, use it in `cmd_status` in `cli/pipeline.py`, and keep the scheduler's selection as it is.

## 3. [agent-build-kit] [unit-test] A card is raised only for units that need a person

Done when a review card is raised only for `light` and `full` units and for units with no verdict, and a source search finds only the readers of a verdict that the spec allows. Estimate: about 270 changed lines.

- [x] 3.1 Test: in `tests/notify/test_cards_review_tier.py`, a `light` or `full` unit in review has a review card, an `auto` unit has none, a unit with no verdict has one as before, a failed or held unit has its card whatever its tier, and a card for a unit whose tier has become `auto` is cleared by the existing reconciliation.
- [x] 3.2 Test: in `tests/test_verdict_readers_guard.py`, a search of the package source finds readers of the verdict file only in the label, ordering, cards, review route, history floor, report and recording modules.
- [x] 3.3 Use the ordering module in `desired_cards` in `notify/cards.py` so that a review card is raised only for units whose recorded tier is not `auto`.

## 4. [agent-build-kit] [unit-test] The review route and the pipeline summary carry the tier

Done when the review route's answer carries a unit's recorded tier, reason and stored focus and skippable lists, the pipeline summary carries the tier, and a unit with no verdict is answered as before. Estimate: about 220 changed lines.

- [x] 4.1 Test: in `tests/serve/test_review_tier_answers.py`, the review route for a unit with a verdict holds its tier, reason, focus list and skippable list, the pipeline answer carries each unit's tier, a unit with no verdict has neither field, and an unreadable verdict file gives the answer of before with the failure logged.
- [x] 4.2 Add the fields to the review route and the pipeline summary in `serve/server.py`.

## 5. [agent-build-kit] [unit-test] The review tab shows the tier and why beside the brief

Done when the tab shows a unit's tier, reason and lists in a strip at its head, the review page orders units in review by tier, and a unit with no verdict is shown as before. Estimate: about 340 changed lines.

- [x] 5.1 Test: in `web/src/review/tier.test.tsx`, the tab renders the tier and the reason above the thread list with the focus and skippable lists beside them, renders nothing extra for an answer without them, and shows `full` and `light` as distinct text and not by colour alone.
- [x] 5.2 Test: in `web/src/pages.test.tsx`, the units awaiting review are listed `full` first then `light`, units without a tier after the `full` and `light` ones and before `auto`, and the order inside a tier is the order the pipeline answered.
- [x] 5.3 Add the strip to `web/src/review/tab.tsx` with its types in `web/src/review/types.ts`, and the ordering to the review page in `web/src/pages.tsx`.

## 6. [agent-build-kit] [unit-test] A forge can say which commit a merged pull request produced

Done when a read on the forge protocol answers the commit a merged pull request produced, empty when it cannot say, GitHub answers it from its own merge record, the local forge answers empty, the read is retried like any other read, the stand-in forge can be given an answer, and Azure DevOps answers empty until the next group. Estimate: about 300 changed lines.

- [x] 6.1 Test: in `tests/forges/test_forge_operations.py`, the new read has an entry that makes it a repeatable read, and the check that every protocol method has an entry still passes.
- [x] 6.2 Test: in `tests/forges/test_github_merge_commit.py`, against the GitHub host fake a merged pull request answers its merge commit, an open or closed-unmerged one answers empty, a missing pull request answers empty, and a transient failure is retried before it is given up.
- [x] 6.3 Test: in `tests/forges/test_local_merge_commit.py`, the local forge answers empty for every pull request, whether merged or not.
- [x] 6.4 Add the read to the `Forge` protocol in `forges/base.py`, its entry in `forges/operations.py`, its implementation in `forges/github.py` and `forges/local.py`, an empty answer in `forges/azure_devops.py` until the next group, and an answer the test can set to the stand-in in `tests/forges/stand_in.py`.

## 7. [agent-build-kit] [unit-test] Azure DevOps answers the commit a completed pull request produced

Done when Azure DevOps answers the commit a completed pull request produced from its own merge record, empty for an active or abandoned one, and the read is retried. Estimate: about 150 changed lines.

- [x] 7.1 Test: in `tests/forges/test_azure_merge_commit.py`, against the Azure DevOps fake a completed pull request answers its merge commit, an active or abandoned one answers empty, and a transient failure is retried.
- [x] 7.2 Replace the empty answer in `forges/azure_devops.py` with the completed pull request's merge commit.

## 8. [agent-build-kit] [unit-test] A verdict record gains an outcome, and a revert is detected from the repository

Done when a merged unit's verdict record holds an outcome derived from its history and the repository by the rules the spec names, a revert is a trunk commit naming the merge commit or the pull request, a unit whose forge cannot say is marked unchecked, and the derivation is repeatable. Estimate: about 380 changed lines.

- [x] 8.1 Test: in `tests/pipeline/test_review_outcome.py`, a unit merged by a person with no rework entry is `clean`; one with two `rework` entries and a `base_changed` entry is `reworked` with a count of two; a unit not yet merged is `open`; a unit closed unmerged is `closed`; deriving twice gives equal results; a unit with no verdict record is left alone.
- [x] 8.2 Test: in `tests/pipeline/test_review_revert.py`, over temporary git repositories, a trunk commit after the merge with `This reverts commit <full sha>` marks the unit `reverted`; a trunk commit with `Reverts <owner>/<repo>#<number>` for the unit's pull request does too; a commit reverting another commit or another pull request does not; a commit before the merge naming it does not; a short sha does not; a commit only on a side branch does not; a forge answering no merge commit leaves the outcome from the history and the record says the revert was not checked.
- [x] 8.3 Add the outcome fields to the verdict record and their derivation to a module beside the recording one, and the revert search over the unit's checkout with `git log` in a second small module.

## 9. [agent-build-kit] [unit-test] A sweep rechecks merged units until the horizon on every pipeline pass

Done when merged units are rechecked until the horizon and then final, and the pipeline pass runs the sweep without failing on an error. Estimate: about 280 changed lines.

- [x] 9.1 Test: in `tests/pipeline/test_review_outcome_sweep.py`, the sweep updates the outcome of every merged unit inside the horizon and none outside it, a revert after the horizon changes nothing, a second sweep with nothing new writes nothing, an error reading one unit's forge or repository is logged and the others are still derived, and the file is replaced atomically.
- [x] 9.2 Test: in `tests/cli/test_tick_outcome_sweep.py`, a pipeline pass with review enabled runs the sweep once, with review disabled does not run it, and a sweep that raises does not fail the pass.
- [x] 9.3 Add the sweep that derives the outcome of each merged unit inside the horizon, and its call in the pipeline pass in `cli/pipeline.py` inside a guard that logs and swallows any error.

## 10. [agent-build-kit] [unit-test] Rates per class are computed over units with the brief and the gates are checked

Done when the clean-merge rate, the agreement rate and the sample counts of each class are computed from brief-carrying records only, records without the brief are kept and counted as excluded, and a class clears the gates on `min_samples` and `min_clean_rate` and a class no policy names is marked not nameable. Estimate: about 280 changed lines.

- [x] 10.1 Test: in `tests/pipeline/test_review_rates.py`, over a table of records, five brief-carrying records of four `clean` and one `reworked` plus ten with `brief` false give five samples, a rate of 0.8 and ten excluded; a `reverted` record is a sample and not clean; `open` and `closed` records are no sample; agreement is `clean` over the samples with evidence tier `auto`, two thirds for three such samples of which two are clean, and absent when a class has none.
- [x] 10.2 Test: in `tests/pipeline/test_review_gates.py`, with `min_samples` 20 and `min_clean_rate` 0.95 a class of 20 samples with 19 clean clears the gates, 19 clean samples do not and the shortfall is named, 20 samples with 18 clean do not, and a class that `review.classes` does not name carries the not-nameable mark even when it clears.
- [x] 10.3 Add the rates and the gates as one computation in a module beside the verdict record.

## 11. [agent-build-kit] [unit-test] The report says when a class clears the gates

Done when `abk review report` prints the rates, counts and gates read-only, and `abk status` prints a line for each class that clears the gates. Estimate: about 330 changed lines.

- [x] 11.1 Test: in `tests/cli/test_review_report.py`, `abk review report` over fixture records prints each class with its samples, clean-merge rate, agreement rate with its own sample count and the excluded count, says which classes clear the gates and may be added to `review.auto_land.classes`, says there is nothing to report for no records, and leaves abk.yaml, the records and the units byte for byte as they were.
- [x] 11.2 Test: in `tests/cli/test_status_review_gates.py`, `abk status` with review enabled prints one line for each class that clears the gates and none otherwise, and prints nothing about them with review disabled.
- [x] 11.3 Add the `review report` subcommand in a new module under `cli/` registered with the others, the status lines in `cmd_status`, and document the command in `docs/cli.md` and the `abk-pipeline` skill.

## 12. [agent-build-kit] [unit-test] The history floor reads real history, and outcomes are counted

Done when the verdict's history floor holds a class at `light` below `min_samples` or `min_clean_rate` computed over brief-carrying records and raises nothing otherwise, the floor and the report use the same computation, a class with no records is held as before, and the outcome and agreement counters are recorded without a unit id and listed in the metric catalogue. Estimate: about 430 changed lines.

- [x] 12.1 Test: in `tests/pipeline/test_verdict_history_floor.py`, a class that clears the gates leaves a unit whose other floors are `auto` at `auto` with both tiers `auto`, a class with three samples gives `light` and a reason naming the shortfall, a class with thirty clean records all without the brief gives `light`, a class with no records gives `light` as before, and the floor never lowers a tier another floor set.
- [x] 12.2 Test: in `tests/pipeline/test_review_floor_matches_report.py`, for each table of records the floor holds a class exactly when the report says the class does not clear the gates.
- [x] 12.3 Test: in `tests/pipeline/test_review_outcome_metrics.py`, deriving an outcome counts it once with its outcome, tier and class and no unit id, a later `reverted` adds a count and removes none, deriving the same outcome again counts nothing, and a merged unit whose evidence tier was `auto` counts whether a person accepted it as it stood.
- [x] 12.4 Test: in `tests/test_metric_catalogue_review_outcomes.py`, both counters are emitted by the source and listed in the catalogue helper.
- [x] 12.5 Replace the stubbed history in `pipeline/verdict.py` with the shared computation, count the outcomes and the agreement from the derivation, and note the new instruments in `docs/architecture.md` where the verdict record is described.
