---
name: abk-authoring
description: TRIGGER — read before writing or editing a change's tasks.md in a planning repo, before choosing a task group's [repo] [kind] tags or [contract]/[narrow]/[acceptance] flags, or when `abk tags` reports a problem. SKIP for questions about running the pipeline (abk-pipeline) or about abk.yaml (abk-config).
version: 1.2.0
generatedBy: agent-build-kit
---

# Writing a change the pipeline can build

The pipeline turns a change's `tasks.md` into units of work — branches and
PRs — without reading anything else about it. Two facts therefore have to be
on every task group heading: which repo its code lands in, and which test kind it needs. They are written as tags, and `abk tags` checks them. The build agent never merges: a person merges what was
not auto-landed.

## The heading contract

```
## <n>. [<repo>] [<kind>] <title>
## <n>. [<repo>] [<kind>] [<flag>] <title>
```

- `<n>` numbers groups from 1, in the order they are built. Gaps and
  reordering are errors: the number is the build order.
- `<repo>` is one of the workspace's repo names exactly as `abk.yaml` spells
  them. A near miss (a capital, an underscore) is an error, not a guess.
- `<kind>` is one of three test kinds, from narrowest to widest: `unit-test` (one module's
  behaviour, in the ordinary suite run in CI), `integration-test` (behaviour across modules or
  files, in the ordinary suite with no live stack) or `e2e-test` (needs the real local stack,
  serialized on one host). `integration-test` is a label: it behaves as `unit-test` in every
  other way, and it is not the pytest `integration` marker or `tests/integration/`. A unit of
  several groups takes the widest kind. The earlier spellings of the two older kinds are still
  read as the same kinds, with a deprecation notice from `abk tags` and `abk check`.
- Choose the kind by what the test needs running. A step that needs a running service (a
  server, a database, a broker, `docker`) is `[e2e-test]`. `[integration-test]` is across
  modules of one package and needs nothing running. Under the sandbox a unit-test or
  integration step cannot reach localhost or a service socket, so a refused loopback
  connection in its output means the group should be tagged `[e2e-test]`.
- `<repo>` may carry a project: `[app/web]` is the project `web` of repo `app`, spelled as
  the path the repo declares for it. A project the repo does not declare is refused, by
  `abk tags` and by planning, with the file and line. Groups of different projects of one
  repo become separate units.
- `<flag>`, optional, is `contract`, `narrow` or `acceptance` — see below.

Under each heading, tasks are checkbox lines numbered within the group:

```
## 1. [app] [unit-test] Add the marker

- [ ] 1.1 Test: `tests/markers/test_registry.py` asserts the marker is listed
- [ ] 1.2 Register the marker in `src/markers/registry.py`
```

Rules `abk tags` enforces:

- Every group has at least one task.
- A group never spans repos. Work in a second repo is a second group with
  its own tag, and the planner never combines groups from different repos
  into one unit.
- Test tasks come before implementation tasks: the unit's first commit is
  the red tests.
- New test files go where the repo's layout says: mirroring the source
  folder, integration tests under `tests/integration/`.
- A `[e2e-test]` group (every `[acceptance]` group is one) is test-only: a stubbed build
  commits it as one `test:` commit and writes no implementation for it, so its tasks are tests
  alone. A `[unit-test]` or `[integration-test]` group still needs its implementation tasks.

## Flags

**`[contract]`** marks a group that widens a shape another repo consumes —
a field on a shared model, an event's payload, a tool's surface. The two
repos are never at the same commit, so callers of both shapes exist for a
window: the widening lands alone, and something removes the old half later.

**`[narrow]`** is that something. Required whenever a `[contract]` group
exists, and it must be the last group of the change: its unit depends on
every unit that migrates a consumer, and nothing depends on it. A change named `fix-test-*` (the
fix of a failing test) is the one exception: it carries `[contract]` for the full review that
flag floors and needs no `[narrow]` group. A unit stores only its direct
dependencies (`direct_dependencies`: a dependency another one of its dependencies reaches is
not stored), and a `[narrow]` unit waits for every earlier unit of its change, computed at run
time and not from stored edges.

This is only for contracts that cross a repo boundary. A shape and its
callers inside one repo land in the same commit; nothing needs flagging.

**`[acceptance]`** marks the group that drives what the change built the way
its consumer does — a scripted run of the tool as a real client, a request
through the public route. It waits for every earlier unit of its change, computed at run time,
while storing only the end of its chain and the independent units. It is always `e2e-test`, comes after every group it
exercises (only a `[narrow]` group may follow it), and gets a unit of its
own. Every change has one, or opts out with a line anywhere in `tasks.md`:

