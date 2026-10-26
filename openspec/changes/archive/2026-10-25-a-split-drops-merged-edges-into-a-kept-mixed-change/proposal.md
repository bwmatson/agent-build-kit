# Proposal

## Why

The previous change (`a-split-moves-the-units-of-archived-changes`) made a moved unit's `depends_on`, `needs` and `merge_needs` edge on a merged unit of **another repo** that stays be dropped from the written record, with a printed note. A real dry run of a repo with a mixed change then still refuses.

The shape: change `m` has groups for repo a (the moving repo) and repo b, and the person keeps it with `--allow-mixed source`. A unit moves only when every change it builds moves, so all of `m`'s units stay in the source, those of repo a included. A unit `g/1` of a different change `g`, wholly repo a, moves, and has `depends_on` and `needs` on `m/4`, a merged repo-a unit of `m`. The dry run says `unit g/1 depends_on names m/4, which is neither moved nor in the destination`, because the drop rule reads "a unit of a repo other than the moving one" (`split/copy.py:118`, `parent.repo == plan.repo` skips). The group-level check (`copy.py:269-280`) refuses the same way for `g` group 1 `Needs: m group 4`.

Nothing is different about `m/4` as a parent from a merged unit of repo b: it is finished, nothing will build it again, and the scheduler reads a merged parent as not waiting whatever its repo. The refusal protects against a half-built parent, which a merged one is not.

## What Changes

- **The drop rule is about why the target stays, not only its repo.** A target that is `merged` with its merge loaded and that stays in the source because its repo is not the moving one, its project is not the moving one, or its change is a mixed one the person kept, is dropped from the record with a note naming the reason. A target that stays for any other reason (unreadable or unclassified change, a unit that blocks the run, one that is not merged, one whose merge is not loaded, `superseded_by`) still refuses.
- **The printed note says why**: `merged unit of another repo, stays in the source`, `merged unit of another project, stays in the source` or `merged unit of a change kept in the source`; the `dropped edges: N` line stays and shows the count by reason.
- **A moved `Needs: <change> group <n>` on a staying change is a note when every unit of that group is merged and loaded**, an error otherwise. The line is copied unchanged: the destination reads a `Needs:` on a change it does not have as nothing (`declared_needs` skips it, `awaiting_planning` ignores it, `abk tags` and `abk check` have no rule about its target), so it is satisfied history that is inert, not a dangling edge.
- `--remove` and the second-run check need no new code: both read the record `unit_records` returns.
- **Docs and changelog**: the `abk planning split` entry, the move runbook step 2 and the changelog.

## Impact

- Capability: `planning-split` (modified: the satisfied-history requirement and the dangling-edge requirement).
- agent-build-kit: `split/copy.py` (`_satisfied_history`, `DroppedEdge`, `preflight`'s `Needs:` loop), `cli/planning_cmd.py` (`_dropped`), `tests/split/`, `tests/cli/`, `tests/docs/`, `docs/cli.md`, `docs/runbooks/move-agent-build-kit-planning.md`, `CHANGELOG.md`.
- Not in this change: moving the kept mixed change's units, rewriting the copied `tasks.md`, removing the `not planned yet` log line a leftover `Needs:` causes.
