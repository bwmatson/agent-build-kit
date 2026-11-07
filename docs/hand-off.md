# Handing work to someone outside the kit

A hold tells the kit that a change, or some of its groups, is being built by a person. The kit
never starts a held unit, units that `Needs:` it wait for its merge, and a recorded hand merge
lets the change archive. Holds are kept in `external.yaml` in the change's folder.

The hold is the path for work a person builds outside the kit. Where a repo names a tracker, the
kit also skips a unit whose board item a person has taken (see "Work tracker" in
`docs/architecture.md`). The hold is the permanent path for a repo with no tracker.

With a tracker configured, a person's claimed item and merged pull request replace the two
commands `abk external hand-off` and `abk external done`: when a pull request that carries the
`AB#` reference of a group item the person holds is merged (on a branch of any name), the next
tick records the hold for those groups (holder the person's display name, link the pull request)
if none exists, then the hand merge. A pull request closed without merging records nothing.

## The order

1. Record the hold first, before any spec is written, so the planner honours it from its first
   plan: `abk external hand-off <change> --all --holder "Sam Example" --link <board item URL>`.
   Use `--groups 2 3` to hold named groups, `--item group=88` to record board item ids and
   `--note` for why. The change folder must exist (`openspec new change` makes it); one with no
   `tasks.md` yet is accepted, and a name that matches no folder is refused.
2. Write the spec: `tasks.md`, the proposal and the design. A group added later is covered by an
   `--all` hold.
3. Create the board items by hand (below), and the person builds the work and gets it merged.
4. Once the work is done, record it:
   `abk external done <change> --groups 2 3 --pr 17` (or `--commit <sha>` for a commit on the
   default branch). The source is optional. Given a pull request, the forge must report it
   merged; given a commit, it must be reachable from the default branch; anything else is refused,
   and giving both is refused. Given neither, which is the usual case when the board item has no
   pull request linked, the board's word is the source: the hold is marked done with no merge
   source, the units whose groups are all done become merged with the history note "recorded by
   hand" and no merge record, and their dependents are released at the next tick. The command
   says that the work is taken as done on the operator's word. That costs a check: the kit cannot
   tell whether the work is on the default branch, so a dependent may start before it is. Give
   `--pr` or `--commit` when that matters. A hold done with no source shows as
   `done (no merge recorded)` in `abk external list`, and a pull request cannot be attached to it
   later.
5. To take the work back before it is done, run `abk external release <change> --groups 2 3`,
   or `--all` for every hold still held, which also works for a change with no groups yet.
   A done hold cannot be released.

`abk external list` shows every hold with its change, groups, holder, link, status, age and the
units waiting on it, and `abk status` has an external holds section. Every command takes `--json`
and is safe to repeat: handing off what the same holder already holds, in any order or in part,
changes nothing. A refusal under `--json` also prints `{"refused": "<reason>"}` on stdout. Work the
kit has already started is refused: let it finish, or `abk retire` it first, which returns its
groups to the plan.

## The file

```yaml
holds:
  - scope: [2, 3]
    holder: Sam Example
    link: https://boards.example/items/42
    since: "<ISO 8601 UTC timestamp>"
    items:
      epic: "39"
      change: "40"
      group: "41"
      tasks: ["42", "43"]
    note: Sam takes the API half
    status: held
```

A finished hold also has `merged_by` (empty when it was recorded with no pull request or commit) and `done_at`. The `status` is `held`, `done` or `released`.

## Board items made by hand

Create them so the tracker sync can adopt them later:

- An item for each level the tracker's `levels` setting names, whose types the provider block
  gives (`docs/configuration.md`): by default one per change, whose body starts with the marker
  line `<!-- abk:<prefix>:<change> -->`, and one per group of `tasks.md`; with `task` in `levels`, one
  per task. A top item a person made (`epic`) is named by the change's `Epic:` line and not made here.
- All unassigned, except the person who takes them.
- The tag `handoff` on each.
- Copy the text of the spec into the bodies.
- Record the ids in the hold with `--item`, the key the level: `change`, `group`, `tasks` (given
  once for each task item) and `epic`. `feature` and `story` are still accepted for `change` and
  `group`, and an unknown key is refused. The ids are what the sync adopts, and the markers are
  the fallback.
