# Risk-tiered review: design and implementation plan

> **Status: implemented.** This is the record of the design; review by tier is always on.

[The philosophy](agent-efficient-coding-philosophy.md) says every change is
verified and a person reviews only what verification can't vouch for. This
document says what in abk has to change to work that way, and in what order to
change it. Review is currently the slowest part of the flow: builds arrive
faster than a person can read them, and the few that matter look like the
rest. That makes this a priority 1 change, and the sequence below is chosen to
relieve the reviewer first and to change merge behaviour last.

It is a design, not a specification. File paths and function names are where
the work happens today; setting and type names are proposals. Each phase in
[the implementation plan](#implementation-plan) becomes its own OpenSpec change.

## Goals and non-goals

**Goals**

- Every unit gets a review tier (`auto`, `light` or `full`) from a
  deterministic verdict, and the tier decides who merges it.
- A reviewer opening a pull request sees at once what matters most and why.
- Units are sized for the review they will get: large when the gates carry
  them, small when a person reads every line.
- The policy that decides all of this stays in the hands of people, and no
  agent can change it.

**Non-goals**

- No gate is weakened. Red-first tests, unit tests, e2e tests where tagged,
  and the independent review all still run.
- The build agent never merges. If anything merges without a person, it is
  pipeline code, and it is the only thing that does.
- Changing what gets built. Specs, priorities and `[acceptance]` stay human.

## What changes, and where abk assumes a human today

| Area | Where it lives today | What assumes a human reviews every unit |
|---|---|---|
| Review reply | `REVIEW_PROMPT` in `pipeline/wiring.py`; `Verdict`, `parse_verdict` and `weigh_review` in `pipeline/stack_runner.py`; the review node in `graph/nodes.py` | The reply is `approved`, `findings`, `needs_human`, `escalate`; it has no notion of how much review a change deserves |
| States and holds | `UnitState` in `pipeline/units.py`; `HeldBy` and `Cause` in `pipeline/unit_store.py` | `in_review` is the only post-review state; `open_pr` is the only way into it |
| Merging | `pipeline/events.py` `_record_merge`, reached only from the poller seeing a merge | Only a person's merge moves a unit to `merged` |
| Merge denial | `hooks/policy.py`, `pipeline/command_policy.py`, `forges/__init__.py` (`denies`), `runtimes/claude_code.py` (`disallowed`) | Every route to a merge is refused to the agent, and the `Forge` protocol (`forges/base.py`, `forges/operations.py`) has no merge method |
| After the merge | `pipeline/verify.py`, `pipeline/archive.py` | They read only the stored `merged` state and the PR number, which is why a self-merge must produce the same record |
| Sizing | `_check_ceiling` in `pipeline/planner.py`; `max_unit_lines` in `config.py` | One ceiling for every unit, set so a person can read a diff in one sitting |
| Build commits | `tests()` and `implement()` in `graph/nodes.py` | One tests commit and one implementation commit for the whole unit, however many groups it holds |
| PR text | `pipeline/pr_body.py` | The reviewer gets a summary but no ranking of what matters, and the footer says a human merges every PR |
| Attention | `notify/cards.py`, `pipeline/labels.py`, `pipeline/vocabulary.py`, `web/src/review` | A card, a label and a review tab for every `in_review` unit, in arrival order |
| Words | README, `AGENTS.md`, `docs/architecture.md`, the three skills | "A human merges every PR" is stated as a rule |

## Design

### Vocabulary: test tiers become `unit` and `e2e`

"Tier" already means the test tier (`tier1`, `tier2`). The new concept needs the
word, so the test tiers are renamed and the review tier takes "tier":

- **`TestTier`** is the enum for the test kind, with the values `unit-test` and
  `e2e-test`, the same strings as the tags. It replaces `work_graph.TIERS`, and
  the `tier` field of `Unit`, `StoredUnit` and `Kind`. The `-test` suffix keeps
  the tag apart from "unit" meaning a pull request's worth of task groups.
- **`ReviewTier`** is the new ordered `StrEnum`: `auto` < `light` < `full`.

The rename covers the internals, not just what people type, so the code reads
the same everywhere:

- Tags `[tier1]` and `[tier2]` become `[unit-test]` and `[e2e-test]`. They are
  words in a `tasks.md` heading, which the heading pattern in `work_graph.py`
  accepts for any text between the brackets, so they don't depend on the forge.
  The names a forge does see are PR labels and status contexts. Hyphenated names
  already work on both forges (`agent-hold` and `agent-rework` are labels today),
  and Azure DevOps splits a status context into a genre and a name, so
  `local/tier2` becomes `local/e2e-test`.
- `Node.TIER2` becomes `Node.E2E`; `Tier2Result`, `Tier2Schedule` and their
  neighbours follow, and so do the modules `pipeline/tier2.py`,
  `tier2_schedule.py`, `tier2_holds.py` and `tier2_times.py`.
- Settings `global_limits.tier2_*` and `tests.tier2_marker` become `e2e_*`.
  The `--tier2-test-time-limit` flag follows.
- State and output: `runs/tier2.lock`, `tier2-output/`, spans, log wording.
- Metrics `abk.tier2.*` become `abk.e2e.*`, with the catalogue helper
  (`tests/metric_names.py`) updated to match.
- Docs, the three skills and the test fixtures, including the recorded stores
  and the sample test reports.

The surface is large: about 48 source files, 272 test files and 11 doc files,
with about 80 test files and fakes carrying the old names in their own names.

Old names are accepted **only at the edges and only in one module**: tags in
`tasks.md`, keys in `abk.yaml`, and values already stored in `units.json` and
`planned.json` are read under their old names with a warning, for one release,
as for any renamed setting. Everything abk writes uses the new names. A guard
test, modelled on `tests/test_ecosystem_names_guard.py`, fails if an old name
appears anywhere outside that module.

The rename is far larger than any unit ceiling, so it is built as a **committed
codemod**, reviewed as the script plus its result, and applied in one pass.
Slicing it by hand would leave the code half-renamed for a long time. It will
conflict with every in-flight branch, so it lands when few units are running and
lets restack and adapt absorb the rest. Renamed metrics break any dashboard that
reads them, which the changelog must say.

### The review policy lives in `abk.yaml`

The policy is a new top-level `review:` section of `abk.yaml`, beside `global_limits`
and `tests`, plus a small per-repo `review:` block under each entry of `repos:`. It
is not a file of its own. This is the whole of it, with the defaults:

```yaml
review:
  enabled: false              # build-out feature flag; removed in the last phase
  ceilings:                   # lines a unit may hold, by the tier it is expected to get
    auto: 5000
    light: 2000
    full: 750                 # replaces global_limits.max_unit_lines (deprecated)
  ceiling_buffer: 0.2         # the verdict's allowance over a ceiling; the planner ignores it
  split_rounds: 2             # hold-and-split attempts per unit; 0 to 2
  brief: true                 # the "Start here" section of the PR body

  protected_paths:            # never auto-land, added to the framework's defaults
    - "deploy/**"
  protected_defaults: true    # false replaces the framework's defaults with this list alone

  classes:                    # named kinds of change, matched on the paths a unit changes
    docs:
      paths: ["**/*.md", "docs/**"]
    test-only:
      paths: ["tests/**", "**/test_*.py"]

  auto_land:
    classes: []               # the classes allowed to auto-land; empty is off
    min_samples: 20           # reviewed units of a class before it can qualify
    min_clean_rate: 0.95      # share merged without rework

  audit:
    sample_rate: 0.1          # share of auto-landed units a person is asked to check

  demotion:
    window: 30                # most recent units of a class considered
    min_agreement: 0.9        # below this, or on any revert, the class is demoted

repos:
  app:
    review:
      protected_paths: ["src/billing/**"]   # added to the global list, never replaces it
      ceilings: { auto: 3000 }              # optional; an unset tier follows the global one
```

**What each part is for**

- **`enabled`** is a feature flag for the build-out only. Review by tier is always on
  once it is finished, so the flag goes in the last phase and is not a long-term
  switch. Auto-land has its own off position: `auto_land.classes` empty.
- **`ceilings`** replace **`global_limits.max_unit_lines`, which is deprecated**: while
  it is still read it is mapped to `ceilings.full` with a warning, for one release,
  and then removed, the way the root `limits` key is already read as `global_limits`.
  **`global_limits.min_unit_lines` stays.** It is the floor the planner uses to merge
  small groups into one unit (`joins`), and it applies to every tier. Calibration
  ratios still apply.
- **`ceiling_buffer`** is used **only by the verdict.** The planner still plans to the
  plain ceilings. At review time a unit is over its tier's ceiling only when it
  exceeds the ceiling plus the buffer: 6000 lines for `auto`, 2400 for `light` and
  900 for `full` with the defaults. A replan and split is expensive, and a unit a
  little over is better sent through than split.
- **`protected_paths`** are the never-auto-land globs. The framework supplies
  defaults (migrations, CI and deploy configuration, secrets and the like) in code,
  not in YAML, so they can be tested and versioned with the tool. An installation
  adds to them, and sets `protected_defaults: false` only to replace them outright.
  A repo's own list is added to the global one for that repo and never narrows it.
- **`classes`** solve a problem the other class key can't. The verdict's history is
  keyed by a class of change, and the first class to auto-land, documentation or
  test-only changes, is a property of the paths changed, not of the repo, test tier
  and flag that `Kind` holds. A unit belongs to the first listed class whose globs
  match **every** path it changes, and to its `Kind` (`repo/test-tier`) otherwise.
  The matcher is `path_patterns.py`.
- **`auto_land.classes`** lists the classes that may auto-land; it is the only way to
  turn auto-land on. `min_samples` and `min_clean_rate` are also the bar a class has
  to clear to be eligible for anything lighter than `light` review.
- **`audit.sample_rate`** is how many auto-landed units a person is asked to look at
  afterwards.
- **`demotion`** sets when the pipeline demotes a class on its own (see
  [Records and metrics](#records-and-metrics)).

**Validation** (`config.py`, the same `Frozen` models that reject unknown keys):

- `ceilings.auto` ≥ `light` ≥ `full` > `min_unit_lines`, which extends
  `_ceiling_above_floor`, and the same for a repo's override once merged with the
  global one.
- `ceiling_buffer` between 0 and 1, and the buffered `auto` ceiling under the
  reviewer's own reading limit.
- `split_rounds` from 0 to 2.
- Every class named in `auto_land.classes` exists in `classes`, and class and path
  globs parse.
- `max_unit_lines` and `ceilings.full` both set is an error unless they agree.

**Where it is in the code**

- New `ReviewConfig`, `ReviewCeilings`, `ReviewClass`, `AutoLandConfig`,
  `AuditConfig` and `DemotionConfig` models in `config.py`, and a `RepoReviewConfig`
  on `RepoConfig`. `WorkspaceConfig` gains `review: ReviewConfig`.
- A helper that resolves the ceilings and protected paths in effect for a repo,
  mirroring how `tier2_unit_scope(repo, limits)` resolves a per-repo override
  against the global one today.
- The framework's default protected paths in a module of their own, and the class
  matcher beside the verdict.
- `abk doctor` checks that the section parses, that its globs match something in
  the repos, that the buffered ceilings are sane, and that `max_unit_lines` is
  flagged as deprecated. It also warns when `auto_land.classes` is not empty and a
  forge reports no branch protection (see [Auto-land](#auto-land)).
- A digest of the sizing settings (the ceilings and the review flag) is recorded
  beside each plan's hash, which matters for [migration](#migrating-open-changes).
- `docs/configuration.md` gets the reference block above, the `abk-config` skill a
  section on it, and `abk init`'s template a commented copy.
- Tests: a new `tests/test_config_review.py` for the schema and validation,
  `tests/test_config_global_limits.py` for the deprecated alias, the doctor tests,
  and `tests/hooks/test_policy*.py` for the fence.

**Settings that live elsewhere.** Not everything new belongs in `review:`.
Running e2e tests before merge optionally is a testing setting and follows the
existing e2e settings, global with a per-repo override. The switch for per-group
commits and stubs belongs with the build settings. Each is named in the spec of
its phase.

Keeping the policy in `abk.yaml` and not in a file of its own has three reasons:

- It is validated like everything else in the file, and `abk doctor` already reads
  it.
- The planning repo is already fenced from build agents by `hooks/policy.py`
  (`_may_write_planning`), and from a track's `propose`, which writes only inside a
  change. A test must pin that, because principle 5 depends on it.
- There is no second place to keep in step.

The cost is that `abk.yaml` holds installation facts and now policy too, and a
policy change is a reviewed edit to `abk.yaml`.

### The verdict

A pure function in a new `pipeline/verdict.py`, implementing the sketch in the
philosophy. Every input is a fact already stored: the planned tier, the changed
paths, the flags of the groups the unit builds, the recorded gate results, the
reviewer's classification and drivers, and the per-class history. It returns a
tier and the reason, or a hold-and-split. It makes no model call and is tested
by tables, including the cases that must not auto-land.

It runs **after every review round**, not only at approval. Each run uses what
is recorded at that moment, so the record is interim until the round that
approves makes it final. That is what lets a unit that will be split be held at
the first round that shows it, before more rework is spent on it. A gate that
runs after review (the e2e-test before the push) is pending in an interim
verdict, counted as met, and missing in the final one. A reviewer's escalation to
a person comes first: a held unit has an interim verdict and no final one.

### Reviewer classification and drivers

The review reply gains two fields, added without removing anything:

- `classification`: `auto`, `light` or `full`, a closed set validated against
  the schema. A missing or unparseable value counts as `full`, and the reviewer
  can only raise a tier.
- `drivers`: the groups or files behind a classification above the plan's
  estimate, which hold-and-split needs.

`parse_verdict` keeps its rule of never raising. **`needs_human` and `escalate`
stay.** They answer a different question from the classification: how much review
a finished unit deserves is one thing, and whether the reviewer can settle a problem
at all, before there is a pull request worth opening, is another. A reviewer that
cannot resolve something still hands it to a person, as it does today, and the
classification neither clears nor sets that. A held unit has no final verdict.

### The review brief, and better git descriptions

Today the reviewer writes a `description` (a summary and three to six changes)
only on approval, `pr_body.py` leads with "Why" and "What this pull request
does", and commits are titles only (`test: <title>`, `feat: <title>`). A
reviewer still has to work out what matters. The brief changes that:

- The review reply gains a ranked **focus list**: what a person should read
  first and why. The reasons are the same kinds of things the verdict uses: a
  boundary another system depends on, a behaviour change, something hard to
  undo, a path with thin test coverage.
- It also gains a **skippable list**: mechanical moves, renames, generated or
  formatting-only changes, with the reason each is safe to skip.
- And a short **verified** list: what the pipeline already checked (the red
  run, unit and e2e results, the reviewer's rounds), so a person doesn't redo it.
- The PR body opens with these under "Start here", followed by the review tier
  and its reason, ahead of "Why". It is a fixed section in `build_pr_body`'s
  size fitting, so a long description can't push it out. A unit held for a
  person carries the same brief.
- Commit messages gain a body of a sentence or two saying why, not only what.

This is independent of any merge behaviour, so it can ship early. Its tests
extend `tests/pipeline/test_review_description.py` and the PR body tests.

### Stubs in the test node, and per-group commits

Today the test step allows stubs (signatures that raise `NotImplementedError`),
and one tests commit plus one implementation commit cover every group of a
unit. Two changes:

- **The test node must write the stubs** so the tests pass static analysis
  (lint and types) at the test commit. A test that fails to import, or a
  signature a type checker rejects, is not a meaningful red.
- **The build commits per group**: stubs and tests for a group, then its
  implementation, one pair after another.
- **The test node checks and fixes its own work before the build starts.** After
  the agent writes the stubs and tests, the pipeline runs the static checks over
  what it wrote: lint, format and types, which is what the repo's pre-commit
  checks cover. A failure is saved as feedback and handed back to the test
  agent with the same kind of fix prompt the build's check step uses
  (`fix_checks` in `graph/nodes.py`), and the checks run again. It repeats up
  to a limit, with its own round counter and the same limit setting as the
  build's checks (`global_limits.max_check_rounds`), and a unit still failing
  when it runs out stops, with the output kept, before any implementation is
  attempted. The tests themselves are not run here, since they are meant to be
  red. This is a new loop in the test node (or a node of its own just after it)
  and the profiles need a static-checks command that includes types.

The benefits:

- The red run fails for the right reason, an assertion or `NotImplementedError`
  and not an import or type error, which is stronger evidence. `red_check.py`,
  `commit_order.py` and `abk gate` need to know what a good red looks like.
- A group's commits can be cherry-picked onto another branch, which is what
  [hold and split](#hold-and-split) needs to reuse built work.
- A person can review commit by commit.

Today `clean_command()` (the profile method the push gate uses at the tests
commit) checks lint and format and skips types, because a test could import a
stub that did not exist yet. With stubs required, the gate's check includes
types, and it stays as the final enforcement behind the earlier fix loop: the
loop gives the test node the chance to fix what the gate would otherwise refuse
at push time, after the whole build has run.

The cost is a change to the core build loop. It ships behind a setting and
becomes the default once it has run for a while. Some toolchains make stubs
awkward, so the profiles (`docs/toolchain-profiles.md`) declare whether they
support them, and a profile that doesn't keeps today's single pair.

### Per-tier sizing and the planner's estimate

The planner returns an expected review tier for each unit, **from Phase 1**, so
the verdict has a real planned tier from the start. In Phases 1 to 5 the estimate
is recorded and only raises the verdict's floor; it sizes nothing. A deterministic floor
sits under the model's answer: a group flagged `contract`, `narrow` or
`acceptance` is `full`, and so is a group whose task text names a protected
path. `_check_ceiling` then uses the ceiling for the unit's tier, and a group
that expects full review may not share a unit with auto-land groups, so the
large units stay large and the PR a person reads stays small.

The new ceilings take effect only when the build-out flag (`review.enabled`)
turns sizing by tier on, in the hold-and-split phase. Until then
`max_unit_lines` alone governs, so shipping the keys grows no unit. Once the
flag is gone, the tier ceilings are the only ceilings, and `max_unit_lines` is
removed after its deprecation release. The planner and `_check_ceiling`
use the plain ceilings; the `ceiling_buffer` is applied only by the verdict, when it
decides whether a unit that earned a higher tier must be split. `unit_size.Kind(repo, tier,
flag)` is the first key for a class of change. It is coarse, and widening it is
an open question.

### Auto-land

Pipeline code merges; the build agent never does. The pieces:

- **A merge method on the `Forge` protocol**: squash on GitHub, the matching
  call on Azure DevOps, never on the local forge. It needs an entry in
  `forges/operations.py` for retries, like every other protocol method.
- **A landing step** after review, run by the pipeline when the verdict says
  `auto` and the class is enabled. It reads the pull request's check status
  itself, because a repo may have no required checks (`doctor`'s merge guard
  only reports that as information).
- **The same record as a person's merge.** The unit goes to `merged` through
  `_record_merge` with a new `Cause.AUTO_LANDED`, so restack, cleanup, verify
  and archive work unchanged. The poller's later `merged` event for the same PR
  must be a no-op, so `_record_merge` has to be idempotent for it.
- **Squash and stacks.** The pipeline already assumes squash merges and handles
  squashed parents by patch identity (`restack.py`), so a self-merge keeps that
  method. A stacked child is retargeted and restacked as for any merge.
- **Safety.** No class is enabled by default, and a class is turned on one at a
  time; turning every class off is the off switch.
  `abk doctor` warns when auto-land is enabled and the forge reports no branch
  protection, since the command-policy hook is then the only guard and does
  nothing against the pipeline's own merge. The `acp` runtime ignores the
  deny lists, which needs a note.
- **The agent's denial is unchanged.** `command_policy.py`, the hook and
  `--disallowedTools` stay as they are, because the merge is not a shell
  command. Only the message in `command_policy.py` that says a human merges
  every PR changes wording.

### Hold and split

A unit that earns a higher tier than it was sized for, and is over the new
tier's ceiling plus the `ceiling_buffer`, is held and split. The buffer keeps
the expensive path for units that are clearly too big: a unit within 20% of its
tier's ceiling goes to review as it is, and a person can still ask for rework.
The mechanism:

- **A hold cause** for "too big for its tier": new `HeldBy` and `Cause` values.
  It is not a failure and doesn't use the ordinary review rounds.
- **Superseding a started unit.** A started unit's shape is fixed today:
  `UnitStore.upsert` keeps state, branch and PR, and `_STARTED` in
  `cli/pipeline.py` makes its groups count as taken. The held unit becomes
  superseded: `closed` with a cause and a `superseded_by` field. Everything that treats a unit as in progress or as satisfying a
  dependency has to know the difference: `_taken_groups`, `_gone_groups`,
  `in_progress` in `units.py`, the reviewed and satisfied checks, PR closing and
  the poller's PR-to-unit map.
- **A planner input that pins groups.** `plan_round`, `build_prompt` and
  `parse_plan` take the drivers and a tier. The prompt says the pinned groups go
  in a unit of their own at that tier, and a deterministic `_check_pins` next to
  `_check_groups` refuses a plan that ignores it, as the planner already
  refuses rather than repairs. `_check_dependencies` still validates the order.
- **New unit ids.** A branch name derives from the unit id (`branch_name`), so
  each piece needs an id that can't collide with the superseded unit's. The id
  extends the parent's (`<parent id>-s<k>`), because readers parse the last
  segment of an id as a number.
- **`split_rounds`**, with a maximum of 2 and its own counter. A re-plan that
  fails or doesn't validate uses a round. When rounds run out, or a single group
  is over its ceiling, the unit is held for a person.
- **Reusing the built work** by cherry-picking each group's commit pair onto the
  new branch. This is why per-group commits come first. Until they exist, a
  split rebuilds the pieces and keeps the old branch under a ref, which is
  correct and costly, and rare because the planner estimates high when unsure.

### e2e before merge, optional

`Node.E2E` (today `Node.TIER2`) and the moved-base re-run get a setting that
turns them off before merge. The unit records the result as `deferred`, and
`verify` still runs the live e2e tests after the merge. The verdict reads three
states for an e2e unit (passed, deferred, failed), and a deferred unit does not
auto-land unless policy says so.

### Triage and notifications

- Labels per review tier, so the queue shows what needs a person at a glance.
- `abk status` and the review tab order by tier, and the tab shows the tier and
  why next to the brief.
- Cards (`notify/cards.py`) are raised for `light` and `full` units only. A new
  digest card kind reports what auto-landed, using `notify/reconcile.py`'s
  existing timing and store, so nobody is interrupted for it.

### Records and metrics

There is no durable record of "merged without rework" today; `StoredUnit.history`
can derive rework after the fact, but nothing stores a verdict. The design adds:

- A per-unit **verdict record** (`runs/verdicts.json`, listed in the state-on-disk
  table in `docs/architecture.md`): the planned tier, the verdict, its reason and
  drivers, the paths the unit touched, and later the outcome, derived from
  `history`, and whether the unit's PR carried the review brief, since calibration
  counts only units that did. The class is the first named class in `review.classes` whose globs
  match every path the unit changed, and `Kind(repo, test tier, flag)` otherwise;
  because the paths are stored on every record, the classes can be redefined
  later and the history re-derived without a migration. A unit planned before Phase 1 has no recorded
  estimate; it gets no floor from the plan, the verdict relies on its other
  inputs, and its record says so, so the planner-accuracy metric can leave it out.
- New instruments such as `abk.verdict{tier,planned,agreement}`, auto-land
  counts and reverts, added to the metric catalogue.
- A measure of how the buffer is used: how many units landed between their
  ceiling and the buffered ceiling, and how those fared on rework and reverts
  compared with units under the ceiling. It is how the 20% default gets tuned.
- The promotion and demotion rules from the philosophy: a class earns auto-land
  from its clean-merge record, and loses it when auto-landed work is reverted or
  agreement falls.

**Promotion and demotion.** The two are asymmetric, because policy is human-owned.

- **Promotion is a person's edit.** The classes allowed to auto-land are listed
  in `review:` in `abk.yaml`. When a class's record clears the gates, `abk status`
  says so, and a person adds it to the list. The pipeline never edits the file.
- **Demotion is the pipeline's, and it is a runtime override.** When an
  auto-landed unit of a class is reverted, fails `verify`, or is found wrong in an
  audit, or when the class's agreement or clean-merge rate falls below its gate,
  the pipeline records a demotion in `runs/` (not in `abk.yaml`). The verdict reads
  it as one more floor that holds that class at `light`. Only a person lifts it,
  with a command, and every demotion and every lift is logged and raised as a
  notification. Demotion only ever raises the review a change gets, which is why
  the pipeline may do it alone without breaking "no agent edits the policy".

### Migrating open changes

Existing changes are planned once, and again only when a change's `tasks.md`
changes (the hash in `runs/planned.json`). Ceilings and policy are not in that
hash, so raising the ceilings leaves every open change planned at 750-line units
with no review tier, and nothing replans them. Folding them into the hash is not
the answer: the next tick would replan every open change unattended, at the cost
of a planner call each.

- **Detection.** Each plan's record carries a digest of the sizing settings,
  kept beside the `tasks.md` hash and not inside it (added in the sizing phase).
  A change to the ceilings or the review flag marks plans stale, and `abk
  status` and the tick list them instead of replanning them. A plan recorded
  before the digest existed reads as empty, so upgrading with the flag off marks
  nothing stale.
- **Scope.** A change with no started units is replanned whole. For a partly
  started change only the unstarted remainder is replanned: `UnitStore.upsert`
  never touches a started unit, and its groups are marked `(built by …)` and
  counted as taken. Merged and started work keeps its shape and has no verdict
  history, so a class's history starts empty.
- **Mechanics.** `abk replan` already drops the recorded plan, asks the planner
  and links `Needs:`, and `upsert` reshapes planned units and demotes ones the
  plan drops to `unplanned`. Four additions: a **report mode** that shows what
  each change's units would become (tier, size, joins, dropped units) before any
  model call is spent, since `replan` today reports only the call count; a
  mechanical rewrite of `[tier1]` and `[tier2]` tags in open `tasks.md` to
  `[unit-test]` and `[e2e-test]` (`abk tags --fix`); a move of the old settings keys
  in `abk.yaml` to their new names, and of `max_unit_lines` to
  `review.ceilings.full`, by `abk config --migrate`; and guidance in `abk-authoring` that groups need no
  longer be split to dodge the size ceiling, only to say what they touch so the
  planner can estimate a tier.
- **Sizes.** Groups authored small to fit 750 lines may now be joined into
  larger units (`joins`, `min_unit_lines`), while any full-review group stays in
  a unit of its own.
- **Safety.** Migrate by priority and a few changes at a time, honouring the
  planner's attempt and wait handling. A refused plan keeps the old plan and is
  reported. Demotions to `unplanned` are listed for a person before anything
  acts on them. Rollback is `abk replan` under the old ceilings.

## Implementation plan

Each phase is one OpenSpec change, written with `Priority: 1`, and ships on its
own. The order puts relief for the reviewer first, then merge behaviour, then
sizing, and keeps every risky change switched off until the evidence is in.

| Phase | Ships | Depends on | Changes behaviour? |
|---|---|---|---|
| 0 | `TestTier` rename (`unit-test`, `e2e-test`) | nothing | no; names only |
| 1 | `review:` policy in `abk.yaml`, `ReviewTier`, the planner's tier estimate, verdict module, reviewer classification and drivers, verdicts recorded | 0 | no; shadow only |
| 2 | Review brief and git descriptions | 1 | PR text only |
| 3 | Triage by predicted tier, verdict and outcome records, metrics; calibration starts here | 1, 2 | ordering and labels only |
| 4 | Auto-land for the narrowest class | 1, 2, 3's calibrated data | yes, per class |
| 5 | Stubs and per-group commits | nothing | build loop, behind a setting |
| 6 | Per-tier ceilings used for sizing, sizing digest, dormant | 1 | no until enabled |
| 7 | Hold and split, then per-tier sizing switched on | 5, 6 | yes |
| 8 | Migration of open changes | 6, 7 | replans unstarted work |
| 9 | e2e before merge optional | nothing | yes, behind a setting |
| 10 | Remove the build-out flag and `max_unit_lines`; finish docs, skills and wording | all | cleanup |

### Phase 0: vocabulary

The full rename above, with the compatibility edge and the guard test. It goes
first because every later phase is written once, in the new words, and because
the collision between the two meanings of "tier" would otherwise run through
all of them.

- **Tests to extend:** every test that names the old terms moves with the code;
  the guard test is new; `tests/test_config*` gains the alias cases.
- **Exit:** no old name outside the compatibility module; old tags, keys and
  stored values still load with a warning.
- **Rollback:** the aliases make a revert safe for one release.
- **Main risk:** conflicts with in-flight branches and the size of the change.

### Phase 1: policy, verdict and classification, in shadow

The `review:` section and its validation, `abk doctor`'s check of it, the
`ReviewTier` enum, the planner returning an expected review tier with its
deterministic floor (recorded, not yet used for sizing), `pipeline/verdict.py`,
the reviewer's two new fields, and the verdict computed and stored after every review round, for every
unit, with the planner-accuracy metric reading the estimate against the verdict. Nothing in the pipeline acts on it
yet. The test that a build agent and a track can't write `abk.yaml` goes in here.

- **Tests to extend:** `tests/pipeline/test_review_verdicts.py` and the review
  fixtures, `tests/pipeline/test_planner*.py` for the new field, `tests/hooks/test_policy*.py`,
  `tests/test_config*`, the doctor tests.
- **Exit:** every new unit has a recorded planner estimate and verdict, and a
  missing classification is `full` in the record.
- **Rollback:** the `review.enabled` build-out flag stops the recording.
- **Main risk:** reviewer prompt drift. The classification criteria in the
  prompt are policy, so they live in version control and change by review.

### Phase 2: the review brief and git descriptions

The focus, skippable and verified lists, the "Start here" section, and commit
bodies. It comes before any merge change because it helps every review that
remains, whatever the tiers end up being.

- **Tests to extend:** `tests/pipeline/test_review_description.py`, the PR body
  tests, `tests/pipeline/test_wiring.py`.
- **Exit:** a reviewer opening any new PR sees the ranked list first.
- **Rollback:** a setting turns the section off and falls back to today's layout.
- **Main risk:** a ranking that is confidently wrong. Phase 3's agreement data (which only starts counting after this phase)
  shows whether the focus list matches what people actually changed.

### Phase 3: triage and shadow data

Labels and ordering by predicted tier in `abk status`, the notification cards and
the review tab; the outcome records; the metrics. This is where the data the
auto-land decision needs starts to accumulate, and **calibration starts here, not
earlier**: the clean-merge rate, the agreement rate and the thresholds are
measured only on units whose PR carried the new description from Phase 2. What a
reviewer asks to be reworked depends on what the description tells them, so a rate
measured on the old descriptions would be calibrated to a baseline that no longer
exists. Verdicts recorded in Phase 1 stay, and are marked as made before the brief;
the calibration leaves them out.

- **Tests to extend:** `tests/notify/`, `tests/pipeline/test_state_labels.py`,
  the status tests, the web tests under `web/src/review`, the metric catalogue
  helper.
- **Exit:** per class, the agreement rate and the clean-merge rate are readable
  from the records, counting only units whose PR had the Phase 2 description, and
  no threshold is calibrated from a unit that did not.
- **Rollback:** ordering falls back to arrival order.
- **Main risk:** none to merging; this phase only reorders.

### Phase 4: auto-land

The merge method on the forge protocol, the landing step, `Cause.AUTO_LANDED`,
the check-status read, per-class enablement, the doctor warning and the digest card.
Enable it first for the narrowest class, documentation and test-only changes, and
promote a class only when its calibrated record from Phase 3 clears the gates.

- **Tests to extend:** `tests/forges/` using the stand-in forge,
  `tests/pipeline/test_events*.py`, `tests/pipeline/test_pr_poller*.py` for the
  idempotent merge record, the verify and archive tests, and a local-stack test of
  one landed unit end to end.
- **Exit:** a documentation-only unit lands without a person, and verify and
  archive run on it as on any merged unit.
- **Rollback:** disable the class; units already landed are ordinary merges.
- **Main risk:** merging without branch protection, a stacked child's base, and
  the squash assumption. Phases 5 and 6 proceed while this one waits for data.

### Phase 5: stubs and per-group commits

The test node writes stubs that pass static analysis and fixes any lint, format
or type failure itself, in a check-and-fix loop, before the build starts; the
build commits per group; the push gate's `clean_command` includes types. Behind a
setting first.

- **Tests to extend:** `tests/graph/` for the tests and implement nodes and the
  new loop, `red_check` and `commit_order` tests, the push gate tests
  (`pipeline/gate.py`), the toolchain profile tests.
- **Exit:** a multi-group unit has a commit pair per group, each red for the
  right reason, and a lint or type failure in the stubs is fixed in the test
  node and never reaches the push gate.
- **Rollback:** the setting returns to one pair per unit.
- **Main risk:** toolchains where stubs are awkward, and a longer build.

### Phase 6: per-tier ceilings and the planner's estimate

The three ceilings as settings (5000, 2000, 750), `_check_ceiling` and the
planner prompt using the ceiling for the unit's estimated tier, and a sizing
digest recorded beside the plan's hash so stale plans are reported. The estimate itself arrived in Phase 1. All
of this is dormant until `review.enabled` turns sizing on.

- **Tests to extend:** `tests/pipeline/test_planner*.py`,
  `tests/test_config_global_limits.py`, `tests/pipeline/test_unit_size_*.py`.
- **Exit:** with the flag on in a test installation, units are sized by tier.
- **Rollback:** nothing is active, so nothing to undo.
- **Main risk:** the estimate being optimistic, which Phase 7's holds then pay for.

### Phase 7: hold and split, then sizing on

The hold cause, superseded units, pins and `_check_pins`, `split_rounds`, and
cherry-picked commit reuse. Then `review.enabled` turns per-tier sizing on, which
is what makes 5000 and 2000 take effect.

- **Tests to extend:** `tests/pipeline/test_unit_store*.py`, `test_units.py`,
  `tests/cli/test_replan_units.py`, `tests/graph/test_hold_causes.py`, the poller
  tests for the PR-to-unit map.
- **Exit:** a unit planned `auto` that earns `full` while over 900 lines (750
  plus the 20% buffer) is split into units that each pass, within two rounds, or
  is held for a person; one at 800 lines goes to review as it is.
- **Rollback:** switch sizing off; superseded units stay as records.
- **Main risk:** the superseded state touching many readers of unit state.

### Phase 8: migrating open changes

The report mode, the tag rewrite, the replan of unstarted work and the authoring
guidance, as in [Migrating open changes](#migrating-open-changes).

- **Tests to extend:** `tests/cli/test_replan_units.py`,
  `tests/cli/test_replan_started_tags.py`, the tags tests.
- **Exit:** every active, unstarted change has a plan with a tier per unit and
  sizes within that tier's ceiling, and `abk status` reports no stale plan.
- **Rollback:** `abk replan` under the old ceilings.
- **Main risk:** the cost of the planner calls and a plan the planner refuses.

### Phase 9: e2e before merge optional

The setting, the `deferred` record, and the verdict's three states. It touches
nothing else, so it can run in parallel with Phases 4 to 8.

- **Tests to extend:** `tests/graph/test_tier2_*` (renamed in Phase 0),
  `tests/pipeline/test_tier2_*`, the PR body tests.
- **Exit:** with the setting off, a unit reaches review without an e2e run and
  `verify` runs it after the merge.
- **Rollback:** the setting.
- **Main risk:** problems found later than they would have been.

### Phase 10: remove the scaffolding, finish the words

The reviewer's `needs_human` and `escalate` stay. The `review.enabled`
build-out flag is removed, so review by tier is simply always on; the deprecated
`global_limits.max_unit_lines` is removed; the README, `AGENTS.md`,
`docs/architecture.md`, `docs/configuration.md`, `docs/cli.md`, `docs/code-forges.md`,
`docs/designs/unit-graph.md` and the three skills stop saying a human merges every PR;
the PR footer and the message in `command_policy.py` change wording; one
changelog bullet per change. Docs that describe a phase's behaviour are updated
in that phase, and this one sweeps what is left.

## Risks and open decisions

- **The planner's estimate.** A wrong estimate costs a split. The planner is told
  to estimate high when unsure, and the planner-accuracy metric (live from Phase 1)
  says whether it does.
- **Classification drift.** The reviewer's criteria are policy: they live in version
  control, change by review, and are out of every agent's reach.
- **Self-merge without branch protection.** The pipeline checks the status of the
  checks itself, the doctor warns, and no class is enabled until someone turns it on.
- **Stacked children.** A parent that auto-lands moves its children's base, the
  same as any merge. This needs a test of its own.
- **The `acp` runtime ignores the deny lists**, so the merge denial depends on the
  runtime. Phase 4 documents it.
- **Class of change.** Named path classes in `review.classes`, with `Kind(repo,
  test tier, flag)` as the fallback, which needs few samples. Touched paths are
  stored on every record, so classes can be redefined and the history re-derived.
- **Stubs on awkward toolchains.** Profiles opt in; a profile that can't keeps
  today's pair.
- **Priority 1 doesn't bypass limits.** It sorts these changes first, but
  `project_limits.max_units_in_progress` and the stack-depth caps still apply, so Phases 0
  and 5 in particular should be sized to fit them.

## Process

This document is documentation, so it can be edited in a session. The code is
not: each phase is an OpenSpec change authored with the `abk-authoring` skill,
with `Priority: 1`, and with `[contract]` or `[acceptance]` where it crosses a
seam (the forge protocol, the store's schema, the config). `abk check` and `abk
tags` must pass first. The pipeline's own review bottleneck is the reason the
phases that help a reviewer come before any that changes who merges.

Tests follow the layout rules in `AGENTS.md`. Run `uv run poe test`,
`poe format` and `poe scrub` for each phase, and the `local_stack` tests for
Phase 4.
