# Design

## What was checked, and where

Read-only: `git fetch`, then `git show origin/main:<path>` in the build tool's checkout (origin/main at `6f487fd5`). Paths are under `src/agent_build_kit/`; the line numbers were read on that commit.

- **Where archived units are lost** (`split/select.py`). `_ARCHIVE_DATE` (line 32) is the date prefix of an archive entry's name. `plan_split` (232) classifies active changes and archive entries, builds `changes_moved` and `archive_moved`, uses both for `_classify_specs`, and then calls `_units(source, set(changes_moved))` (266). `_units` (308) compares each unit's `member.change` values with that set; an archived change's units have no member in it, so `moves` is empty and the unit is skipped: not moved, not blocking, not counted. `_mixed_decision` (193) already strips the date once, to avoid refusing an archive entry twice (line 206).
- **What then refuses** (`split/copy.py`). `preflight` (114) builds `here = held | moved_units` (140) and refuses every moved unit's `depends_on`, `needs` and `superseded_by` target not in `here` (147-152), and every `joined` member change not in `moved_changes | destination_changes` (154-157). Both `moved_changes` (`plan.changes_moved`) and `destination_changes` (active directories only) leave archive entries out, so the joined check also needs the fix once archived units move. The staying side (171-194) lists edges from a staying unit to a moved one: a warning, an error under `--remove`.
- **What a unit is** (`pipeline/units.py`). `Unit.members()` (180) is the unit's own change first, then `joined`; `Unit.repo`, `Unit.project` (default `.`), `depends_on`, `needs`, `merge_needs` (a subset of `needs`), `superseded_by` are plain fields. `UnitStore.all()` (`pipeline/unit_store.py:710`), `import_units` (922: equal skipped, differing is a conflict naming the id) and `remove_units` (949) are the only store calls the split uses.
- **`--remove`** (`split/remove.py`). `remove` (line ~72) calls `remove_units(plan.units_moved)`; `verify` and `outstanding` read `plan.units_moved` and `copy.unit_records`. All of them follow the plan, so archived units are removed and verified once the plan has them. `still_naming` (96) keeps the repo's entry while any remaining unit has `unit.repo == repo` and is not in `moving` (110). No change is needed in `remove.py`, except tests: that is the invariant of the spec, and the orphan rule below is what makes it hold for a unit whose change was deleted.

## Decisions

### A unit is matched to its change by name, over active directories and archive entries

The plan builds, from the directories it already classified, a map from change name to the sides of every directory with that name. An active directory is named by its change; an archive entry by `_ARCHIVE_DATE.sub("", name)`. A change name is **moving** when all its directories move, **staying** when it has directories and none moves (staying, unreadable, unclassified, or mixed and kept), **ambiguous** when some move and some do not (the same name archived twice with different tags, or re-opened after an archive), and **absent** when it has none. A unit moves when none of its members is staying or ambiguous and at least one is moving or the orphan rule (below) applies; a unit with a staying member and a moving one is the existing spanning refusal, unchanged. A unit with an ambiguous member is a new refusal kind, `ambiguous-change`, naming the unit and the change; a refusal rather than a guess, because the right side cannot be read from the files.

`--allow-mixed destination` puts a mixed change's active directory and archive entries in the moved sets (`_mixed_decision`, already so); `source` leaves them out. Units follow with no further rule, which is why the mixed scenarios are about units and not about new flags.

The unit settle check is unchanged: a moved unit in `running`, `in_review` or `held` blocks, whichever kind of change it belongs to. Archived units are almost always `merged`, `closed` or `satisfied`.

### A unit whose change has no directory moves by its repo, and the plan says so

One real installation holds a unit whose change was removed from both `changes/` and `changes/archive/`. Options:

