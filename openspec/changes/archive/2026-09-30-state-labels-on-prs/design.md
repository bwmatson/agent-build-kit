# Design

## Two families, named apart

Labels become two-directional here, and the two directions must not be confused —
the poller dispatches work when a label it recognises appears, so a label the
pipeline writes must never be a label the pipeline reads as an instruction.

So they are separated by name, not by bookkeeping: the instruction family a person
adds keeps the prefix it has (`agent:hold`, `agent:rework`), and the state family
the pipeline maintains takes its own. A reader can tell whose label is whose
without knowing the implementation, and the poller's rule becomes "only the
instruction prefix is a trigger" rather than a list of exceptions that grows.

## One state label at a time, in the graph's words

A unit is in exactly one state, so its pull request carries exactly one state
label: setting a new one removes the old. Anything else drifts into a pull request
labelled both `running` and `in_review`, which is worse than no label at all
because it looks authoritative.

The states and their colours are **not invented here**. `diagram.py` already has
both: a state vocabulary richer than the store's, derived from a unit's history —
`planned`, `blocked` (waiting on a dependency), `running`, `paused: rework`,
`paused: usage`, `held`, `in_review`, `failed` — and a `classDef` per state giving
a fill, a stroke and a text colour. That vocabulary is what a person already reads
on the graph page, so it is what the labels use.

The mapping to a host label is mechanical: the label's text is the state's name as
the graph writes it, and its colour is the state's **stroke** — the saturated one
that identifies the state, rather than the pale fill a node is painted with, which
would read as washed out where a host renders a label as a solid chip.

Three states the graph draws get no label, for the same reason the graph is not the
only thing showing them: `merged` and `closed` are what the host itself shows on a
pull request, and `unplanned` has no pull request to label.

The derived states are the valuable half. `blocked`, `paused: rework` and
`paused: usage` are all `planned` in the store, and they answer the question a
person actually asks of a queue — not "what state is this in" but "why is this not
moving". A label that says `paused: usage` says the pipeline is fine and the window
is spent; one that says `blocked` says something below it has to land first.

## One definition, or they drift

The colours and names live in the diagram module today, which is the wrong home
once two things render them. They move to one vocabulary both consume, and a test
asserts the obvious invariant: every state the graph can draw either has a label or
is on the documented list of states that deliberately have none.

Without that test this change decays the first time someone adds a state — the
graph gains a colour, the labels keep the old set, and the two surfaces disagree
about the same unit.

## Consuming an instruction

`agent:rework` means "send this back". Once that has happened the label is a lie,
and today it persists: a pull request being reworked, and one whose rework landed
hours ago, both still read as unhandled requests.

Worse, the trigger is the *addition* of the label, so a standing label cannot be
re-added — asking for a second rework means removing the first by hand. Removing it
at dispatch fixes both: the pull request tells the truth, and the instruction is
available again.

`agent:hold` is different and is kept. It does not request an action, it withdraws
the unit from the pipeline for as long as it is there; removing it is how a person
hands the unit back. That asymmetry is worth stating plainly in the docs, because
the two labels look like a pair and behave differently.

## Cosmetic means cosmetic

A label is not part of any guarantee. It is written after the work it describes,
its failure is logged once and never fails, holds or delays a unit, and no
decision anywhere reads a state label back — the unit store remains the only
source of truth about where a unit is.

That matters for a reason beyond tidiness: a label write is an extra call per
state change, on a host that rate-limits, and the pipeline must degrade to
today's behaviour rather than spending retries on decoration. It also keeps this
change from being able to break anything that matters.

## Why not put it in the body

The body already describes the unit, and it is written once when the pull request
is opened. Keeping a state sentence current there means editing the body on every
transition — a heavier write than a label, invisible in the list, and one more
thing to go stale. A label is the right size for a fact that changes.
