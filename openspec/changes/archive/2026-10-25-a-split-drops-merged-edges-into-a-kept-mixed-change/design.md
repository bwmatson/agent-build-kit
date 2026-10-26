# Design

## What was checked, and where

Read-only: `git fetch`, then `git show origin/main:<path>` in the build tool's checkout (origin/main at `9af81ad4`, the merge of the predecessor). Paths are under `src/agent_build_kit/`; the line numbers were read on that commit.

- **The drop rule** (`split/copy.py`). `_satisfied_history` (100-125) takes, for each moved unit, the ids of its `depends_on`, `needs` and `merge_needs` outside `here` (moved units plus the destination's), and skips a target that is missing, **of the moving repo** (`parent.repo == plan.repo`, 118) or not `MERGED`. A loaded merge (`merge_loaded`, 120) drops the edge; an unloaded one is returned in `unloaded` and refused with "run a tick" (257-261). Everything else reaches `_dangling` (263, 312). `DroppedEdge` (48-53) has unit, field and target; `_edges_in` (128-137) reports `depends_on` and `needs` only.
- **Why a unit of the moving repo stays** (`split/select.py`). A change is moved, staying, mixed, unreadable or (archive) unclassified (`_classify`, 143-185). A mixed change moves only with `--allow-mixed destination`; `source` leaves it in `changes_mixed` / `archive_mixed` and out of `changes_moved` / `archive_moved` (`plan_split`, 267-273). `_units` (365-423) moves a unit only when no member change stays; a unit with a staying member and a moving one is the spanning refusal, an unsettled one the in-flight refusal, a changed-both-ways name the ambiguous refusal, and each of those is in `units_blocking`, not `units_staying`. A unit with no directory stays when it is not of the moving repo (and project). So a unit is in `units_staying` for these reasons only: its change belongs to another repo; its change belongs to another project of the moving repo (`--project`); its change is a kept mixed one; its change is unreadable or an unclassified archive entry (`_sides` gives such a directory a `False` side).
- **What the scheduler reads** (`pipeline/units.py`). `waiting_on` (964-1020) follows `followed_dependencies` and `merge_needs`; a parent missing from the graph is skipped (1002). For a parent that is present, `edge_kind` (873-889) is a merge edge when the repo differs, when the id is in `merge_needs`, or for a failed unit; otherwise a review edge. A merge edge waits unless `parent_landed` (892: `MERGED`) and `merge_loaded` (929); a review edge waits only when the parent's state is not in `REVIEWED` (93: in review, merged, satisfied, 1017). `second_open_parents` and `open_parents` (620-629) count in-review parents only; `depth_of` (750-757) says merged ancestors drop out; `base_of` (597-617) stacks on an open parent, otherwise on the trunk. So for a **merged** parent, whatever its repo or edge kind, the unit waits for nothing, has no base on it and no depth from it. An edge to an id that is not in the graph is the same answer (1002). Dropping the edge changes nothing the scheduler reads, same-repo included. This was checked for the same-repo case by reading the three consumers above; the builder pins it with a test over `waiting_on`, `base_of` and `ready_units`.
- **The `Needs:` loop** (`copy.py` 269-280). For a moved change it refuses each `Needs: <c> group <n>` where `c` has an active `tasks.md` in the source, is not moved and has none in the destination. The check is blind to what the line names: a group whose units are all merged is refused the same as one still being built.
- **What the destination does with a `Needs:` on a change it does not have** (`pipeline/work_graph.py`, `cli/pipeline.py`, `pipeline/cycles.py`):
  - `group_needs` (906) only parses the line; `validate_tasks` has no rule about the target change, so `abk tags` is clean.
  - `abk tags` / `abk check` notes and warnings that read the target (`_needed_repo` 1159, `inverted_groups` 1055, `unrelated_parent_warnings` 1133) return `""` or `continue` when the target's `tasks.md` is missing (1167, 1055).
  - `declared_needs` (4337) builds a link only for `(change, group)` pairs a live unit covers (4369) and reports the others to `missing`, which `link_needs` logs as `... not planned yet` (4164). Nothing is linked, nothing waits. The unit's stored `needs` is the dropped-edge record and `link_needs` leaves it equal (4199).
  - `awaiting_planning` (2529) counts a target only when its `tasks.md` is a file (2549); an absent one is "archived, which is merged".
  - `needs_cycle` (158) gives a node for the missing change no outgoing edges, and `find_cycle` (64) reads a missing key as empty, so there is no cycle.
  - So the copied line is inert: no error, no wait. Its cost is one `not planned yet` log line per tick while `g` is active, which a person removes by deleting the line.

## Decisions

### A target is dropped when it is merged, loaded and stays for a reason that is not a mistake

The rule changes from "its repo is not the moving one" to "it is in `units_staying` for one of three reasons", decided in this order, the first that applies:

| Reason the target stays | Test (on plan and the source's units) | Result | Note |
|---|---|---|---|
| Another repo | `target.repo != plan.repo` | drop | `merged unit of another repo, stays in the source` |
| Another project of the moving repo | `plan.project` set and `target.project != plan.project` | drop | `merged unit of another project, stays in the source` |
| A mixed change kept in the source | target in `plan.units_staying` and a member change of it is in `plan.changes_mixed` (or, with the date stripped, `plan.archive_mixed`) and not in `changes_moved` / `archive_moved` | drop | `merged unit of a change kept in the source` |
| Its change is unreadable, or an unclassified archive entry | target in `units_staying`, none of the above | refuse (dangling) | the existing message |
| It blocks the run (spanning, in flight, ambiguous) | target in `plan.units_blocking` | refuse (dangling); its own refusal is in the plan too | the existing message |
| Not `merged`: `in_review`, `failed`, `closed`, `satisfied`, any other | any reason above | refuse (dangling) | the existing message |
| `merged` but its merge is not loaded | any reason above | refuse, "run a tick and try again" | the existing message |
| In no store at all | | refuse (dangling) | the existing message |
| Already in the destination | | kept in the record, not reported | none |
| A `superseded_by` target | | refuse (dangling), as before | none |

Why the first three and not "any staying merged target": the others are cases where the plan is wrong or incomplete (a change the tool cannot read; a unit that already has its own refusal). Dropping an edge there would hide a mistake behind a note; for the three reasons the target's change is classified, the person chose its side or its tags say so, and the tool can print which. A same-repo merged unit that stays for no reason in the list cannot occur on a plan without a refusal, so nothing is lost by refusing it.

The note names the reason because the person reading the dry run is checking that "a unit depends on something that is not coming" is expected. "Another repo" is expected; "a change kept in the source" is the sign that the mixed change was kept on purpose, and the person can see which one.

`DroppedEdge` gains a `reason` field (a `StrEnum` of the three) so the printed line, the count by reason and the tests do not compare strings. `dropped edges: N` stays as the first words of the count line; when more than one reason is present, the count is followed by `(another repo: a, kept change: b)` for the reasons that occurred. `unit_records`, `preflight` and `dropped_edges` all derive from the same function, so the written record, `remove.verify` and the second-run check are unchanged in shape.

### A moved `Needs:` on a staying change is a note when the named group is merged history

The check at 269-280 keeps its trigger (the named change stays, has an active `tasks.md` in the source and none in the destination) and gains a second question: which units of the source cover `(change, group)` (a unit with a member of that change whose `groups` include it, as `declared_needs` finds them, 4347-4352)?

- Every covering unit is `merged` with its merge loaded: the line is a warning, `change g group 1 `Needs: m group 4` names m, which stays; its group is merged history and the line is kept, inert in the destination`. Both rules share one test, so a line is a note exactly when the unit edge it caused is a dropped edge (or was never recorded).
- A covering unit merged but not loaded: the "run a tick" error.
- No covering unit, or one not merged: the error as today, because the destination would then not wait for a group that is still to be built, and a person must settle it.
- This holds for any reason the change stays (another repo, another project, a kept mixed change), as the unit edge does; the other reasons in the table (unreadable, blocking) are refusals already.

**The copied `tasks.md` is not rewritten.** Rewriting would make the destination's file differ from the source's, which `file_contents` compares for the second-run check and `--scrub` handles as text only; it would hide the history from the person reading the change; and it is not needed because the line is inert there (above). A leftover line costs a log line per tick, never a block. The note tells the person it can be deleted, and a person who deletes it does so in the destination as an ordinary edit (which `abk replan` keys on without the `Needs:` lines, `cli/pipeline.py:5048`, so it does not even replan).

### `--remove` and the second run need nothing new

`remove` removes `plan.units_moved` and compares through `unit_records` (`remove.py` 64-93; the predecessor's decision), which already returns the record without the dropped edges; `still_naming` (96-122) keeps the repo's entry while a unit of the repo stays, and the kept mixed change's units are exactly that case, so the entry stays with `kept repo app: still named by unit <id>` (as the predecessor's scenario says). The `Needs:` note changes no record. The builder pins both with tests; no change in `remove.py` unless they fail.

### Where the code goes

`_satisfied_history` takes the reason decision (a small function over the plan and the source's units); `_edges_in` carries it; `preflight`'s `Needs:` loop adds the covering-units question; `_dropped` in `planning_cmd.py` prints it. No new module.

## Risks

- Dropping an edge into a kept mixed change drops a link between two repo-a units that the destination's planner will never see again. Mitigated as in the predecessor: the scheduler already read the edge as satisfied, and each drop is printed with its reason.
- The kept mixed change's units stay in the source with the repo's name, so `--remove` keeps the entry; that is the point of keeping the change, and it is reported.
- The leftover `Needs:` log line per tick is noise; accepted, as the alternative is a rewritten file.
