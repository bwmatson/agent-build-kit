# Runbook: move an installation to risk-tiered review

Follow each section **when the change named in its trigger is built and merged**; nothing in it is read by the pipeline. Tick the boxes as you go. Note beside a section when it is done so the next person knows where the migration stands.

The work is twelve changes, all priority 1, in the kit. The design is `docs/risk-tiered-review-design.md` there and the reasoning is `docs/agent-efficient-coding-philosophy.md`. This runbook holds only the steps a person does. Everything the pipeline does itself is in the changes.

| Order | Change | What a person does after it merges |
|---|---|---|
| 1 | `test-kind-names-are-accepted-both-ways` | section 1 |
| 2 | `test-kinds-are-unit-test-and-e2e-test` | section 2, and the vocabulary sweep (section 3) |
| 3 | `review-policy-and-verdict-recorded-in-shadow` | section 4 |
| 4 | `reviewers-are-told-where-to-look` | section 5 (the calibration start date) |
| 5 | `units-are-triaged-by-review-tier` | section 6 |
| 6 | `low-risk-units-land-without-a-person` | section 7 |
| 7 | `tests-are-stubbed-checked-and-committed-per-group` | section 8 |
| 8 | `units-are-sized-by-review-tier` | section 9 |
| 9 | `a-unit-over-its-tier-is-held-and-split` | section 10 |
| 10 | `open-changes-are-migrated-to-review-tiers` | section 11 |
| 11 | `e2e-tests-before-merge-are-optional` | section 12 |
| 12 | `review-by-tier-is-always-on` | section 13 |

The order of 5 to 11 is not strict; each change names what it waits for in its `Needs:` lines.

## 0. Before anything starts

- [ ] `abk status`: note how many units are running, in review and held. `limits.max_units_in_progress` caps the running units, and a priority 1 change still needs a free slot.
- [ ] In-flight changes that touch the renamed areas wait for the compatibility change on their first affected group. Those lines are in each change's `tasks.md`; they stop mattering once the compatibility change has merged, and you can delete them then.
- [ ] Decide when the rename slices (section 2) should run. They touch most of the tree and conflict with every open branch, so prefer a time when few units are in flight. Restack and adapt carry the rest.

## 1. After `test-kind-names-are-accepted-both-ways`

- [ ] `abk tags <change>` and `abk check`: old `[tier1]` / `[tier2]` tags now validate with a notice. Read the notices; they are the list of what the rename will touch.
- [ ] `abk config` and `abk doctor`: any old settings key (`tier2_*`, `tier1_*`, `tests.tier2_marker`, `tier2_runtimes`, `tier2_splits`) is read with a notice. Nothing to change yet; this is the baseline.
- [ ] Check that the gated groups started (they were waiting). `abk status` shows what each is waiting on.

## 2. While `test-kinds-are-unit-test-and-e2e-test` runs (23 groups)

- [ ] Watch for units that fail the rename's progress test in a directory a slice has already converted. The fix is to rename that occurrence to the new spelling (the design note in each in-flight change says so); a unit that keeps failing is a `requeue --rework` with that note.
- [ ] After the slice that renames metrics, update any dashboard or query that reads `abk.tier2.*` to `abk.e2e.*`. The changelog entry lists them.
- [ ] After the slice that renames the lock file and the output directory, check that nothing outside abk reads `runs/tier2.lock` or `tier2-output/`.
- [ ] After the slice that renames the status context, check any forge branch rule or required-status setting that names `local/tier2`: it is now `local/e2e-test`.

## 3. After the last slice of the rename: the vocabulary sweep (person-run, outside the pipeline)

This is the step the changes do not do. The planning repo's own text still says `tier1` and `tier2`: the main specs in `openspec/specs/`, the specs and design notes of changes still open, `docs/`, and the `context:` in the OpenSpec project config (its `context:` and glossary). The code is renamed; the specs are the contract it is judged against, and they should say the same words.

Do it **once, after the rename has fully landed and before the next big change is proposed**, so no spec describes a name the code no longer has.