```
Acceptance: none — a refactor; nothing a consumer sees changes
```

The reason is what review agrees to; the line without one is an error. Write
`Acceptance: none — reason` and nothing else on that line: `Acceptance:` followed
by a description of a test reads as requiring an `[acceptance]` group.

In `tasks.md` the first heading is `# Title`. A `## Change:` heading leaves the
group unreadable, and the change is not planned.

```
## 1. [platform] [unit-test] [contract] Accept the new field, keep the old one
## 2. [app] [unit-test] Send the new field
## 3. [app] [e2e-test] [acceptance] Drive the route end to end as a client
## 4. [platform] [unit-test] [narrow] Drop the old field
```

## Say which files and paths a group touches

The planner sizes a unit by the review tier it expects, and estimates the tier from the task text. Say in each
group which files, boundaries or behaviours its tasks touch (a migration, CI or deploy config, a protected
path, a public contract) so the expected tier can be estimated, without naming functions. A group need not be
split to fit a single ceiling: the planner combines and separates groups itself, and a group over its unit's
ceiling is reported for a person to split. When a built unit passes its tier's buffered ceiling and the reviewer
names the groups that drove its tier (its drivers), the pipeline splits those groups out into units of their own;
`tasks.md` is not changed by the split, so a driver group needs no rewriting there.

Name the file a task changes. A group whose test task names a test file and whose implementation task
names nothing used to read as one that edits only test code, so `abk tags` showed it as `tests_only` and the
build wrote its tests and no implementation. A task that is not a `Test:` task and not a check (a task that
begins `Confirm`, `Check`, `Verify` or `Read`) must name a path, in backticks or as a word of a backticked
command, or the group is built with tests first and then code. The rule reads whether a task names a path, not
what the path is: a task that describes code in prose and also names a document or a test file reads as
placed, and so does a backticked name with a dot (`tracker.start`). Say `Tests: required — <reason>` on a
group where that would be wrong. A group that really edits only test code, and has a task that names no path
(deleting the originals, noting something in the pull request), lists its files in a `Paths:` line, which says
what the group names and turns the rule off.

## `Manual:` lines

Declare `Manual: <slug> — <what to do> — runbook: <path>#<heading>`, with an optional
`Check: <command>`, for any step only a person can do. Give it a runbook entry (the slug as a
heading); `abk tags` warns when the file or heading is missing. The unit waits until the check
exits 0.

## `Needs:` lines

A group that cannot pass until a group of *another* change has landed says
so on a line inside the group:

```
Needs: <other-change> group <n> — why
```

The planner orders groups within a change on its own; across changes it only
sees what is already in flight, so a dependency that must hold is written
down and applied as code.

Two kinds of edge come from a `Needs:` line. A review edge starts the dependent on the
parent's branch once the parent is in review. A merge edge holds the dependent until the parent
has merged and a later tick has the merge in the code it runs. An edge is a merge edge for three
reasons only: it crosses repositories, the line says `merged` straight after the group number,
or its dependent is a failed unit waiting on the parent. A plain `Needs:` to a group of another
repository is read as a merge dependency, and `abk tags` and `abk check` say so in an info note.
A fix change a failed unit waits on needs no `merged` line.

Write `merged` only when the dependent must run against a parent's change that is loaded
by the tools that build and check it (shared code, a generated file, a setting the pipeline
reads), where a branch stacked on the parent would not show it. Otherwise write a plain line.

```
Needs: add-marker group 2 — the dependent only reads the marker the parent registers
Needs: shared-config group 1 merged — the build reads the setting this group adds
Needs: api-change group 3 — another repository; read as a merge dependency
```

A `Needs:` the chain already implies (the unit reaches the target through its dependencies) is
recorded but not linked, and draws no edge on the graph; `direct_dependencies` stores only
dependencies another does not reach.

A same-repo `Needs:` starts the dependent on the parent's branch once the
parent's pull request is in review; it does not wait for a merge. A cross-repo
`Needs:` waits for the parent's merge. A never-started unit with two unrelated
same-repo parents builds on one and waits for the others to merge. The word
`merged` straight after the group number marks a line that waits for the parent's merge, and a
plain `Needs:` to a group of another repository is read the same way (`abk tags` and `abk check`
say so in an info note). A `Needs:` on
a group of the change's own is an error: groups within a change are already
ordered.

To make a change follow another's merge in the same repo, hold the change with a
planning note and start it after the merge. Write the note as a hold, not as
"wait for these to merge", which the pipeline does not read, and do not invent a
qualifier.

