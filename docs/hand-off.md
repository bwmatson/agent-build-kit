# Handing work to someone outside the kit

A hold tells the kit that a change, or some of its groups, is being built by a person. The kit
never starts a held unit, units that `Needs:` it wait for its merge, and a recorded hand merge
lets the change archive. Holds are kept in `external.yaml` in the change's folder.

The hold is the interim path to the tracker design's blocking, which blocks a unit whose board
item a person has taken. It is the permanent path for a repo with no tracker.

## The order

1. Record the hold first, before any spec is written, so the planner honours it from its first
   plan: `abk external hand-off <change> --all --holder "Sam Example" --link <board item URL>`.
   Use `--groups 2 3` to hold named groups, `--item story=88` to record board item ids and
   `--note` for why. The change folder must exist (`openspec new change` makes it); one with no
   `tasks.md` yet is accepted, and a name that matches no folder is refused.
2. Write the spec: `tasks.md`, the proposal and the design. A group added later is covered by an
   `--all` hold.
3. Create the board items by hand (below), and the person builds the work and gets it merged.
4. Once the work is merged, record it:
   `abk external done <change> --groups 2 3 --pr 17` (or `--commit <sha>` for a commit on the
   default branch). The pull request must be reported merged by the forge, or the commit must be
   reachable from the default branch; anything else is refused.
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
      feature: "40"
      story: "41"
      tasks: ["42", "43"]
    note: Sam takes the API half
    status: held
```

A finished hold also has `merged_by` and `done_at`. The `status` is `held`, `done` or `released`.

## Board items made by hand

Create them so the tracker sync can adopt them later:

- A Feature per change, whose body starts with the marker line `<!-- abk:<prefix>:<change> -->`.
- A Story per unit or group set, and a Task per task in `tasks.md`.
- All unassigned, except the person who takes them.
- The tag `handoff` on each.
- Copy the text of the spec into the bodies.
- Record the ids in the hold with `--item`; the ids are what the sync adopts, and the markers
  are the fallback.