- [ ] Make sure no unit is mid-build on a change whose spec you are about to edit (`abk status`), or accept that its reviewer will see the spec change under it.
- [ ] Find the old spellings with `git grep -n -i -E 'tier ?[12]|tier[12]_'` and replace them with a reviewed edit; the rename tool is gone.
- [ ] Read the matches. `tier 1` and `tier 2` in prose become `unit-test` and `e2e-test`; `tier2_splits` and its siblings become `e2e_splits`. Leave a name alone where it is history (a dated research note under `docs/research/`, an archived change).
- [ ] Make the edit, run `openspec validate --all --strict` and `abk check`, and commit as one change that does nothing else, so `git log --follow` and blame still work.
- [ ] Remove the glossary sentence about the old spellings from the OpenSpec project config (its `context:` and glossary) and the direction note from each in-flight change's `design.md` once their groups have landed. Leave the glossary sentence about `integration-test` (a third kind, a label that behaves as `unit-test`) in place: once `integration-test-kind-is-a-label` group 1 has merged, drop only its clause that says not to tag a heading with it yet, and check `abk tags` lists `[integration-test]` among the tags accepted.

## 4. After `review-policy-and-verdict-recorded-in-shadow`

- [ ] In `abk.yaml`, check that `review.enabled` is not set to `false`. It is true by default and is the build-out flag: with it off nothing is recorded. Only a person edits this file; agents and tracks are refused.
- [ ] Add the installation's own `protected_paths` (the kit's defaults cover migrations, CI and deploy configuration, container definitions, secrets and ownership files), and per repo `repos.<name>.review.protected_paths` for paths that are sensitive there.
- [ ] Define `classes`. The first one to allow later is documentation or test-only changes, so list the globs that are only that, for example `docs: {paths: ["**/*.md", "docs/**"]}`.
- [ ] `abk doctor`: no failure for the `review` section, and no warning for a glob that matches nothing.
- [ ] After a few units have been reviewed, open `runs/verdicts.json` and read three or four entries. Check the class, the paths, the evidence tier and the reason are what you expect, before anything is calibrated on them.

## 5. After `reviewers-are-told-where-to-look`: the calibration starts

Calibration counts only units whose pull request carried the new description. Write the date here: **calibration started on ____ **.

- [ ] Open two or three new pull requests and read the "Start here" section as a reviewer. If the focus list is not what you would look at first, fix the review prompt's criteria (through a change, not a settings edit) before the numbers mean anything.
- [ ] Do not set `auto_land.classes` yet, and do not tune `min_samples` or `min_clean_rate` from anything before this date. Verdicts recorded earlier are kept and excluded.

## 6. After `units-are-triaged-by-review-tier`

- [ ] Run `abk review report` weekly. It lists, per class, the samples, the clean-merge rate and the agreement rate, and says when a class clears `min_samples` and `min_clean_rate`. The numbers are on units with the brief only.
- [ ] Check the ordering in `abk status` and the review tab: `full` first, then `light`; `auto` units that will not land are listed and not hidden.
- [ ] Read the rework and revert detection once by hand on two units: one that was reworked and one that is clean. A wrong "clean" here becomes a wrong promotion later.

## 7. After `low-risk-units-land-without-a-person`: turning auto-land on

Do this per class, one class at a time, never for all.

- [ ] `abk doctor`: the merge guard line for each repo. If a repo reports no branch protection, the command policy hook is the only guard and it does nothing against the pipeline's own merge; decide whether the repo should allow auto-land at all.
- [ ] Choose the class from `abk review report`: enough samples and a clean-merge rate at or above the gate, with the brief. Start with documentation or test-only changes.
- [ ] Add it to `review.auto_land.classes` in `abk.yaml`. That edit is the promotion, and it is a person's.
- [ ] Watch the first auto-landed unit end to end: the label, the comment naming the class and the reason, the digest card, `verify` and archive running as on any merged unit, and the sampled audit asking you to check one.
- [ ] To turn it off: empty `auto_land.classes`. To lift an automatic demotion once you have looked at why: `abk review reinstate <class>`; every demotion and lift is logged and carded.
- [ ] Weekly after that: read the audit queue and any demotion, and decide whether to promote the next class.

## 8. After `tests-are-stubbed-checked-and-committed-per-group`

- [ ] Set the per-group setting on for one repo first and run a multi-group unit. Check each group has its own commit pair, each red for the right reason, and the check-and-fix loop ran before the build.
- [ ] Look at the profiles: a toolchain that cannot stub keeps today's single pair; `abk doctor` says which.
- [ ] The last group of the change turns the default on after a soak. Confirm the soak criterion in its `design.md` was met before you let that group's pull request merge.

