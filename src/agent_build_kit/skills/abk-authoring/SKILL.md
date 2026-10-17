---
name: abk-authoring
description: TRIGGER — read before writing or editing a change's tasks.md in a planning repo, before choosing a task group's [repo] [tier] tags or [contract]/[narrow]/[acceptance] flags, or when `abk tags` reports a problem. SKIP for questions about running the pipeline (abk-pipeline) or about abk.yaml (abk-config).
version: 1.1.0
generatedBy: agent-build-kit
---

# Writing a change the pipeline can build

The pipeline turns a change's `tasks.md` into units of work — branches and
PRs — without reading anything else about it. Two facts therefore have to be
on every task group heading: which repo its code lands in, and which test
tier it needs. They are written as tags, and `abk tags` checks them.

## The heading contract

```
## <n>. [<repo>] [<tier>] <title>
## <n>. [<repo>] [<tier>] [<flag>] <title>
```

- `<n>` numbers groups from 1, in the order they are built. Gaps and
  reordering are errors: the number is the build order.
- `<repo>` is one of the workspace's repo names exactly as `abk.yaml` spells
  them. A near miss (a capital, an underscore) is an error, not a guess.
- `<tier>` is `unit-test` (the ordinary suite, run in CI) or `e2e-test` (needs the
  real local stack, serialized on one host). The old `tier1` and `tier2` are still
  read as the same kinds, with a deprecation notice from `abk tags` and `abk check`.
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

## Flags

**`[contract]`** marks a group that widens a shape another repo consumes —
a field on a shared model, an event's payload, a tool's surface. The two
repos are never at the same commit, so callers of both shapes exist for a
window: the widening lands alone, and something removes the old half later.

**`[narrow]`** is that something. Required whenever a `[contract]` group
exists, and it must be the last group of the change: its unit depends on
every unit that migrates a consumer, and nothing depends on it.

This is only for contracts that cross a repo boundary. A shape and its
callers inside one repo land in the same commit; nothing needs flagging.

**`[acceptance]`** marks the group that drives what the change built the way
its consumer does — a scripted run of the tool as a real client, a request
through the public route. It is always `e2e-test`, comes after every group it
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

## `Needs:` lines

A group that cannot pass until a group of *another* change has landed says
so on a line inside the group:

```
Needs: <other-change> group <n> — why
```

The planner orders groups within a change on its own; across changes it only
sees what is already in flight, so a dependency that must hold is written
down and applied as code.

A same-repo `Needs:` starts the dependent on the parent's branch once the
parent's pull request is in review; it does not wait for a merge. A cross-repo
`Needs:` waits for the parent's merge. A never-started unit with two unrelated
same-repo parents builds on one and waits for the others to merge. The old
`merged` qualifier after the group number is deprecated: `abk tags` and
`abk check` warn about it and it changes nothing, so leave it out. A `Needs:` on
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
first tier 2 run that has not happened yet. Where a gap shows only in the tier 2
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
and tier. `[acceptance]`, `[contract]` and `[narrow]` groups are never joined
and need no `Separate:` line.

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

## `Priority:` lines

A group says how urgent it is on a line inside it, and a line above the first
group sets the default for the change's groups; a group's own line wins:

```
Priority: 2
```

The scale is 0 to 5, 0 the most urgent, and 3 for a group that says nothing:
0 (emergency) is the emergency lane. 0 is for work that must go before all urgent work, such as a fix that
unblocks every priority-1 change; it is rare, starts first, and bypasses no limit.
1 a bug fix or a fix for a fault in the pipeline itself, 2 high priority (it
unblocks other work), 3 normal, 4 can wait, 5 nice to have. The framework reads
only the number. A unit takes the most urgent priority of the groups it builds,
carried ones included, and keeps it once it has started. A value that is not an
integer from 0 to 5, a second line in one place, or a line in a group that could
not be read is an error; `abk tags` shows a priority that is not 3.

## Tier 2 splits

A repo's tier 2 tests may be divided by `tests.tier2_splits` in `abk.yaml`; a test belongs
to at most one split and the rest are `rest`. Before writing an `[e2e-test]` group that adds
a tier 2 test, run `abk tier2 check` to see that the test lands in one split only.

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