A `Needs:` that makes a cycle across changes (counting the order of each change's
consecutive groups) is an error: `abk tags` and `abk check` report it under each
change on the cycle, and the dependency is refused when linked.

## Do not write a task a builder cannot do

Do not write a task a builder cannot do: a record that needs live numbers, an
edit to the change's own files (`tasks.md`, its specs), or a tuning against a
first e2e-test run that has not happened yet. Where a gap shows only in the e2e-test
feedback, record it in the unit's fix round from that feedback instead of
specifying it up front. Confirm a measurement's premise before specifying it: a
task that measures a setting on a schema the setting does not affect cannot
pass.

## `Separate:` lines

The planner may join a small group onto an unstarted unit of a related change,
or join two such units, so one pull request carries both. A group that must be
reviewed and reverted on its own says so on a line inside the group:

```
Separate: <reason>
```

Such a group is never carried by another change's unit, and nothing is added to
its unit. The reason is required; `abk tags` rejects the line without one. Use
it sparingly: a small requirement that is related to another change does not
need it, and may simply be its own change, since it no longer costs its own
pull request when it is small and in line with unstarted work in the same repo
and kind. `[e2e-test]` groups (flagged or not), `[acceptance]`, `[contract]` and
`[narrow]` groups are never joined and need no `Separate:` line.

The planner joins related work first, groups that touch the same or closely related
files, and among equally good fits offers the more urgent work its partner first. It
never joins unrelated work for its priority, and a joined unit takes the most urgent
priority of its groups.

## What an `[e2e-test]` group holds

An `[e2e-test]` group is a stand-alone unit: it always has a unit of its own,
the planner never puts another group in it or joins it elsewhere, and it needs
no `Separate:` line. It holds only tests: test files and test support
(fixtures, helpers, test configuration), documentation and the changelog.
`abk tags` and `abk check` warn, without failing, when a task in an e2e group
names a backticked path that is none of these. The pipeline also stops the
unit at `checks` when its branch changes product code.

Do not put product fixes in an e2e group. When a live test finds a product
defect, the builder reports it and the pipeline files a `fix-product-defect`
change with one `[unit-test]` group (reproduce, then fix); the e2e unit waits
on it with a `Needs:` line and resumes once the fix is in review. An author who already
knows of the defect writes that `[unit-test]` group first, in its own change or
ahead of the e2e group, and the e2e group `Needs:` it.

A support file the e2e group must change, such as a fixture module outside the
test paths, is declared on a line inside the group:

```
Support: `scripts/seed.py`, `fixtures/` — <reason>
```

The reason is required, a trailing `/` covers a directory, a second `Support:`
line adds paths, and `abk tags` rejects the line in any other kind of group
or without a reason.

### Word the tasks of an `[e2e-test]` group

A task that asks for a fix is the usual cause of a failed e2e unit: the builder does as told,
changes product code, and the scope guard fails the unit after the build was spent. `abk tags`
and `abk check` warn of a task that begins with a changing verb (fix, change, add, implement,
update, refactor, remove, rename, make) even when it names no path.

- Bad: `Fix whatever the subprocess run shows that in-process calls could not (the entry point,
  the working directory, the default workspace path).`
- Good: `Test: run the entry point in a subprocess and make the test pass without changing
  product code; report a product fault as a product-defect.`

Checklist: for each task of an e2e group, ask whether it could change a product file; if so, it
belongs in another group. A known defect goes in a `[unit-test]` group written first, which the
e2e group `Needs:`; an unknown one is reported by the builder as a `product-defect` block.

## `Independent:` lines

Groups of a change are built in order: each unit depends on the one before. A
group that needs nothing the earlier ones build says so on a line inside it:

```
Independent: <reason>
```

Its unit is ready without its predecessor, and the chain closes around it: the
next group depends on the last unit before the independent one. It is never
joined into a neighbouring unit. The reason is required, the first group cannot
carry the line, and neither can an `[acceptance]`, `[contract]` or `[narrow]`
group (a flagged group keeps the ordering rules its flag gives it); `abk tags` rejects each.

`abk tags` and `abk check` warn when an `[acceptance]` or `[narrow]` group follows an
`Independent:` group, when a later group follows an `Independent:` group of its repo, or when a
`Needs:` to another change's same-repo group sits beside a same-repo predecessor: the unit can
have two parents neither of which builds on the other, and it then waits for all but one of them
to merge. Order the groups as a chain, or put the independent group in another change, to avoid it.

## `Split:` lines