## 9. After `units-are-sized-by-review-tier`

- [ ] Run `abk config --migrate` (added by `limits-split-into-global-and-project`, extended by this change): it moves `max_unit_lines` to `review.ceilings.full`. Review the one change it shows, confirm, and keep the backup.
- [ ] `abk doctor`: the deprecation notice for `max_unit_lines` is gone, and the effective ceilings (5000 / 2000 / 750 by default) print.
- [ ] `abk status` now lists plans that are **stale** against the ceilings. Do not replan them yet; section 11 does that on purpose.

## 10. After `a-unit-over-its-tier-is-held-and-split`

- [ ] The last group of this change turns per-tier sizing on by default. Before its pull request merges, check the soak criterion in its `design.md`, and check `abk status` for any unit held "too big for its tier" and how it went.
- [ ] After it merges, new plans are sized by tier. Watch the planner-accuracy reading for a week: if the planner keeps estimating lighter than the verdict, units will be split more than intended.
- [ ] A unit held for a person because it ran out of split rounds or cannot be split is yours: read the reason on the hold and either split its tasks by hand or waive the size (`abk requeue`).

## 11. After `open-changes-are-migrated-to-review-tiers`: migrate the open changes

Do this after section 10, when sizing by tier is on, so the new plans use the new ceilings.

- [ ] `abk tags --fix` over the open changes: it rewrites `[tier1]` and `[tier2]` heading tags to `[unit-test]` and `[e2e-test]` and changes nothing else. It is a command you run; the pipeline never edits `tasks.md`.
- [ ] `abk config --migrate` again: it renames any remaining old test-kind settings keys in `abk.yaml`.
- [ ] `abk replan --report --all`: which plans are stale, how many units are started and unstarted, and what a replan would cost in planner calls.
- [ ] `abk replan --dry-run <change>` for a few changes: what each change's units would become (tier, size, joins, units dropped). Read the dropped ones.
- [ ] Migrate by priority, a few at a time: `abk replan --stale --limit 5`. A refused plan keeps the old plan and is listed. Units a plan would drop to `unplanned` are listed first and only applied with `--accept-unplanned`; look at each before you accept.
- [ ] Started units keep their shape; only the unstarted remainder of a partly started change is replanned. Check that on one change by hand.
- [ ] When `abk status` shows no stale plan, write the date here: **migration finished on ____ **.

## 12. After `e2e-tests-before-merge-are-optional`

- [ ] Leave `e2e_before_merge` at `required` (the default). Defer it per repo only where the live stack is slow or contended, and know that a deferred unit does not reach `auto` unless `review.auto_land.allow_deferred_e2e` is true.
- [ ] If you defer a repo: confirm that `verify` runs its live tests after the merge, and that a failed verification names the deferred units.

## 13. After `review-by-tier-is-always-on`: the last step

- [ ] Delete `review.enabled` from `abk.yaml`. It is ignored now and gives a notice until you do.
- [ ] Confirm `global_limits.max_unit_lines` is gone; a file that still has it fails to load and names `review.ceilings.full`.
- [ ] The README, `AGENTS.md`, the docs and the skills now say a person merges what was not auto-landed. Spot-check one pull request footer.
- [ ] Group 5 of this change deletes the rename tool. Merge it only after the vocabulary sweep (section 3) is done.
- [ ] Mark the two kit documents (philosophy and design) as implemented, if the change did not.
- [ ] Archive this runbook's "where it stands" notes: copy the two dates above into the changelog or the design document, then leave the runbook in place as the record.

## If something goes wrong

- **A class auto-landed something it should not have.** Empty `auto_land.classes`, then read the unit's verdict record for the reason. A demotion should already have been recorded; if it was not, that is a bug in the demotion triggers, and the change that added them needs a fix before the class returns.
- **Plans are being replanned that should not be.** The sizing digest is kept beside the `tasks.md` hash on purpose; a tick should only list stale plans. If one replans on its own, stop the timer and look at `runs/planned.json` for what moved.
- **The rename left something half done.** The guard test lists the old spellings that remain and where. The aliases (shims) stay importable until the last slice removes them; do not merge that slice while the guard still finds old spellings in directories other slices own.
