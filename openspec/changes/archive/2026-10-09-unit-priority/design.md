# Design

## The scale

An integer from 1 to 5, 1 the most urgent, 3 the default for everything that exists, so every current unit and change reads 3
without an edit. The numbers mean, by convention written into the authoring guidance: 1 a bug fix or a fix for a fault in the
pipeline itself, 2 high priority (it unblocks other work), 3 normal, 4 can wait, 5 nice to have. An integer rather than words
leaves room between the levels, and an in-between value sorts as its number. The framework does not read the meaning, only the
number.

In code the scale is an `IntEnum` with a member per conventional level (fix, high, normal, low, nice to have), so call sites say
what they mean; a value in range without a name is still valid and compares and sorts as its integer. It lives in
`pipeline/units.py` beside `UnitState`, not in `pipeline/vocabulary.py`: that module imports from `units.py`, and `Unit` needs the
type.

## The syntax

A `Priority: <1-5>` line, read in `pipeline/work_graph.py` beside `Needs:` (`NEEDS_LINE`, `SEPARATE_LINE`, `INDEPENDENT_LINE`
there are the models). Inside a group it sets that group's priority; above the first `##` group heading it sets the change's
default, which a group's own line overrides. Both `abk tags` and the planner read it through `validate_tasks`, which gains a
`priority` on `TaskGroup` (already resolved against the change default). A value that is not an integer from 1 to 5, a second
line in the same place, or a line the reader cannot attach to a group or to the head of the file is an error with its line
number, like the other lines; `abk tags` lists a group's priority when it is not 3. `abk check` is `openspec validate` and does
not read `tasks.md` groups, so it neither accepts nor rejects the line: only `abk tags` and the planner do.

## A unit's priority

A unit built from several groups takes the most urgent (smallest) of them, including groups carried from other changes: a join
must not hide an urgent group inside a normal unit. The plan is a model's JSON, which the planner parses into units, so the
priority is not asked of the model. The planner sets it in code from the groups of each member of the unit after the plan and
its joins are accepted, as the checks on independent and acceptance groups read groups in code. `priority` is a field on `Unit`
(`pipeline/units.py`), so `ready_units` can read it from a plain graph, and thereby on `StoredUnit`.

`UnitStore.upsert` takes the planned shape from the plan for every unit it is handed, so a re-plan would overwrite the priority
of a unit that has started. It keeps the stored priority for any unit that is not `unstarted` (planned with no branch, commit or
pull request), and takes the plan's for one that is. A started unit keeps what it started with; a line edited in the file
reaches only units that have not started, on the next plan of their change. Whether a change is re-planned when only a priority
line changed depends on the planner's trigger, which this design has not traced; a change that is not re-planned keeps its
units' priorities until it is, and the priority-only edit is then not seen. The tasks include the test that settles it.

## The unit store

`StoredUnit` is written whole by `model_dump`, and a record holding a key an older release does not know with a value is refused
by it (`_tolerate_other_releases`). Writing `priority: 3` on every unit would therefore make every store unreadable to an older
release for no reason. The field is left out of the record when it is the default, and an absent field reads 3, so a store with
no unit off the default is byte-identical to today's and an older release meets the unknown key only when somebody has written a
priority, then refuses it with the message it gives for any newer field. The changelog says so.

## Effective priority and the shared helper

The effective priority of a unit is the smallest priority among itself and every unit waiting on it. This change builds the
helper that finds the waiting set, because it is built first and the other rules need the same set: `waiting_on_me(unit, graph,
excluded)` in `pipeline/units.py`. It follows the reverse of `depends_on` (`merge_before` is a subset of it, so it adds no
edge), across repos, through chains, skips merged, closed and satisfied units and looks through satisfied ones, and keeps a
visited set so a cycle cannot loop. `excluded` is the explicit set of units the round leaves out (those named away by `--only`,
held by a lease, or in a backoff): the evaluation turns those into `held` units before ordering, so from the units alone they
cannot be told from a unit held for another reason that does wait. Excluded units are neither started nor counted as waiters.
There is no helper like it today: `waiting_on` answers a different question (what stops this unit starting), and the dependents
lookup in `pipeline/events.py` (`_dependents_of`) stops at the unit's own repository and serves restacking. The helper is one
function so `start-order-by-stack-age` takes its effective age from the same set and `blocked-units-free-their-slot` its handoff
order from the same pair, with one definition of who waits on a unit.

A waiting unit counts whether it is idle in a place or not yet started, as in the age rule. Lowering a waiter's urgency does not
make a prerequisite less urgent than it is on its own: the smallest is taken, and the unit's own priority is always among them.
A prerequisite of only nice-to-have units is therefore as urgent as its own priority says and no more.

## Ordering

The sort is one function with the age order, so it is written in `start-order-by-stack-age`, which reads the priority field and the
waiting-set helper this change adds in its first group. Written here as well it made the two changes wait on each other (this change's
second group on that one, that one on this change's second group) and nothing could start. The requirement below stays here as the
behaviour; the code for the sort lands with the age order, and this change's second group only shows it.

Priority decides only what goes next in the queue. `_start_rank` in `pipeline/units.py` keeps its three classes (an open pull
request, a resumed build, a unit that has never run), and `ready_units` sorts inside a class by effective priority, then by
whatever the other rules say, and ends with the planned position, so the order is total. Until another rule says otherwise a tie
falls to the planned position, as today. A resumed build still goes before a new priority-1 unit. It does not push out or pause an
active unit, and does not raise the limit on units in progress or the cap on units running at once: the choice of which ready unit
takes a free place is all it changes. For the same reason it does not make a unit ready that is not: a unit waiting on a
dependency, past the depth cap or outside `--only` is not started however urgent.

## Display

`abk status` marks the units whose priority is not 3, and gives the order of the ready queue with the reason each is where it
is (its priority and, if inherited, the unit it comes from). The unit graph shows a badge for a priority that is not 3. The log
of a start says when priority put a unit ahead of an older one.

## Not included

An override from the command line (a `priority` command) is left out: the line in `tasks.md` is the single source, so the order
can be read from what is committed. It is cheap to add if it is wanted.

## Related changes

`start-order-by-stack-age` and `blocked-units-free-their-slot` order by effective age and by the handoff; both wait for this change
(`Needs:`) and read the pair (effective priority, effective age) through the helper here.
