# Design

## A Protocol, because that is what this repo already does

`forges/base.py` and `profiles/base.py` are `typing.Protocol`s with a
module-level singleton per adapter and a four-function registry. `AgentRuntime`
copies that exactly: structural typing, so an adapter owns its own code and a
test double is a plain class, and no base class to inherit.

The Protocol is what keeps adapters consistent, so conformance is checked
rather than assumed: each adapter module ends with `_: AgentRuntime = RUNTIME`
and the registry is typed `dict[str, AgentRuntime]`, which makes the type
checker in `poe format` the thing that catches drift.

## Behaviour-preserving, provably

The risk in this change is not the new package, it is the seven rewritten call
sites. The guard is that `tests/pipeline/test_wiring.py` asserts on **argv
shape** — that `--settings` is present, that it names the policy hook module,
that `stream-json` is passed, that the denied commands appear. Those tests are
not to be rewritten: if the adapter builds a different argv, they should fail.

`init/research.py` and `init/propose.py` assert argv by index-of-flag in the
same way, and `tests/tracks/test_runner.py` asserts the tracks argv comes from
`TracksConfig`. Between them the current behaviour is pinned.

## The two sites that have no seam

`tracks/runner.run_phase_command` is replaced as a module attribute by its
tests, and `restack.claude_resolver` is hardcoded one level below the
`resolve=` seam its tests use. Both get a real injection point as part of this
change, because a call site that cannot be given a different executor cannot
be given a different runtime either.

## Config: additive, sparse, and per-machine overridable

`WorkspaceConfig` is `extra="forbid"`, so `runtime` and `runtimes` have to be
declared before an installation may name them. They are declared with defaults
that make every existing file keep loading: `runtime: claude_code`, and
`runtimes: {}`.

An entry under `runtimes` exists only for a runtime that needs a fact abk
cannot default — a command to spawn, a fix command to offer — so a workspace on
`claude_code` never grows the key. Model resolution stays where it is: the flat
`models:` block is the active runtime's, a `runtimes.<name>.models` block
overrides it when present, and `ABK_*_MODEL` overrides both. A second model set
is only needed while two runtimes' names have to coexist.

`runtime` is workspace-level, because a mixed-runtime workspace would mean two
policy models and two usage windows. That is also why `ABK_RUNTIME` exists:
flipping the committed setting moves every repo at once, which is no way to try
a runtime out.

## Proving the policy, not declaring it

A runtime whose agent executes its own tools is only as constrained as that
agent's configuration, so `policy_coverage` states a capability while
`check_policy` establishes a fact. Claude Code's adapter answers it locally and
for free — the hook is registered per run and the same commands are denied as
flags — which is enough for `doctor` and `init` to have a working check before
any second adapter exists.

`init` asks before it changes anything and then runs a command the installation
supplied, exactly as `doctor`'s existing forge-access check offers
`forge.access_fix`. The framework never edits another tool's configuration and
never inspects what the fix does.

## Why usage tracking has to be a capability, not a call

Today an unknown usage reading pauses the pipeline, which is right when the
account has a window shared with the operator's own sessions. A runtime billed
on demand has no window: it can never give a reading, and pausing on that would
stop the pipeline forever. So `supports_usage_tracking` gates the *step*, and
`AgentRateLimited` is reserved for runtimes that really do have a window.
