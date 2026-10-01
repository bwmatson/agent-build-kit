---
name: abk-authoring
description: TRIGGER — read before writing or editing a change's tasks.md in a planning repo, before choosing a task group's [repo] [tier] tags or [contract]/[narrow]/[acceptance] flags, or when `abk tags` reports a problem. SKIP for questions about running the pipeline (abk-pipeline) or about abk.yaml (abk-config).
version: 1.0.0
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
- `<tier>` is `tier1` (the ordinary suite, run in CI) or `tier2` (needs the
  real local stack, serialized on one host).
- `<flag>`, optional, is `contract`, `narrow` or `acceptance` — see below.

Under each heading, tasks are checkbox lines numbered within the group:

```
## 1. [app] [tier1] Add the marker

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
through the public route. It is always `tier2`, comes after every group it
exercises (only a `[narrow]` group may follow it), and gets a unit of its
own. Every change has one, or opts out with a line anywhere in `tasks.md`:

```
Acceptance: none — a refactor; nothing a consumer sees changes
```

The reason is what review agrees to; the line without one is an error.

```
## 1. [platform] [tier1] [contract] Accept the new field, keep the old one
## 2. [app] [tier1] Send the new field
## 3. [app] [tier2] [acceptance] Drive the route end to end as a client
## 4. [platform] [tier1] [narrow] Drop the old field
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

```
Needs: <other-change> group <n> merged — why
```

The `merged` qualifier makes the dependent wait for that group's pull request
to merge, or for a satisfied dependency's work to land, even when both are in
the same repo, and then start on the trunk instead of stacked on the
dependency's branch. Use it when the dependency is still reshaping what this
group builds on, so stacking would build against a moving target. It is
refused on a group of the change's own (`abk tags` rejects it): groups within
a change are already ordered.

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

## Before committing a change

```
abk check          # openspec validate --all --strict
abk tags <change>  # the heading contract above
```

Both run in CI on the planning repo's own PR, but running them first saves a
round trip. `abk check` covers the OpenSpec artifacts (proposal, design,
delta specs with GIVEN/WHEN/THEN scenarios); `abk tags` covers everything on
this page.