- **Refuse naming it.** Safe in that nothing is guessed, but there is nothing for the person to do: the only ways out are to edit the unit store by hand, or to recreate a directory for a change they deleted on purpose. A refusal that cannot be resolved by the tool blocks the whole run and teaches people to bypass it.
- **Leave it.** This keeps the old defect in miniature: the source keeps a record with the moving repo's name, `still_naming` (`remove.py:110`) keeps the repo's entry for ever, the destination lacks a unit whose dependents moved (a dependency refusal, or a silently shorter history), and the cutover check ("the same units") fails.
- **Move it when its `repo` is the moving repo** (and, with `--project`, its `project`). A unit record is data keyed by unit id and `repo`; the repo is what `abk.yaml` and the destination agree on, and the record says which. No file is copied for it and no plan record exists. It is chosen. The plan prints it on its own line (`no change directory, moved by repo: <ids>`), so the person sees the one fact the tool inferred. A no-directory unit of another repo stays and is not counted (it is not this split's business). A unit with an orphan member and a moving member moves (the orphan member needs no side); with an orphan member and a staying member it is the spanning refusal; the in-flight check applies as everywhere.
- The joined-member check accepts a member change that is an orphan of a moving unit.

### A dependency on a merged unit of another repo is satisfied history; anything else still refuses

In a planning repo that manages several repos, a unit of repo b can be the parent of a unit of repo a (an edge across repos). When repo a moves and repo b's unit stays, today's check refuses (`neither moved nor in the destination`). What the destination can honor follows from how a dependency is read:

- `waiting_on` (`pipeline/units.py:964`) looks each followed dependency up in the graph; a parent that is **absent** is skipped (`parent is None`, line 1003: "A unit the plan dropped builds nothing, so nothing waits on it"). So an id naming no unit in the destination waits for nothing. For a **merged** parent the answer is the same: a cross-repo edge is a merge edge (`edge_kind`, 873-880) and `parent_landed` (892) is true for `MERGED`. Dropping the edge therefore changes nothing a scheduler reads for a merged parent, and the record no longer names an id that does not exist there.
- For a parent that has **not** merged, absence is not equal to waiting: a dangling id would be skipped and the moved unit would become ready early, against a parent still being built, in the other repo. This is exactly what the refusal protects, so it stays. The same holds for `closed` (a merge edge to a closed parent never clears, line 1011 excepted for failed units), `satisfied` (needs the graph to know whether its work landed), `failed`, `held` and the rest.
- A merge that is recorded but not yet loaded by the running tick also holds a dependent (`merge_loaded`, 929; used in `waiting_on` at 1013-1015). Dropping the edge would skip that wait. The rule therefore applies only to a parent whose merge is already loaded; a merged parent not yet loaded is refused like an unmerged one, with the message saying to run a tick and try again.
- `superseded_by` targets are the pieces carrying a split unit's work, always units of the same change and repo; a staying one is a real inconsistency and refuses. A `joined` member is a change, not a unit, and refuses as today.
- A same-repo staying unit (a dependency inside the moving repo that the selection leaves behind) also refuses: that is the person's selection splitting a repo's own chain, and it is not history.

The rule is applied where the record is written, not by editing the source: `copy.unit_records` returns the record with the satisfied foreign targets removed from `depends_on`, `needs` and `merge_needs` (kept in order, nothing else changed), `verify` and the idempotence check read the same function, and a second run computes the same record and finds it equal. A target already in the destination store is kept and needs no rule. Each dropped edge is one printed line (`unit X: dropped depends_on Y (merged unit of repo b, stays in the source)`) and a count, so the cutover check's comparison has an explanation for every unit whose dependency list is shorter in the destination. Under `--scrub` the ids are untouched.

### A staying edge into a moved merged unit is a warning even under `--remove`

The mirror case appears once archived units move: a staying unit of another repo that depends on a moved merged unit. `preflight` makes this an error under `--remove` (171-194). After the removal the id names no unit in the source, which `waiting_on` reads as "waits for nothing", the same answer as the merged unit gave. So the error stays only for moved targets that are not merged (the staying unit would have lost a parent still being built); for a merged target it is the same warning without `--remove`. The staying record is not rewritten: the split removes exactly the moved records. The builder checks the claim with a test over `waiting_on` / `ready_units` on a source after `remove`, and if a replan of the staying change raises on the stale id (`planner.py:825` is the check over plan units against the store's ids), the fix is to drop that id from the staying record through `UnitStore.set_dependencies`, as `_drop_stale_edges` in `cli/pipeline.py:4226` does for a unit that builds nothing; that would be recorded here as a decision, not done silently.

### The plan reports the split of units

`SplitPlan` gains `units_moved_active`, `units_moved_archived`, `units_moved_no_directory` (a partition of `units_moved`, by the unit's own change: a moved active change, a moved archive entry, no directory) and `units_staying` (ids of units not moved). `units_moved` stays the total, so a caller that reads it is unchanged. `_counts` prints `units: N` as before and indents the split under it, then the left-in-source count; the notes (no-directory ids, dropped edges) follow the counts as their own lines. The dropped edges come from `copy`, because only it sees the destination store; the CLI prints them from there, as it already prints `copy.preflight` results.

### Where the code goes

Selection stays in `select.py` (`_units` takes the resolution map and the moving repo and project), the edge rules in `copy.py` (`preflight`, `unit_records`, a `dropped_edges` helper returning frozen `DroppedEdge` models: unit, field, target), the output in `cli/planning_cmd.py`. No new module.

## Risks

- Matching by name merges an active change and an archive entry that share a name; the ambiguous refusal covers the case where they disagree, and when they agree they are the same change.
- Moving an orphan unit by repo is an inference. It is printed, it is limited to the moving repo, and the person can still decide differently by leaving the run at the dry run and fixing the record.
- Dropping an edge changes a record between source and destination; mitigated by one printed line per edge and by the drop applying only where the scheduler already reads the edge as satisfied.
