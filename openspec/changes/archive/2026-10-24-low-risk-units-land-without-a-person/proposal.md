# Proposal

## Why

Review is the slowest part of the flow, and most of what reaches a person needs nothing from them: documentation and test-only changes
that every gate has already vouched for. The earlier changes of this work rank what a person sees, say where to look, and record per
class how often units merged without rework and how often a person agreed with the verdict. This change acts on that record for the
narrowest class and no other, and makes it safe to take back: landing is pipeline code behind a forge method with its own retry and
refusal rules, it needs evidence the pipeline reads itself, a person still audits a share afterwards, and the first sign of trouble
raises the review a class gets without anyone having to notice.

## What Changes

- **Policy keys.** `review.auto_land.classes` (default empty, the off switch), `review.audit.sample_rate` (default 0.1) and
  `review.demotion.window` (default 30) and `min_agreement` (default 0.9). Validated by the same models as the rest of the section.
  Only a person edits them.
- **A merge method on the forge protocol.** Squash on GitHub, the matching completion on Azure DevOps, never on the local forge,
  with a retry entry like every other method. The head the pipeline approved is sent with it so a push in between is refused.
- **A landing step run by pipeline code** after approval, when the verdict says `auto`, the unit's class is listed, review is enabled,
  the class is not demoted, nothing a person did stands in the way, the unit builds on the trunk, and the checks the pipeline reads
  itself are all green. A pull request with no checks has no evidence and does not land.
- **The same record as a person's merge.** The unit is recorded `merged` with a new cause, `auto_landed`, through the existing merge
  path, so restack, cleanup, verify and archive work unchanged; the poller's later merged event for the same pull request changes
  nothing. A stacked child is retargeted and restacked as for any merge.
- **The pull request says it was auto-landed and why**, by a comment holding the verdict's reason and a label.
- **A digest card** lists what auto-landed, without a per-unit interrupt, and an `auto` unit that will not land is no longer hidden
  from the cards.
- **Audit sampling.** A deterministic share of auto-landed units is put to a person afterwards, who records the result with a command.
- **Automatic demotion.** A revert of an auto-landed unit, a verify failure of its change, a failed audit, or agreement below
  `min_agreement` over the window demotes the class: a runtime override in `runs/` that the verdict reads as one more floor holding
  the class at `light`. `abk review reinstate <class>` lifts it; every demotion and lift is logged and notified; `abk status` shows
  demoted classes.
- **`abk doctor` warns** when `auto_land.classes` is not empty and a repo's forge reports no branch protection.

## Impact

The first behaviour change that merges. With `review.auto_land.classes` empty, which is the default, nothing differs from before
except a new forge method no one calls. The build agent's merge denial in the policy hook, the command policy and the runtime's
disallowed tools is unchanged: the merge is a forge call made by the pipeline, not a command the agent could run. A new forge
operation, three state files in `runs/`, two commands and two card kinds appear.
