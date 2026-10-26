# Design

## Context

The build agent can never merge: the policy hook, the command policy and `--disallowedTools` refuse every route to one, and the
`Forge` protocol has no merge method. Only a person's merge moves a unit to `merged`, through the poller seeing it and `on_merged`
recording it, restacking what was built on it and cleaning up. After that `verify` and `archive` read only the stored state and the
pull request number. Earlier changes of this work added the verdict (a tier per unit, with a reason), the brief, the outcome of each
verdict record, per-class rates over units whose pull request carried the brief, and `abk review report`, which says when a class
clears `min_samples` and `min_clean_rate`. The policy is a section of abk.yaml that no agent and no part of the pipeline writes.

## Decisions

- **Pipeline code merges, and only pipeline code.** The merge is a new forge method called by a landing step. It is not a shell
  command, so the agent's denial needs no change and gets none: `hooks/policy.py`, `pipeline/command_policy.py`, each forge's denied
  commands and requests, and the runtime's `--disallowedTools` stay as they are, pinned by a test that the lists are unchanged. The
  `acp` runtime ignores deny lists, so the docs say plainly that a build run on it has only the server-side guard.
- **Nothing is on by default.** `auto_land.classes` is empty; a class is turned on one at a time by a person editing abk.yaml, and
  emptying the list is the off switch. The first class a person should enable is a documentation or test-only class. A class named
  in the list must exist in `review.classes`, as the section already validates. `audit.sample_rate` is a rate from 0 to 1,
  `demotion.window` a count of at least 1, `min_agreement` a rate from 0 to 1.
- **The forge method.** `merge_pr(repo, pr, *, head)` squash-merges pull request `pr` when its head is `head` and returns the commit
  the merge produced. A host that refuses (not mergeable, a protection rule, a head that moved, a pull request already closed)
  raises `MergeRefused` with the host's reason, and the landing step treats it as a decline, not a failure. The GitHub adapter
  passes the head as the merge call's expected head sha and the squash method; the Azure DevOps adapter completes the pull request
  with the squash strategy and the last merge source commit as the head; the local forge raises `MergeRefused` always, since a
  merge there is a person's, made with git. A forge says whether it merges at all (`merges`), so a repo on one that does not is
  simply never landed. If the Azure DevOps adapter proves larger than its group, `merges` stays false there and the repos on it
  never auto-land until a follow-up change finishes it; GitHub does not wait for it.
- **Retries.** A merge is a write that must not be repeated blindly: it is declared as a create whose landing read is the existing
  read of the commit a merged pull request produced, so a retry after a transient failure first asks whether the merge happened and
  returns that commit if so. A refusal is never retried.
- **The landing step.** A pass over units in review, run by pipeline code after the poll, lands a unit only when every one of these
  holds, and otherwise records why it declined, in words, where `abk status` shows it:
  review is enabled; the unit is in review with no feedback pending and not held; its recorded verdict tier is `auto`; its class is
  in `auto_land.classes` now (the policy as it stands, not as it stood at approval); its class is not demoted now; its forge
  merges; its pull request is open, not a draft, not known to conflict, carries no hold label and no request for changes; the pull
  request's head is the commit review approved; the unit builds on the trunk, with nothing unmerged beneath it (a stacked unit waits
  for its parent, which also keeps a landing from merging into another unit's branch); and the checks are green.
- **The pipeline reads the checks itself.** It reads the pull request's checks from the forge when it is about to land and requires
  every one to have passed. There are no required checks to rely on, and none may be assumed to exist: a pull request with no checks
  registered has no evidence, does not land, and is declined with that reason, which also puts it in front of a person. Pending or
  cancelled checks wait; a failed one is left to the existing rework path.
- **Squash, because the rest of the pipeline already assumes it.** Restacking recognises a squashed parent by patch identity, so a
  squash by the pipeline looks like a person's. A stacked child is retargeted and restacked by the same code as for any merge.
- **The record is the same as a person's, and idempotent.** The landing step records the merge through the existing merge-record
  path, with a new cause `auto_landed`, which restacks children, removes the worktree and branch and releases what waited. That path
  becomes idempotent: an event for a pull request whose unit is already recorded `merged` changes nothing, writes no history entry,
  and restacks and cleans nothing a second time, so the poller's later `merged` event for the same pull request is a no-op. The
  forge merge itself is preceded by an intent record in `runs/` naming the unit and pull request and followed by its removal once the
  merge is recorded, so a crash between the two leaves a landing the next pass can see: the poller's merged event for a pull
  request with an intent is recorded with the cause `auto_landed`, not as a person's merge, which would otherwise count as a person's
  agreement. Intent records and landed records are one file.
