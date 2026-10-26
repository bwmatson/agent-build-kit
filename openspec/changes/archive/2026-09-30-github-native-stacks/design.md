# Design

## What the pipeline already produces

`base_of(unit, graph)` returns the branch of the unit's newest still-open
same-repo dependency, or the trunk when they have all merged, and the pull
request is opened against it. So a change whose units depend on each other
already lands as a chain: one pull request in this workspace targets
`spec/<change>/3` rather than the trunk.

That chain is precisely what the host's stacks API takes as input: an ordered
list of pull request numbers, bottom to top, where each pull request's base ref
matches the one below it. Nothing about how the pipeline builds needs to change
for the host to accept it.

## Registering, and when

The stack is created when the *second* pull request of a chain is opened — a
stack of one is not a stack — and extended as each later unit opens its own.
Both facts the call needs are already in the unit store: the unit's own pull
request number, and its base unit's.

Two failure modes have to be handled rather than assumed away:

- **Concurrency.** The append call can be refused while another request is
  mutating the same stack, which is ordinary here: ticks overlap deliberately,
  and two units of one change can finish close together. This is a retry, not a
  failure.
- **A stack that is finished.** Once every pull request in a stack has merged, it
  cannot be extended; a later unit of the same change starts a new one. The
  pipeline decides which case it is by asking the host what stack, if any, the
  base pull request is in, rather than remembering.

## Degrading rather than depending

The host's documentation does not say whether stacks work for a private
repository on a free plan, and it carries an error meaning "stacks are not
enabled for this repository" while also saying no enablement is required. That
contradiction is not worth resolving before building: what matters is that the
pipeline does not care.

So registration is advisory. It happens after the pull request exists, its
failure is logged once per unit and recorded on the unit, and nothing downstream
reads the stack back. A workspace where it never succeeds behaves exactly as it
does today, which is also the behaviour for any other code host.

## The rebase stays ours

There is no documented API to trigger the host's server-side cascading rebase —
it is a button in the interface and a command in an extension, neither of which a
tick can use. The pipeline therefore keeps `restack`: it already rebases a chain
when something merges, resolves conflicts with an agent, and carries an approval
over only when the rebase left the diff identical. Nothing here replaces that.

Two consequences of the host having its own opinion, though:

- **After a stack merge the host rebases and re-targets the pull requests above,
  force-pushing their branches.** The pipeline did not do it, so a branch's head
  can differ from the commit review approved without any run having touched it.
  The existing rule — push only the approved commit, and re-review anything else
  — is the right response, and must be reached by inspecting state rather than by
  assuming the pipeline is the only writer.
- **A non-linear chain cannot be merged** until something rebases it. The
  pipeline knows when it has left a chain non-linear; the reviewer should be told
  in the body rather than discovering it in a disabled merge button.

## What the body should say now

The body currently asserts the stack in prose: which unit this is, what is
beneath it, whether it is ready to merge. Where the host renders the series
itself, repeating it is two sources of one truth, and the pipeline's copy is the
one that goes stale.

So on a host with stacks, the body keeps only what the host does not show: that
the chain is linear or not, and what the pipeline is waiting for. On a host
without them, it keeps today's prose. The forge's capability flag decides which,
so neither is a special case buried in the body builder.

## Why not adopt the extension

The host's stack extension owns the local side — initialising, adding branches,
submitting, rebasing, restructuring — and the pipeline already does all of that
with plain git, in worktrees, under its own locks, with its own conflict
resolution. Adopting it would mean replacing working machinery with a dependency
that has an interactive-only path for restructuring and its own opinion about
branch layout.

The API is a different matter: one call, no local footprint, nothing taken over.
That is the part worth having.
