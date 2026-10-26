# Tasks

Acceptance: none — the pipeline's observable behaviour is unchanged, and the
existing argv-shape tests are what assert it; there is no new surface for a
consumer to drive.

## 1. [agent-build-kit] [tier1] The runtime protocol and its registry

Done when `runtimes.get(name)` returns an adapter or raises naming the known
ones, the Protocol's members and value objects are defined, and the type
checker rejects an adapter that does not satisfy it.

- [x] 1.1 Test: `runtimes.get` returns the registered adapter by name, an
      unknown name raises listing the known ones, and every registered entry
      has a `name` matching its registry key — mirroring
      `tests/forges/test_registry.py`.
- [x] 1.2 Test: the request, result and policy-report value objects reject an
      unknown field and refuse mutation (they are `model.Frozen`), and a
      cancelled turn and a spent usage window are distinct exception types.
- [x] 1.3 Add `runtimes/base.py`: the `AgentRuntime` `typing.Protocol`
      (`name`, `implemented`, `policy_coverage`, `supports_usage_tracking`,
      `supports_streaming`, `run`, `get_usage_status`, `check_policy`) and its
      value objects — `ToolPolicy`, `AgentRequest`, `AgentResult`,
      `PolicyReport`, `UsageStatus` — plus `AgentInterrupted` and
      `AgentRateLimited`, as `docs/agent-runtimes.md` specifies.
- [x] 1.4 Add `runtimes/__init__.py` with `register`, `get`, `names` and
      `_load_builtin`, copying `profiles/__init__.py`'s structure, with the
      registry typed `dict[str, AgentRuntime]`.

## 2. [agent-build-kit] [tier1] The Claude Code adapter, behaviour unchanged

Done when one adapter builds every `claude` invocation the pipeline makes today
and interprets its outcome, and the existing argv assertions still pass
unrewritten.

- [x] 2.1 Test: the adapter's build, review and track invocations produce the
      same argv the call sites build today — the readable specs directory, the
      hook registration naming the policy module, the allowed and denied tool
      lists, the edit permission mode, the model, and the streaming flags.
- [x] 2.2 Test: a streamed result event yields the final answer text; a
      non-zero exit with a rate-limit message raises the rate-limit error with
      its reset time; a signal death raises the interruption error; any other
      non-zero exit is a failed result rather than an exception.
- [x] 2.3 Test: `check_policy` reports every forbidden class enforced without
      running an agent, and `get_usage_status` returns the live reading, the
      cached one, or None, as the usage guard does today.
- [x] 2.4 Add `runtimes/claude_code.py` absorbing `init/claude_call`'s
      executor, `pipeline/claude_stream`'s streaming wired to the request's
      progress callback, the hook registration and tool-list composition from
      `hooks/policy` and `pipeline/wiring`, and the usage reading and refusal
      interpretation from `pipeline/usage_guard`. Declare `implemented`,
      coverage of every call, usage tracking and streaming; end the module with
      the Protocol assignment that type-checks it.
- [x] 2.5 Add an autouse test fixture that fails any test which would spawn a
      real agent process, beside the existing one that guards the login
      refresh.

## 3. [agent-build-kit] [tier1] Every call site through the runtime

Done when no module builds a `claude` argv of its own, the two call sites with
no injection point have one, and the two with no refusal handling have it.

- [x] 3.1 Test: the scheduled tracks run through an injected runtime, with no
      module attribute replaced, and the phase's model and tool lists still
      come from the tracks configuration.
- [x] 3.2 Test: conflict resolution runs through an injected runtime, and a
      run refused for a spent usage window surfaces as a rate limit rather
      than as a resolution that changed nothing.
- [x] 3.3 Test: the planner's graph call surfaces a refusal as a failed
      planning attempt, and research and propose still send the tool lists and
      settings they do today.
- [x] 3.4 Rewrite the seven call sites to build a request and call the active
      runtime: the build and review runners, the planner's graph call,
      conflict resolution, the track phases, research and propose. Keep each
      existing injectable parameter, defaulting it to the active runtime.
- [x] 3.5 Give the tracks runner an injectable executor and conflict
      resolution a default resolver that resolves the active runtime, so both
      are replaceable without monkeypatching.

## 4. [agent-build-kit] [tier1] Selection, models, and the setup checks

Done when a workspace can name a runtime and per-machine override it, a
selection that cannot work fails at load, and both `doctor` and `init` report
and offer to fix an unenforced command class.

- [x] 4.1 Test: an `abk.yaml` with neither key loads with the default runtime
      and its existing models block; a per-runtime models block overrides that
      block for the active runtime only; the per-machine model overrides still
      win; an unknown runtime and a selected runtime missing a required fact
      each fail at load with a message naming what is wrong.
- [x] 4.2 Test: the environment override selects a different runtime for one
      invocation without touching the file.
- [x] 4.3 Test: `doctor` reports the active runtime, fails when the runtime is
      not implemented or its agent command cannot be resolved, calls out
      coverage short of every call, and fails naming each unenforced class and
      printing the installation's fix command.
- [x] 4.4 Test: `init` asks before running the fix command, runs it only on
      confirmation, changes nothing when declined, and re-checks afterwards.
      The probe result is reused within a short window rather than re-run.
- [x] 4.5 Add `runtime`, the optional `runtimes` mapping (an agent command, a
      fix command, optional models) and the per-machine runtime override to the
      configuration and settings, and resolve models per active runtime.
- [x] 4.6 Add the runtime check to `doctor` and the ask-then-fix step to
      `init`.
- [x] 4.7 Update `docs/configuration.md`, `docs/cli.md` and the `abk-config`
      skill for the new keys and the override, and decide in the same change
      whether the tracks' own model and tool lists move under the runtime or
      stay where they are — documenting whichever it is.