- **Say so on the pull request.** After the record, the pipeline comments on the merged pull request that it landed without a person
  and why, quoting the verdict's reason and the class, and adds the label `auto-landed`. Both are best-effort: a failure is logged
  and changes nothing.
- **Cards.** Change `units-are-triaged-by-review-tier` raised none for an `auto` unit on the grounds that it would land. That holds
  here only for a unit the landing step will land: an `auto` unit in a class not listed, in a demoted class, or last declined for
  something that will not clear by itself (no checks registered, a forge that does not merge) raises a card as a `light` unit does, so
  it cannot sit unseen. A unit waiting on pending checks still raises none. The digest is a card of its own kind listing the units
  auto-landed in the last 24 hours with their classes and a link each; it is sounded once with no reminder, keyed by the date, and
  cleared when nothing is left in the window. A person is not interrupted per unit.
- **Audit sampling is deterministic.** A landed unit is picked for audit when a fraction derived from a hash of its id and the
  commit it landed as is below `audit.sample_rate`, so the same unit and rate always give the same answer and a test needs no
  randomness; a rate of 0 picks none and 1 picks all. A picked unit gets an audit card and is recorded as awaiting audit in `runs/`.
  `abk review audit <unit> ok|wrong` records the result and clears the card; `abk status` lists audits waiting. A person's own
  checking of a unit that was not picked is welcome and not recorded.
- **Auto-landed units in the rates.** An auto-landed unit is derived an outcome by the same rules as any merged unit (a revert is
  found the same way) and its record says it was landed by the pipeline. No person read it, so it is a sample for the clean-merge and
  agreement rates only when it was audited (`ok` counts as accepted, `wrong` as not) or reverted (not accepted), and an unaudited
  auto-landed unit that has not been reverted is no sample, so unread work never raises a class's record.
- **Demotion is a runtime override and only raises review.** A demotion is a record in `runs/demotions.json` naming the class, the
  trigger, the unit and the time, never a write to abk.yaml. The verdict takes it as one more floor holding the class at `light`,
  beside the history floor, and the landing step reads it live. That is the whole of its power, and since it only raises review the
  pipeline may do it alone without breaking the rule that no agent edits the policy. The triggers are, for a class with an
  auto-landed unit: a revert of such a unit, found by the outcome sweep; a failed `verify` of a change that has such a unit, which
  demotes the class of each of its auto-landed units since the live test cannot say which one broke it; an audit recorded `wrong`;
  and agreement below `min_agreement` over the most recent `window` agreement samples of the class, once there are at least the
  smaller of `window` and `min_samples` of them. A second trigger on a class already demoted is logged and added to its record.
- **Lifting is a person's command.** `abk review reinstate <class>` marks the demotion lifted, with the time, and the verdict no
  longer applies the floor to units computed after it. Nothing else lifts one, including the passing of time or a good run of
  results. Every demotion and every lift is logged to the run log and raised as a card: one while the demotion stands, and a
  notice of the lift for a day. `abk status` shows each demoted class with its trigger and since when.
- **`abk doctor` warns about the guard.** When `auto_land.classes` is not empty, a warning (not the information it is today) for
  each repo whose forge reports no branch protection: the policy hook is then the only guard and does nothing against the pipeline's
  own merge. It also warns when the list is not empty and `review.enabled` is false, which makes it ineffective.
- **Acceptance is opted out.** The only hosts that merge are real ones, and a scripted run against one would merge real code that
  cannot be unmerged. The behaviour is proved through the real GitHub and Azure DevOps adapters against their HTTP fakes, end to
  end through the landing step, the record and the poller, and by the doctor warning that comes before any class is enabled.

## Risks

- **Merging without branch protection.** The checks are read by the pipeline, the doctor warns, nothing is enabled by default, and a
  class is enabled one at a time by a person who has read the report.
- **Landing over a person's veto.** A hold label, a request for changes, a draft, or a moved head each stop a landing, but a person
  who has only opened the diff and said nothing does not. The audit and the digest are the answer to that, and a class is enabled
  only by a person.
- **A stacked child's base.** Only a unit with nothing unmerged beneath it lands, so the base is the trunk; its children are then
  retargeted by the existing release path, which has a test of its own here.
- **Squash by assumption.** A repo that forbids squash merges is refused by the host and the unit is declined, not failed.
- **A revert phrased in a way the sweep does not see** would keep a class from demotion by revert; agreement and audits remain.
- **An `acp` run** has no agent-side deny list, so server-side protection matters more there; the docs and the doctor say so.
