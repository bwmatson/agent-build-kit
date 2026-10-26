# Agent-efficient coding: verify everything, review by risk

> **Status: implemented.** This is the record of the reasoning; the pipeline now works this way.

abk was built around one idea: plan a change carefully, build it to a high
standard, and send every unit to a person before it merges. That idea worked
while builds were slow. It stops working once the pipeline produces more pull
requests than a person can read carefully. Most of those PRs are fine, and the
few that matter look the same as the rest in the queue. This document sets out
the philosophy abk is moving to, the outside evidence behind it, and a design
sketch of how it would work. The sketch is illustrative: it does not decide how
the pipeline, configuration or UI change, and the code and setting names in it
are proposals. That is follow-up work (see
[What this document does not decide](#what-this-document-does-not-decide)).

In one line: **every change is verified, and a person reviews only the changes
that verification can't vouch for.**

Terminology: this document uses "tier 1" and "tier 2" for the two kinds of
test abk runs today. The [design](risk-tiered-review-design.md) renames them
unit-test and e2e-test, so that "tier" alone means a review tier.

## Why the old stance stops scaling

Reviewing every PR made sense when a person was the only check that looked at
a change as a whole. abk no longer depends on that. Every unit already passes
a test committed and run red before the implementation (see
[What "run red" means](#what-run-red-means)), tier 1, tier 2 on a live stack, a read-only review by a different model, and, for a change as a
whole, `[acceptance]` and post-merge verify. What human review adds on top of
that is real, but it is narrow. It catches the change that is correct and
still wrong: the wrong contract, an unsafe default, a risk the spec never named.

### What reviewing everything costs

Reviewing everything has three costs:

- **It hides the PRs that matter.** If forty routine PRs and one contract change
  arrive with the same notification and the same layout, the reviewer's
  attention is spread evenly over all of them. The contract change gets the
  same few minutes as a docstring fix.
- **It trains rubber-stamping.** A reviewer who approves forty clean PRs in a
  row learns that approval is the expected answer. A review that almost never
  finds anything stops being read closely, while it still looks like a
  safeguard.
- **It limits throughput.** `project_limits.max_units_in_progress` and the stack-depth
  caps exist because open PRs waiting for a person pile up. The builder waits
  on the reviewer, and the reviewer is the slowest part of the pipeline.

Review is a scarce resource to spend where it pays off. Applying it to every
change by habit wastes it.

### What "run red" means

The first gate is the one the rest lean on, so it is worth spelling out. Before
the implementation exists, the builder writes the tests for it and commits
them on their own. The pipeline then runs those tests at that commit, and they
must **fail**: that failing run is "red". Only after a red run does the
implementation get written, and the tests turn "green".

A test that has never been seen to fail proves little. It may assert nothing,
exercise the wrong function, or pass whatever the code does. A test committed
together with the code it covers has never had the chance to fail, so a
passing run says only that the two agree. A red run at a separate commit is
recorded evidence that the test can tell the difference between code that does
the job and code that doesn't, and a later green run means something. abk
keeps that evidence honest in two ways: the red run is checked at the
test-only commit (`abk gate`), and the policy hook denies `--amend`, so the
commit order can't be rewritten afterwards.

This matters here because it is evidence a machine can check without reading a
diff, which makes it a fit foundation for letting changes land without a
person.

## What others are finding

The industry is going through the same shift. Most of what follows is
practitioner writing and should be read as opinion. The exceptions are Meta's
paper and the large studies, which report measurements.

**Agents increase output faster than review keeps up.** A Harvard/Jellyfish
study of more than 700 software companies (as reported by
[n8nlab](https://n8nlab.io/news/ai-coding-agents-code-review-bottleneck); the
paper is [here](https://fion.ac/jellyfish.pdf)) found that adopting coding
agents raised lines of code by about 30%, commits by about 20% and PRs by about
23%. Resolved issues did not rise measurably, and the time from a PR opening to
its merge grew by about 49%. Meta reports that lines per landed diff rose 106%
year over year, most of it from agentic AI, while the share of diffs that got a
timely human review fell
([RADAR, arXiv 2605.30208](https://arxiv.org/abs/2605.30208)).

**Risk-stratified auto-review works at scale.** Meta's RADAR runs every diff
through the same stages in order:

1. It classifies the diff by author and source.
2. It applies eligibility gates and static heuristics.
3. It scores the diff's risk with a learned model.
4. It runs an LLM review.
5. It validates the result deterministically.

Only diffs that come out low-risk land without a person. Across more than
535,000 reviewed diffs:

- Diffs reviewed by RADAR were reverted at one third the rate of the others.
- They caused production incidents at one fiftieth the rate.
- Median review time fell 35%.
- Relaxing the risk threshold from the 25th to the 50th percentile raised the
  approval rate to about 60%.

**The verdict is code, not a model.** Rewind's AI-approval system
([write-up](https://rewind.com/blog/ai-approve-pull-requests-safely/)) runs
more than a dozen reviewers in parallel, each with its own focus: correctness,
security and tenant isolation, tests, blast radius, revertibility. Each one
reports findings with a severity and a confidence. Unit-tested code, not a
model, turns those findings into a LOW/MEDIUM/HIGH grade and decides whether
the PR is eligible.

- **Protected paths.** A hand-audited, CODEOWNERS-protected policy file lists
  paths that can never be auto-approved: auth, authorization, secrets,
  encryption, governance.
- **Gradual rollout.** The system ran for a week in shadow mode, reviewing
  every PR without gating any. It was then promoted on objective gates: at
  least 90% agreement with human reviewers, and no linked incidents or
  reverts.
- **Early results.** About 40% of PRs were auto-approved, with about 99%
  agreement where a person also reviewed, at under a dollar per PR. These
  figures come from about one week of data.
- **Fixed policy.** The bot never edits its own prompts or policy.
- **Merge stays separate.** Auto-approval does not mean auto-merge: CI and
  branch protection still apply.

**Route by blast radius, not size.** Several guides make the same point
([Augment](https://www.augmentcode.com/guides/agentic-code-review-authority-boundaries),
[Addy Osmani](https://addyosmani.com/blog/agentic-code-review/),
[SoftwareSeni](https://www.softwareseni.com/why-agent-generated-code-is-breaking-the-pull-request-review-model/)):
what a change touches and how easily it can be undone decide how much review it
needs. A large mechanical change can be safe, and a three-line change to an
auth check is not. A common pattern is three levels of authority by kind of
change: the reviewer flags findings, blocks the merge until a person clears it,
or approves a bounded change outright.

**Cheap signals already predict which PRs need attention.** A study of 33,707
agent-authored PRs ([arXiv 2601.00753](https://arxiv.org/abs/2601.00753)) found
that 28.3% merge immediately. Static cues available when the PR is created, such
as file types and patch size, picked out the high-effort PRs with an AUC of
0.96. Reviewing only 20% of PRs caught 69% of the costly ones.

**The maker should not grade the checker.** An agent that writes both the
implementation and its tests produces tests that show the two are consistent,
not that either is correct
([Vercel](https://vercel.com/i/evaluating-ai-coding-agents),
[Augment](https://www.augmentcode.com/guides/adversarial-code-review)).
Independent checks matter: a separate context, a different model, and tests
written before the implementation. An AI approval is labelled as AI and never
counted as a human review.

**Not everyone agrees.** One position paper argues that human code review is
already redundant and should be kept only for high-risk or regulated changes
([The End of Code Review, arXiv 2606.13175](https://arxiv.org/html/2606.13175v1)).
It brings together existing evidence and runs no new experiments. Most
practitioners stop short of that. They keep a person accountable for the
merge on risky paths, and they warn that "a human is responsible" often means
nobody actually read the change
([Codacy](https://blog.codacy.com/code-review-is-dead-why-ai-generated-code-needs-verification-not-human-approval),
[Nish Bhana](https://nishbhana.com/Removing-The-Human-From-Code-Review/)).

## Where forward-thinking groups converge, and where they split

This comparison draws on the sources above. Few groups publish measurements, so
read it as a description of the practice, not a ranking. The short version:
verification is mandatory and automated, human review depends on risk, and
trust placed in automation is earned by measurement and can be withdrawn.

### Converging

| Approach | What groups agree on |
|---|---|
| **Verification is mandatory** | None of the sources proposes dropping tests, CI or independent checks. The disagreement is only about the *human* step. |
| **Risk decides review depth** | Blast radius, revertibility and the kind of change route a PR. Size and author do not. Meta, Rewind and the practitioner guides all arrive here. |
| **A never-auto-approve list** | Auth, authorization, secrets, encryption, billing, infrastructure, migrations and public APIs keep a human gate. The list is kept by people, in version control. |
| **The maker doesn't grade the checker** | A separate context, a different model or an adversarial reviewer. Tests written by the same model that wrote the code are treated with suspicion. |
| **The final verdict is not a model's opinion** | Meta ends with deterministic validation; Rewind turns findings into a grade with tested code. Models produce evidence, rules decide. |
| **Policy is human-owned** | Rewind's bot never edits its own prompts or policy, and its policy file needs code-owner review. The same principle shows up wherever the sources discuss who may change the rules. |
| **Trust is staged and measured** | Shadow mode first, then enabled on a subset, then promoted or demoted on agreement, reverts and incidents. |
| **Oversight continues after merge** | Fast revert, post-merge checks and sampled audits are treated as part of the safety design. |

### Diverging

| Question | The positions |
|---|---|
| **Is any human review needed?** | One position paper says human review is already redundant except for high-risk or regulated changes. Most practitioners keep a named person accountable for the merge on risky paths, and say a person who didn't read the change isn't accountable in any useful sense. |
| **How is risk scored?** | Meta uses a learned risk model plus an LLM review. Rewind uses a council of specialist LLM reviewers whose findings feed fixed rules. Others use only path and keyword deny-lists. The cheaper methods are less precise but easier to audit. |
| **Who merges?** | Meta lands low-risk diffs without a person. Rewind's bot approves, but a person still clicks merge on any PR the bot wrote, and CI and branch protection still apply. |
| **One reviewer or several?** | Some systems use one reviewer model. Others run many in parallel, or a proposer, a challenger and an arbiter. More reviewers catch more, and cost more and need tuning. |
| **Where does safety live?** | Most put it before the merge. Some move the real boundary to rollout time: feature flags and gradual release, so the review can be lighter because the change is easy to switch off. |
| **How big can a change be?** | Rewind skips AI review above roughly 10,000 lines on the argument that no reviewer can hold that much. Meta's pipeline gates on its risk score and its eligibility rules. |
| **Should a second opinion gate?** | Rewind runs another vendor's reviewer as advisory only, so it informs calibration but never decides. Others treat any extra reviewer as one more gate. |
| **How early can PRs be triaged?** | One study predicts which PRs will be costly using only cues available at creation, such as file types and patch size. Most systems wait until a review has run. |

abk adopts everything in the converging table and takes a position on each
split:

| Question | abk's position |
|---|---|
| Is any human review needed? | Yes, for the full-review tier, and a sampled audit of what auto-landed. |
| How is risk scored? | The planner's estimate, hard exclusions read from the diff, recorded gate results, the reviewer's classification and a per-class track record. The highest tier wins. |
| Who merges? | Auto-land merges without a person, as Meta does; light and full review are merged by a person. A deterministic verdict, not a model, decides which. |
| One reviewer or several? | One reviewer by a different model, as today. More are a later option. |
| Where does safety live? | Before the merge, plus post-merge `verify` and fast revert. Feature-flag rollout is not assumed. |
| How big can a change be? | Size is a planning budget per expected tier, not a risk signal. |
| Should a second opinion gate? | Not in this design. |
| How early can PRs be triaged? | At planning, from the plan's flags and expected paths; the diff's verdict overrides it. |

## Principles

1. **Verification is not optional; human review is.** Every unit passes every
   gate it passes today: red-first tests, tier 1, tier 2 where tagged (before the
   merge or deferred to `verify`, as configured), and an independent model
   review. Nothing in this philosophy weakens a gate. What
   changes is that passing the gates can be enough.

2. **Evidence beats inspection.** A person reading a diff is a weaker check
   than a test that was seen to fail and then pass against a real stack. Put
   effort into the evidence first, such as more realistic tests and better
   acceptance, before adding more reading.

3. **Route by blast radius and reversibility.** The questions that decide
   review are what breaks if the change is wrong, who notices, and how fast it
   can be undone. Diff size, author and how confident the reviewer sounds do
   not decide it. Size only sets how much work is bundled into one PR, once
   the review it will get is known (see
   [Sizing work by expected review](#sizing-work-by-expected-review)).

4. **Spend human attention where the gates can't see.** Tests check what the
   spec says. A person is needed when the spec itself might be wrong, when a
   change crosses a boundary other systems depend on, or when a mistake can't
   be cleanly undone.

5. **Humans own the policy, and the agent never edits it.** This is a hard
   rule, not a preference. The rules that decide what may land without a
   person, the list of areas that never auto-land, the thresholds and the
   gates themselves are kept in version control and changed only through human
   review. No agent can change them: not the builder, not the reviewer, and not
   a track's `propose`. A pull request that touches the policy is always
   full review, and the build agent's permissions are fenced off from it the
   same way they are fenced off from merging. The hard exclusions always win
   over any score.

6. **Earn trust, measure it, and be able to take it back.** Auto-landing starts
   in shadow mode, where it predicts and a person still merges. Each class of
   change is promoted only on its own record of being merged without rework,
   and demoted automatically when auto-landed changes are reverted or cause
   incidents.

7. **Keep part of the safety after the merge.** Post-merge verify, fast
   reverts and sampled audits of what auto-landed are part of the design. They
   are not an admission that the gates failed. A pipeline that can undo a
   change quickly can afford to merge it sooner.

8. **Unreviewed does not mean unaccountable.** Every auto-landed change says
   that it auto-landed and why: the risk evidence, the gates it passed, the
   reviewer's verdict. A person can audit it later as easily as they could have
   reviewed it first.

9. **Make the remaining reviews count.** A person asked to review should see
   at once why the PR needs them: the risk that sent it to them, what to look
   at and what has already been checked. Asking for a review is a signal and
   should be rare enough to be taken seriously.

## Risk tiers

The tiers are concepts, not configuration. They describe the intended outcome.

| Tier | Lands when | Typical changes |
|---|---|---|
| **Auto-land** | Every gate is green, the reviewer approved with no open required findings and classified it auto-land, and nothing in the change matches an exclusion | Docs, test-only changes, narrow in-repo changes behind an existing interface, mechanical dependency bumps, `fix-*` flake changes |
| **Light review** | A person skims a summary and merges; the diff is open if they want it | Larger internal refactors, new modules behind an existing seam, and any class of change without enough clean history yet to auto-land |
| **Full review** | A person reads it and merges, as abk works today | Anything in [the list of areas that never auto-land](#areas-that-never-auto-land), or anything the reviewer classifies as full review |

Three rules apply on top of the table:

- **The exclusions are absolute.** A change that touches a full-review area is
  full review regardless of size, score or test results.
- **When in doubt, go up a tier.** A signal pointing to two tiers resolves to
  the higher one. Auto-land is an outcome a change has to qualify for, not the
  default.
- **Tiers only ratchet up.** The planner's estimate is the starting point.
  The reviewer model, a failing signal or a person adding a label can each
  raise a change to a higher tier, and none of them can lower it. Only the
  policy, through the per-class track record, can make a class eligible for a
  lighter tier, and that decision is made before a unit exists, not during its
  review.
  This is a rule about the rules inside one verdict. The verdict is recomputed
  after each review round from what exists then, so a rework that removes a
  risky path lowers the next round's tier, and a reviewer's classification in
  one round is not carried into the next.

### Areas that never auto-land

The most important part of the policy is the list of areas that cannot land
without a person, whatever else the gates say. It is short on purpose, it is
a list of *what a change touches*, and it is the first thing checked. A change
matching any entry skips the scoring entirely.

- authentication, authorization, sessions and permissions
- secrets, credentials, keys and anything that reads them
- billing, payments and anything that moves money
- infrastructure, deploy scripts, CI configuration and branch protection
- database migrations, and any change that deletes or rewrites stored data
- public API and wire-format changes, including every `[contract]` group
- the auto-land policy, its exclusion list, and the pipeline's own gates
- changes to tests that define acceptance, and anything crossing a repo boundary
- anything the reviewer classifies as full review

An installation extends the list with its own sensitive paths. Narrowing it
is a policy change and is full review.

## How it would work

Three mechanisms turn the tiers into pipeline behaviour: the planner sizes
units by the review they expect, a unit that earns more review than it was
sized for goes back for a split, and a deterministic verdict decides the tier.

### Sizing work by expected review

The unit size ceiling (`global_limits.max_unit_lines`, 750 today) rests on one
argument: a person has to read the whole diff in one sitting. That argument
holds only when a person reads it. A unit expected to auto-land is judged by
gates, not read line by line, so a ceiling set for human attention is
needlessly small for it, and every extra PR it forces is more overhead for
everyone. The planner should therefore **estimate the review tier a unit will
get, and trim its groups to a size ceiling set for that tier**. The
ceilings are configuration, with these defaults:

| Expected tier | Default ceiling | Why |
|---|---|---|
| Auto-land | ~5,000 lines | Gates and a reviewer model carry it; no person reads it in one sitting. |
| Light review | ~2,000 lines | A person skims a summary and opens the diff only when something stands out. |
| Full review | ~750 lines | A person reads every line, so the existing ceiling applies. |

This keeps the principle that size does not decide *whether* a change is
reviewed. Size here only decides how much work is bundled into one PR, once
the review it will get is known.

Three consequences for the planner:

- **The planner estimates the tier from what it can see before any code
  exists:** the task groups' flags, the repo and tier tags, and the paths the
  tasks say they will touch, checked against the protected list. When in
  doubt it estimates the higher tier, as the verdict does.
- **A unit takes the tier of its riskiest group.** One group that expects full
  review makes the whole unit full review and brings its ceiling down to 750.
  The planner should therefore keep a full-review group in its own small unit
  and not bundle it with auto-land work. The auto-land work then stays large
  and the PR a person reads stays small.
- **The estimate can be wrong, and the verdict has the last word.** A unit
  planned as auto-land that the verdict sends to full review is now larger
  than a person should be asked to read. Handing it over as it stands defeats
  the purpose of the ceiling, and a silent auto-land to avoid that would defeat
  the purpose of the verdict. So the unit is **held and split**; see
  [Hold and split](#hold-and-split).
  How often the planned tier and the verdict's tier differ is also a direct
  measure of how good the planner's estimate is.

A reviewer model has a limit as well. Another group skips AI review above
roughly 10,000 lines because no reviewer can usefully hold that much, so
the auto-land ceiling, buffer included, should stay well under that and stay
configurable.

### Hold and split

When the tier a unit earns, at any review round, is higher than the tier it was
sized for, and the unit is over the ceiling of the tier it earned, the unit is
held at that round: it is not sent for more rework, not approved, not merged and
not handed to a person. It goes back. (The same applies when the diff turns out
larger than the ceiling of the tier it was planned for. With no `drivers`
to pin, the re-plan is then asked only to bring each unit under its ceiling.)

"Over the ceiling" allows a **buffer**, 20% by default and configurable, that
only the verdict uses. The planner still plans to the plain ceilings. A re-plan
and split costs model calls and rebuilt work, so a unit a little over its tier's
ceiling is better sent through to review as it is than split.

1. **The unit is held**, with a cause that says it was over the ceiling for its
   classified tier. It is not a failure and does not count against the
   review-round limit for an ordinary rework.
2. **The reviewer's classification names what drove it.** A classification
   above the plan's estimate must come with the groups or files that caused
   it. Without that, the split can't tell which part of the unit needs the
   higher tier.
3. **The unit goes back to planning.** The held unit is superseded, and the
   planner is run again for its groups under one constraint: the groups the
   reviewer named as `drivers` go in a unit of their own at the higher tier,
   within that tier's ceiling, and the rest stay together at the tier they
   were planned for, with that tier's larger ceiling. The constraint is an
   input to the planner. `tasks.md` stays as its author wrote it. The new plan
   is validated like any other (ceilings, flags, dependencies), and the
   groups keep their order: a driver group in the middle of a unit gives a
   unit before it, the driver, and a unit after it, chained by dependencies.
   The commits already built for those groups are reused by the new units
   where the build commits per group (see the
   [design](risk-tiered-review-design.md#stubs-in-the-test-node-and-per-group-commits));
   until then the pieces are rebuilt.
4. **Each resulting unit is reviewed again on its own,** and its classification
   can again only go up. The number of splits is limited by its own setting,
   proposed as `split_rounds` with a maximum of 2. A re-plan that fails or
   doesn't validate uses up a round, like a successful split. When the rounds
   are used up, or a unit can't be split further (a single group over its
   ceiling), the unit is held for a person instead.

Each piece is a unit of its own, with its own branch, pull request and verdict.
The alternative, keeping one unit and opening several pull requests from it,
was rejected because a unit is one branch and one pull request throughout the
pipeline: its branch name, its PR, its labels, the poller's mapping from PR to
unit and its state all assume it. Going back to planning keeps "one unit, one
PR, one verdict", and the verdict stays simple to state.

The extra cost of a split is the price of a wrong estimate, which is why the
planner is told to estimate high when in doubt.

### An example of a deterministic verdict

"Deterministic" means the decision is made by ordinary code, with no model
call, that gives the same answer for the same inputs and can be unit tested.
Models gather evidence; the verdict reads it. A model can be wrong in a
confident voice, so the last step must not depend on one.

The verdict runs **after every review round**, on what is recorded at that
point. Only the one the approving round makes is final; the earlier ones are
interim, and exist so that a unit that is going to be split can be held at the
first round that shows it. A gate that has not run yet because it runs after
review counts as met in an interim verdict and as missing in the final one.

The sketch below is an illustration of the shape, not a config format abk has
today. Everything it reads is a fact recorded earlier in the pipeline:

```python
def verdict(unit: Unit, policy: Policy) -> Verdict:
    # Tier is ordered: AUTO_LAND < LIGHT < FULL. Every rule can only raise it,
    # starting from what the planner estimated.
    floors = [(unit.planned_tier, "estimated at planning")]

    # 1. Hard exclusions, read from the actual diff and from the plan,
    #    never from the PR text.
    if policy.touches_protected_path(unit.changed_files):
        floors.append((Tier.FULL, "touches a protected path"))
    if unit.group_flags & {"contract", "narrow", "acceptance"}:
        floors.append((Tier.FULL, "contract or acceptance group"))

    # 2. Evidence the pipeline already recorded must be present and green.
    #    A missing result is not a green one. (A failed gate normally sends the
    #    unit back for rework before the verdict runs; this keeps a gap from passing.)
    if not (unit.red_run_recorded and unit.tier1_green and unit.tier2_green_or_not_required):
        floors.append((Tier.FULL, "a gate did not pass"))
    if unit.review.open_required_findings:
        floors.append((Tier.FULL, "the reviewer has open required findings"))

    # 3. The reviewer's classification. It may only raise the tier, and a
    #    missing or unparseable classification counts as full review.
    floors.append((unit.review.classification or Tier.FULL, "classified by the reviewer"))

    # 4. Track record for this class of change.
    history = policy.history_for(unit.change_class)
    if history.clean_merge_rate < policy.min_clean_rate or history.samples < policy.min_samples:
        floors.append((Tier.LIGHT, "not enough clean history for this class"))

    tier, why = max(floors, key=lambda floor: floor[0])

    # 5. The unit was sized for the tier the planner expected. If it earned a
    #    higher one and is too big for it, send it back; do not hand it over.
    #    The buffer is the verdict's only: the planner plans to max_lines itself.
    if unit.changed_lines > policy.max_lines[tier] * (1 + policy.ceiling_buffer):
        return Verdict.HOLD_AND_SPLIT(tier, why, drivers=unit.review.drivers)

    return Verdict.of(tier, why)
```

Where each input comes from, and what is deliberately left out:

- **`group_flags` is declared in the plan, then checked.** A unit does not
  carry flags itself. They are written by whoever authors the change, as
  `[contract]`, `[narrow]` or `[acceptance]` on a task group's heading in
  `tasks.md`, and validated by `abk tags` (a contract must be followed by a
  narrowing, an acceptance group must exist, and so on). The verdict would
  look up the groups a unit builds and collect their flags. A flag is only as
  good as the author, which is why it is not the only input: the protected
  path check reads the files the diff actually touches, so a contract change
  that was never tagged is still caught if it lands in a public API path.
- **`tier2_green_or_not_required` needs no new ordering, and is a setting.**
  Tier 2 does not run only at the end. A `[tier2]` unit can run it as part of
  its own build, on its branch and before the push, so the result is recorded
  by the time review starts. Running it before merge is a configuration
  choice, not a given: an installation whose live stack is slow or contended
  can leave it optional and rely on `verify` instead. What runs at the end,
  after every unit of a change has merged, is `verify`: a deploy, the live
  tier 2 tests and the `[acceptance]` group, the post-merge net of principle
  7. The verdict therefore reads three states for a `[tier2]` unit: *passed
  before merge*, *deferred to verify by configuration*, or *failed*. Whether
  *deferred* may auto-land is a policy decision, and the conservative default
  is that it may not: auto-landing leans on evidence recorded before the
  merge, and a deferred run is evidence that arrives after it. A `[tier1]`
  unit has no tier 2 result, and "not required" means exactly that.
- **The reviewer's classification is an input, never the decision.** The
  reviewer is asked to classify the unit as auto-land, light or full review
  against criteria written in its prompt (what touches a boundary, what is
  hard to undo, what the tests don't exercise). The answer is a closed set
  of values, validated against a schema, and the verdict takes the higher of
  it and everything else, so a reviewer can only ever make a unit need more
  review. A classification above the plan's estimate must name the groups or
  files behind it (`drivers`), which is what lets a held unit be split. The
  reviewer's `needs_human` and `escalate` outputs stay beside it: the
  classification says how much review a finished unit deserves, and those say
  the reviewer cannot settle a problem and a person has to, before there is a
  pull request to merge. The criteria in the prompt are policy under principle 5: in
  version control, changed through human review, out of the agent's reach.
- **Size is not a risk rule.** Principle 3 says size does not decide review,
  so the verdict does not raise a unit's tier because it is large. Step 5 does
  something different: it checks the unit against the ceiling of the tier it
  earned, plus a buffer, and sends it back when it is over. Size is otherwise a planning
  budget set by the review the unit is expected to get; see
  [Sizing work by expected review](#sizing-work-by-expected-review). Size also
  carries information about *rework*: large changes get sent back more often.
  That belongs in the per-class history below, where it moves the clean-merge
  rate, and not as a separate threshold.
- **Deletions are not a rule either.** A deleted file is a fact about the diff,
  not a risk. A move or rename (`git diff -M` reports it as a rename, not a
  delete plus an add) changes nothing about behaviour, and a real deletion
  whose tests still pass is covered by those tests. Where deleting matters
  (migrations, stored data, a public API, anything in a protected path) the
  protected list already catches it by path. The verdict records the counts
  of renames and real deletions in the PR body for a person auditing later.

Properties worth keeping in whatever the real version looks like:

- **Order matters.** Exclusions are checked before anything that could excuse
  them.
- **It can only go up a tier on any doubt.** Every branch that can't be
  satisfied resolves to more review, never less.
- **Missing evidence is not green.** A gate with no recorded result fails the
  check.
- **It explains itself.** The string returned says which rule decided, and goes
  into the PR body, so a person auditing an auto-landed change sees exactly why
  it qualified.
- **It is tested like any other code**, including cases that must *not*
  auto-land.

## What stays human

- Merging anything in the full-review tier, and skimming and merging the light
  tier.
- Every change to the auto-land policy, the exclusion list and the gates.
- Every `failed` unit, every verify failure, and every unit held for a reason
  other than a split in progress.
- Deciding what to build. Specs, priorities and `[acceptance]` stay human
  decisions, and a track's `propose` still produces a change that people
  prioritize.
- A regular look at what auto-landed: a sampled audit plus the trend in the
  metrics below.

## How the human's job changes

Today the human's job is to read every PR. In the new model it is to make the
decisions only a person can make, and to audit the system that makes the rest.

- **The queue is sorted by risk, not by arrival.** The PRs that need a person
  come first, each with a short "why this needs you" summary.
- **Auto-landed work goes into a digest, not a notification.** A person can
  read what landed and why, but is not interrupted for it.
- **Feedback returns to the policy.** When a person disagrees with something
  that auto-landed, the fix is a policy change, made through review, that
  stops it happening again. Rewording the reviewer's prompt is not enough.
- **The planning effort moves.** Careful specs and good `[acceptance]` matter
  more than before, because they are what auto-landed code is checked against.

## Measuring whether it works

The philosophy only holds if the numbers support it. These are the measures to
track:

- **Clean-merge rate by class of change:** the share of PRs of a given kind
  (docs, test-only, a narrow change in a given repo, a dependency bump) that a
  person merged *without asking for rework*. Shadow mode produces this for
  free. While every PR is still reviewed by a person, the verdict records what
  it would have done, and the history records whether a person then accepted
  the PR as-is, requested changes or reworked it. When a class has enough
  samples and a high clean-merge rate, it has earned auto-land. When the rate
  drops, the class loses it. The verdict above reads this history, so trust
  is granted per class, from a track record, and not for the pipeline as a
  whole.
- **Agreement:** of the changes auto-land would have accepted, the share that
  a person also accepted, measured in shadow mode before promotion and by
  sampling after it.
- **Escape rate:** reverts, incidents and verify failures traced to auto-landed
  changes, compared with reviewed ones.
- **Throughput:** time from a unit's build to its merge, and units in review
  waiting on a person.
- **Planner accuracy:** how often the tier the planner estimated differs from
  the tier the verdict gave, and how many units are held and split. A high rate
  means the estimate is too optimistic, or the criteria are too vague.
- **Review yield:** findings per human-reviewed PR. If it rises, attention is
  going where it matters. If it falls to near zero, the review tiers are too
  broad.
- **Auto-land share:** the external reports above suggest a realistic range of
  30–60%. A much higher share than that should be questioned, not celebrated.

Demotion is automatic. If the escape rate rises above what reviewed changes
show, or agreement falls below its gate, auto-land narrows or switches off
until a person has looked. Promotion is the opposite: a person adds a class to
the policy once its record clears the gates. The asymmetry follows from principle
5. Demotion only ever raises the review a change gets, so the pipeline may do it
alone, while loosening the policy stays a human edit.

## What this document does not decide

This document sets the philosophy and sketches the design. The
[design and implementation plan](risk-tiered-review-design.md) turns it into
mechanism, and that work will need to revisit these assumptions, which abk
currently relies on.

**Who merges, and what a unit's state says**

- **The README and `docs/architecture.md` say a human merges every PR.** So
  does the PR body footer (`pipeline/pr_body.py`), the skills (`abk-pipeline`,
  `abk-authoring`), `AGENTS.md` and installations' own planning docs, some of
  which state "no auto-merge" as a rule.
- **Merging is denied to the agent.** The policy hook (`hooks/policy.py`), the
  command policy (`pipeline/command_policy.py`) and `--disallowedTools` all
  forbid it, for every forge. Auto-land needs a narrow, policy-checked path to
  merge. That path probably belongs in the pipeline's deterministic code, and
  the build agent's permissions should stay as they are.
- **Units have one post-review state.** `in_review` is the only state after
  review, and only the poller seeing a merge moves a unit to `merged`. There is
  no state for "eligible to auto-land" and none for "landed without a person".
- **Notifications fire on every `in_review` unit.** The web UI's review tab
  likewise assumes a person handles every PR.

**What the reviewer and the verdict read**

- **The reviewer's output has no classification yet.** It returns
  `approved`, `findings`, `needs_human` and `escalate` today. The follow-up
  adds a tier classification and the `drivers` behind it, keeps the other
  fields, and must say how a missing classification is treated (as full
  review).
- **Tier 2 before merge becomes optional.** Today a `[tier2]` unit always runs
  it before the push. The follow-up adds the setting, and has to define what
  the verdict does with a unit whose tier 2 was deferred to `verify`.
- **There is no risk signal yet.** The task-group flags (`[contract]`,
  `[narrow]`, `[acceptance]`), the repo and tier tags, the reviewer's
  `follow_ups` severities and `estimated_lines` are the raw material for the
  planner's estimate. How the planner turns them into a tier is open.

**Planning and splitting**

- **Capacity limits assume the reviewer is the bottleneck.** That includes
  `project_limits.max_units_in_progress`, the stack-depth caps and the
  "reviewable in one sitting" reasoning behind `global_limits.max_unit_lines`, which
  is deprecated in favour of a ceiling per expected review tier. The floor,
  `min_unit_lines`, stays, to merge small groups.
- **A started unit can't be reshaped or superseded today.** Re-planning
  merges into the store by unit id, taking the shape from the plan and the
  state, branch and PR from what is recorded, and a started unit's groups don't
  change. Hold and split needs:
  - a hold cause for "too big for its tier", and a way to supersede a started
    unit without it counting as abandoned work;
  - a planner input that pins groups to a unit and a tier, and validation that
    the pinned unit fits that tier's ceiling;
  - a way for the new units, with new ids and branches, to reuse the commits
    already built, which needs the build to commit per group (today a unit
    has one tests commit and one implementation commit);
  - the `split_rounds` setting, default and maximum 2, and the rule that a
    failed re-plan uses a round.

Risk is judged twice: the plan's estimate sizes the unit, and the verdict on
the actual diff decides its review, with the higher tier winning. Hold and
split is what resolves a disagreement between the two.
