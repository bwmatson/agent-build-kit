# Proposal

## Why

The pipeline knows exactly where every unit is — `abk status` prints it from the
unit store — but a person looking at the pull request list cannot see any of it.
Each pull request looks like every other: the state lives in a store on one
machine, and in prose inside the body that goes stale as the unit moves on.

Labels are already half-wired. The poller acts on two a person can add,
`agent:hold` and `agent:rework`, and the forge reads labels on every poll. What it
has never had is a way to write one, so the traffic is entirely one-directional.

Two consequences, both met in practice today:

- **A queue you cannot read.** Six open pull requests, one building, one awaiting
  review, one being reworked, one held — indistinguishable in the list. The state
  is a command away, on a machine, rather than beside the thing it describes.
- **An instruction that never clears.** A pull request labelled `agent:rework` is
  still labelled `agent:rework` while the rework runs and after it lands, because
  nothing removes it. It reads as a standing request that has not been picked up,
  which is the opposite of the truth. And since only an *added* label triggers, a
  second rework cannot be asked for until someone removes the first label by hand.

## What Changes

- **The pipeline keeps one state label on each pull request**, updated as the unit
  moves and replacing the previous one, **named and coloured as the unit graph
  already names and colours that state** — so the list and the graph read as one
  system rather than two vocabularies for the same thing.
- **One definition serves both.** The graph's state names and its palette move into
  a shared vocabulary that the diagram and the labels both consume, so a state
  cannot be renamed or recoloured in one place and drift in the other.
- **An instruction label is consumed when it is acted on.** The pipeline removes
  it once the dispatch it asked for has happened, so the pull request shows its
  state rather than a request already granted, and the same instruction can be
  given again later.
- **What a person writes and what the pipeline writes are told apart**, by name,
  so the pipeline never reads its own label as an instruction and a person can see
  at a glance which labels are theirs to set.
- **A label the repository does not have yet is created**, once, with a
  description saying what it means — rather than the write failing on a fresh
  repository.
- **Labelling never costs a unit.** It happens around work already done, and a
  host that refuses or cannot label is logged once and ignored, exactly as with
  anything else cosmetic.
- **The change a pull request belongs to is a label too** — stable for the life of
  the pull request, so a queue can be read by change as well as by state.

## Impact

- **agent-build-kit**: the forge gains label writes, the places a unit's state
  changes gain a call, and the poller learns which labels are its own.
- Nothing about building, reviewing, rebasing or merging changes.
- The two labels a person already uses keep their names and meanings.