A `[e2e-test]` group may carry `Split: <name>`, one of the e2e-test splits its repo declares, or
`rest`; no line means `rest`. A group is in one split: a test that must run in two splits is
written as two groups, and the planner never joins them. `rest` merges now while the group in a
held split waits until the split is released. A `Split:` line in a unit-test group, above the first
group, or naming an undeclared split is refused by `abk tags`. Editing the `Split:` of a started
unit's group takes effect for a unit parked on a split: it is reworked once with a note, and when
the new split is held the rework is deferred until it is released. For any other started unit the
stored split stays as it was.

## `Epic:` line

A change may name an existing board item, made by a person, that a board sync places the
change's top item under. One line above the first group, beside `Priority:`, gives the item's id or its exact title:

```
Epic: 42
Epic: Roadmap: Phase One
```

The kit only reads that item and never writes to it. A line with no value, a second line, or a line
inside a group is refused by `abk tags`. The line is left out of the plan hash, so adding or changing
it does not replan the change. A change without the line has no manual parent.

## `Priority:` lines

A group says how urgent it is on a line inside it, and a line above the first
group sets the default for the change's groups; a group's own line wins:

```
Priority: 2
```

The scale is 0 to 5, 0 the most urgent, and 3 for a group that says nothing:
0 the emergency lane, 1 a bug fix or a fix for a fault in the pipeline itself, 2
high priority (it unblocks other work), 3 normal, 4 can wait, 5 nice to have. 0 is
for work that must go before all urgent work, such as a fix that unblocks every
priority-1 change; it is rare, and it starts at the next tick in the emergency lane with no limit edit. The framework
reads only the number. A unit takes the most urgent priority of the groups it builds,
carried ones included, and keeps it once it has started. A value that is not an
integer from 0 to 5, a second line in one place, or a line in a group that could
not be read is an error; `abk tags` shows a priority that is not 3.

A group should be at least as urgent as every group that depends on it: the groups after
it in the chain, and any group with a `Needs:` line on it. `abk tags` and `abk check`
warn of a group that is less urgent than one that depends on it, and such a group is
promoted: the prerequisite is raised to its dependent's priority. Two groups that do not
share code belong in an `Independent:` group, so neither is a prerequisite of the other.

## E2e-test splits

A repo's e2e-test tests may be divided by `tests.e2e_splits` in `abk.yaml`; a test belongs
to at most one split and the rest are `rest`. Before writing an `[e2e-test]` group that adds
an e2e-test test, run `abk e2e-test check` to see that the test lands in one split only. A split held with `abk e2e-test hold` parks the
units that wait on it until `abk e2e-test release`; `abk e2e-test status` shows what is held.

A test that needs one of several runtimes or telemetry sinks carries the marker of that value
from `tests.e2e_dimensions`, at most one value per dimension. A machine lists the values it has
in `tests.e2e_available`; a run leaves out the others, and a split with nothing runnable there
is skipped, not failed. Write a test that works across values once, parametrized, with a name
that holds no value.

## Unit names

The program names units, not the planner: a unit is `<change>/<lowest group>`, the lowest
group of the change it carries, so a person can predict it from the headings. A replan over
the same groups keeps every id, and a taken id (retired, started or finished) is replaced by
the next free integer.

A group's owner is one unit while that unit has started and not finished. Renumbering or
narrowing a group a started unit carries gives it to a second unit, and the plan is refused,
naming both units and the group. To move the group, retire the owner with `abk retire UNIT
--reason TEXT` (its work stays on its branch unless `--delete-branch` is given), or edit
`tasks.md` to keep the group with the unit that has it.

## Describe behaviour, not names

A task describes behaviour. It names a new function, class or constant only when
the name is a contract: public API, a command, a wire shape, or a name another
change or repository depends on. Otherwise replace "add a helper that does X"
with what must be true, so the tests step is not handed a name to pin and can
search for existing code first.

- Good: "Two spellings that differ only in case or surrounding spaces select the
  same record."
- Bad: "Add `normalize_key()` and call it from the lookup and the import."

## Before committing a change

```
abk check          # openspec validate --all --strict
abk tags <change>  # the heading contract above
```

`abk tags` takes a change name, not a path.

Both run in CI on the planning repo's own PR, but running them first saves a
round trip. `abk check` covers the OpenSpec artifacts (proposal, design,
delta specs with GIVEN/WHEN/THEN scenarios); `abk tags` covers everything on
this page.

## Writing a change in a repo that is also the planning repo

Write and edit a change's artifacts in your working copy, under the specs
directory, and commit them as planning. The pipeline builds the code in its own
pipeline worktree, so run `abk tags` and `abk check` from the working copy as
usual, and run `abk tick` with `abk --config <worktree>/abk.yaml tick`, which
`abk status` prints. Do not tick boxes or edit the code to apply a change by hand.
