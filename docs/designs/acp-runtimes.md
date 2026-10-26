# Driving coding agents through one runtime seam: ACP, the Claude Agent SDK and the sandbox

The kit runs coding agents behind one interface, [`AgentRuntime`](../agent-runtimes.md). Two runtimes ship: `claude_code`, which starts
`claude -p` as a subprocess, and `acp`, a client for any agent that speaks the Agent Client Protocol. This document says how to make the
two consistent: how to use the official Claude Agent SDK where it beats what the kit built, how to run Claude Code itself as an ACP agent
written in Python, how one capability policy can drive every runtime, and what the ACP client and the [sandbox](sandbox-design.md) can do
together that neither can do alone.

It started from an outside proposal for an `AgentGateway` with two backends. Most of that proposal already exists in the kit under other
names, so this document keeps what is new in it, replaces the rest with the kit's own pieces, and adds what a proof of concept, the reference
implementations and an inventory of the kit's tool and command policy showed. It is a design, not a specification. Paths and function names
are where the work happens today; names for new things are proposals. Each [recommended step](#recommended-steps) can become its own
OpenSpec change.

## Goals and non-goals

**Goals**

- One seam for every agent. A caller builds an `AgentRequest` and reads an `AgentResult` and `TranscriptEvent`s, whichever runtime serves it.
- One policy decision for which tools and commands an agent may use, made in the kit's own process for every runtime, rather than a string
  syntax only one runtime understands and agent-side config files for the rest.
- Use the Claude Agent SDK instead of the kit's own launch, stream-parsing and session code wherever it is better, and keep the kit's code
  where there is a reason (accounts, the usage guard, failure classification, the sandbox launcher).
- Claude Code reachable over ACP, in Python, with the strongest policy coverage ACP allows.
- Compatible with the sandbox, and better with it than without.
- The first release is about **agent nodes**: the steps where an agent edits, reviews or plans. ACP's usage features are described, not
  built on.

**Non-goals**

- **No Node.** Every dependency is a Python package. Node-based adapters are references to read, never dependencies.
- No editor plugin, and no serving of the kit's agents to editors over ACP.
- No remote ACP transports; stdio is the only stable one.
- Agent-to-agent messaging. That is a different protocol that shares the initials.
- Removing the `claude -p` runtime in the first release. It stays until the SDK path shows parity.

## Where the kit is today

| Piece | Where | What it does |
|---|---|---|
| The seam | `runtimes/base.py` (`AgentRuntime`, `AgentRequest`, `AgentResult`, `ToolPolicy`) | `run(request) -> result`, with callbacks (`on_record`, `on_session`, `on_result`, `on_permission`) and typed errors (`AgentRateLimited`, `NetworkUnavailable`, `ServiceUnavailable`, `SessionUnavailable`, `AgentInterrupted`) |
| Registry and selection | `runtimes/__init__.py`, `config.py` | `claude_code` always, `acp` when its extra is installed; chosen workspace-wide (`runtime:` or `ABK_RUNTIME`) |
| Claude Code runtime | `runtimes/claude_code.py`, `pipeline/claude_stream.py`, `runtimes/claude_output.py` | `claude -p`, prompt on stdin, `--output-format stream-json`, per-run `--settings` registering the `PreToolUse` policy hook, `--allowedTools`/`--disallowedTools`, resume and fork, accounts through `CLAUDE_CONFIG_DIR`, failure classification, usage from the result event |
| ACP client | `runtimes/acp.py` (`_Session`) | Advertises `fs` and `terminal` for a policed run and does that work itself under `command_policy`; `session/request_permission` verdicts; resume only when the agent advertises resume and list; usage from the raw prompt response and `usage_update` |
| Known ACP agents | `runtimes/known_agents.py` | Hermes (the one with an applied policy), OpenClaw, OpenCode, Goose, Qwen Code, Gemini CLI, Kimi CLI, Codex, and "Claude via an adapter" (unverified) |
| Events | `pipeline/transcript.py` (`TranscriptEvent`) | Nine runtime-neutral kinds: text, reasoning, tool_call, tool_result, plan, usage, permission, stop, user |
| Policy rules | `pipeline/command_policy.py`, `hooks/policy.py`, `tool_patterns.py` | One command policy shared by the hook and the ACP client; Claude-syntax tool strings (`BASE_TOOLS`, `REVIEW_TOOLS`, ...) |
| Usage | `pipeline/usage_ledger.py`, `pipeline/usage_guard.py`, `pipeline/gateway_usage.py` | Per-call ledger rows for every runtime; the session and weekly window guard for Claude; an optional spend gateway for per-token agents |
| Fakes | `tests/runtimes/acp_agent.py`, `policy_fake_agents.py`, `claude_cli.py` | Scripted ACP agents and a fake `claude` at the process boundary |

Coverage today: Claude Code declares `all_calls` (every tool call reaches the hook); the ACP client declares `agent_flagged`, because an
agent that runs its own tools tells the client only what it chooses to.

## What the outside proposal duplicates, and what it adds

| Proposed | The kit already has | Verdict |
|---|---|---|
| `AgentGateway`, `Backend`/`BackendSession` | `AgentRuntime.run(AgentRequest)` and the registry | Drop. "Gateway" also collides with the kit's spend gateway (`ABK_GATEWAY_*`). |
| `PermissionPolicy`, `FsPolicy`, `TerminalPolicy` | `_Session._verdict`, `_resolve_target`, `create_terminal`, over `command_policy` | Drop; harden what exists (below). |
| Typed event dataclasses, unknown updates dropped | `TranscriptEvent`; the ACP client already drops what it cannot map | Drop. |
| Agent registry by name | `known_agents.py`, `runtimes.candidates` | Drop. |
| In-process `claude-agent-sdk` backend | Nothing: the SDK is not used anywhere | **Keep, adapted** (next sections). |
| Claude over ACP | A row in `known_agents.py` marked unverified | **Keep, as a Python agent** (below). |
| Hermes through `hermes acp` | A verified `known_agents.py` entry and the resume handling in `agent-runtimes.md` | Keep; cite, do not restate. |
| Terminal env scrubbing, rooted file access | The ACP client confines writes but not reads, and passes the whole environment to terminals | **Keep as hardening.** |
| MCP passthrough, external cancel | `mcp_servers=[]`; cancel only on a refusal | **Keep as small, explicit features.** |
| Subscription authentication only, no direct API calls | True of `claude -p` already | Keep as a constraint. |
| Exposing the kit's agents to editors | | Non-goal. |

Dropped from the outside text for the same reason: an author and audience table, a package-health table that dates in a week (re-check
`agent-client-protocol` and `claude-agent-sdk` releases at each design review), and the long code samples for pieces that exist.

## What the reference implementations teach

Three implementations were read from source: the Python `claude-code-acp` (a Claude agent over the SDK), `hermes-acp-sdk` (a Python client for
Hermes), and the Node adapter in `agentclientprotocol/claude-agent-acp`, which is the one that matters most and changes a premise.

**The premise correction.** Since its 0.18.0 the Node adapter runs Claude through the SDK with Claude's **built-in** tools. It no longer routes
`Read`/`Write`/`Edit`/`Bash` through the client's `fs/*` and `terminal/*` methods; terminals are display-only. Up to 0.17.1 it did: when the
client advertised `fs` and `terminal`, the built-ins were disallowed and an in-process MCP server offered client-backed equivalents. It
stopped for fidelity with Claude Code's native tools. So "Claude over ACP gives every call to the client" is false for the current adapter:
coverage there is `agent_flagged`. What still works through it is `session/request_permission`, an options passthrough
(`_meta.claudeCode.options`: `disallowedTools`, `settings`, `env`, `mcpServers`, `model`), and `CLAUDE_CODE_EXECUTABLE`, which can point the SDK at a
wrapper script such as the sandbox launcher.

**Patterns worth taking**

- From the Node adapter: the capability set it advertises (`sessionCapabilities` for list, resume, close, fork; `promptCapabilities`;
  `mcpCapabilities`); `set_config_option` for model and mode; `usage_update` plus per-turn usage plus `_meta.quota`; `$/cancel_request` for pending
  permission requests; resume and list on top of the SDK's transcripts; stdout kept clean by rebinding console output to stderr; a test
  harness with a scripted fake SDK `query` and recorded golden ACP messages.
- From `hermes-acp-sdk`: deny-by-default policy objects; advertising only the client capabilities the policy allows; terminals with an
  allow-listed command set, `create_subprocess_exec`, no inherited environment and a byte-limited reader; a short drain after the prompt
  response so late `session/update` notifications are not lost; a fake agent over real pipes.
- From `claude-code-acp`: how little a Python agent over `ClaudeSDKClient` needs (`can_use_tool` mapped to `request_permission`, the client
  recreated on a model change).

**Pitfalls they document or contain**

- The Python `claude-code-acp` has no session persistence, ignores usage and cost, treats `allow_always` as allow-once, runs terminals through
  a shell on a joined string, and does not confine paths: a map of what to avoid.
- `hermes-acp-sdk`: read `line` and `limit` semantics are wrong, its allow-list matches only the command string, and its kill is not a process-group kill.
- The Node adapter's open issues: a client that stops reading stdout stalls the adapter's hooks (#1269); `session/list` compares the working
  directory case-sensitively, which breaks `/mnt/<drive>` paths on WSL (#1041); a `settings.model` in the user's settings overrides the requested model
  (#1056); the context `size` is wrong after a load until the result (#1181); a background subagent can hold a turn open (#1284).

### What the kit's ACP client should improve

| # | Change | Why |
|---|---|---|
| 1 | Do not assume client policing for an agent that runs its own tools; report `agent_flagged` and enforce through passthrough options, the sandbox and the existing post-run worktree comparison | The premise correction above |
| 2 | Scrub the environment of terminals the client starts (PATH plus an allow-list plus what the agent asks for) | `create_terminal` ignores its `env` and passes the whole kit environment today |
| 3 | Keep `session_update` non-suspending and pin it with a test; add a bounded drain after the prompt response | The library handles each notification in its own task; it works because the handler never awaits |
| 4 | Also read `_meta.quota`; tolerate a cumulative cost that goes down; trust a context `size` only from the last update | Per-call ledger accuracy |
| 5 | Retry `session/list` case-insensitively on WSL paths | #1041 |
| 6 | After selecting a model, re-read its `currentValue` and warn on a mismatch | #1056 |
| 7 | SIGTERM the process group, wait, then SIGKILL; add an external cancel (`conn.cancel`) | Transcript flush; the kit cannot cancel a run today except on a refusal |
| 8 | Confine `read_text_file` to the policy's read list (resolve, then check the root) | It is unconfined today |
| 9 | Keep `use_unstable_protocol=True` | The proof of concept needed it on both ends for `session/resume` in `agent-client-protocol` 0.12.1 |
| 10 | A scripted fake-agent layer that issues permission, `fs`, terminal and usage calls in varied orders | Pins 3 and 4 |
| 11 | A turn timeout | A background subagent can hold a turn open |

## The Claude Agent SDK against what the kit built

The SDK is a typed client over the **same `claude` subprocess**; it is not another engine. It replaces the plumbing the kit wrote and nothing
else. Adopt it where it is better; keep the kit's code where the SDK has nothing, or less.

| Kit piece | Verdict |
|---|---|
| Launch, stdin prompt, stream-json parsing, flag assembly | **Adopt.** The prompt travels as stream-json on stdin; the API is async only, so the kit's synchronous `run()` bridges to it with a dedicated event-loop thread (measured below). |
| Raw event parsing and failure classification | **Keep the kit's**, reached through a transport that tees the raw lines (below), so `claude_stream.records` and `claude_output.agent_failure` run unchanged. |
| The `PreToolUse` policy hook as a subprocess | **Adopt in stages.** First pass the existing shell hook through inline `settings`; then move the decision into SDK in-process `hooks`, which run in the kit's own process before every other permission step. `can_use_tool` is not the gate: it only fires when evaluation falls through to a prompt. |
| Cost, usage, session id, stop reason, `permission_denials` | **Adopt** (`ResultMessage`; read the last result, which is cumulative). |
| Session list and messages, `get_context_usage()`, `include_partial_messages`, `max_turns`, `max_budget_usd`, `set_model()` | **Adopt** where the kit re-derives them. |
| Account selection (`CLAUDE_CONFIG_DIR`) | Keep; pass through `env`. |
| The live usage endpoint and cache | **Keep**, and add the SDK's `RateLimitEvent` as a second signal (below). |
| Rate-limit, 5xx, network and session classification, retries, backoff | **Keep.** The SDK has no retry; read `ResultError` and `ProcessError` fields first. `ProcessError.stderr` is a placeholder, so capture stderr with the `stderr` callback. |
| The sandbox launcher | **Keep**; `cli_path` is the hook point. |
| Compaction tracking | Keep (it arrives as a generic `SystemMessage`); adopt `get_context_usage()` for fill. |
| In-process MCP servers, subagents, skills, structured output, file checkpointing, a pluggable `session_store`, OpenTelemetry propagation | New, not used in the first release; each is listed where a step could use it. |

**Costs.** The wheel bundles a pinned Claude Code binary (292 MB for version 2.1.308 at the time of the proof of concept), so the SDK belongs
in an optional extra, as `acp` is, and `cli_path` keeps the kit on the `claude` it already manages. Anthropic's terms on SDK-based products and
subscription login need a read for automated use (an [open question](#open-questions)).

## Proof of concept

Run on the development machine (WSL2, Python 3.14, `claude-agent-sdk` 0.2.172, `agent-client-protocol` 0.12.1), in a scratch
virtualenv with a short Haiku prompt per scenario on a second subscription account. Nothing in the kit changed. Several results are single runs.

| Question | Result |
|---|---|
| Does the SDK run with `cli_path` pointed at a wrapper that starts `claude` under the Landlock launcher? | **Yes.** An allowed write worked and a write to a protected file was refused. The account authenticated through `CLAUDE_CONFIG_DIR`. |
| Can the kit keep its own stream mapper? | **Yes.** A transport subclass that tees the raw stream-json lets `claude_stream.records` and the result classification run unchanged. Event and result shapes match `claude -p`; the SDK adds `control_response` and `session_state_changed` events. |
| Policy hooks | An in-process `PreToolUse` hook fires for every Bash call, denies, and the denial appears in `permission_denials`. A shell hook passed as inline `settings` works too, with the kit's attribution settings. `can_use_tool` was not called for tools already in `allowed_tools`; the SDK warns about it. |
| Sessions and control | Resume restores context and cost is cumulative; fork gives a new id; `interrupt()` and `get_context_usage()` work; `extra_args` builds `--worktree`. The list helpers return nothing unless `CLAUDE_CONFIG_DIR` is set in the process. |
| Defaults that differ from `claude -p` | The SDK sends a minimal system prompt: 142 tokens against 3,272 with the `claude_code` preset. Parity needs `system_prompt` set to the preset. |
| Rate-limit data | The `RateLimitEvent` raw payload carries the five-hour and seven-day windows with utilization and reset times: the numbers the kit's usage guard polls an endpoint for. Its `raw` shape is internal, so use it as a cross-check first. |
| Sync bridge | A dedicated loop thread works from synchronous code. A trivial prompt took 3.6 s through the SDK and 5.7 s through `claude -p` (medians of four). |
| A Python ACP agent over the SDK | **Works.** Initialize, streaming updates, tool-call updates, `usage_update` with cost, prompt-response usage, `session/cancel` (stop reason `cancelled`), `session/list` and `session/resume` in a new agent process. |
| Delegation routing | **Works.** With `fs` and `terminal` advertised, the built-ins are disallowed and in-process SDK tools call the client: a Bash call became a client terminal, and file writes were client writes. Delegated tools are deferred by Claude Code, so the model needs one extra turn to find them. |
| Delegation-minimal confinement | **Works.** With the agent process under the launcher and **no write access to the worktree**, a write-then-run task completed entirely through the client, and the file existed. |
| Per-command policy | **Works.** A terminal started with an empty worktree write list could not `touch` a file, a client file method in read-only mode refused a write, and a delegated command writing a protected path got `Permission denied` from the kernel. A command the client's rules refuse (`gh pr merge`) never started. |
| Mixed mode | **Works.** With only Bash delegated, the native `Write` still worked when the process wrap granted the worktree. |
| The kit's own ACP client | **Drives the agent unchanged.** `AcpRuntime.run` returned `ok`, text, token usage, cost, a session id, `usage_source=reported` and the expected transcript events. |
| The neutral policy | A frozen `CapabilityPolicy` rendered to the Claude flags reproduced today's `--allowedTools`, `--disallowedTools` and `--permission-mode` exactly. A first sketch split patterns such as `Bash(git *)` on spaces: the policy must hold parsed tuples, as `tool_patterns` tokenises them. |

Not proven: fidelity of delegated `Read` and `Edit` against the native tools (the native `Read` adds line numbers and handles images, the
delegated one returns raw text); long-running and background commands and terminal timeouts; the agent's own policy gate (the proof of concept
used a stub, and the command rules ran in the client); a no-network terminal in this run (the sandbox proof of concept covered the network
rule); a real third-party ACP agent.

## The path

The Node adapter is a reference, so Claude over ACP means **a Python ACP agent that the kit owns**, on `claude-agent-sdk` and the
`agent-client-protocol` package the kit already pins in its `acp` extra. Three stages, each reusing what exists.

1. **The SDK as the `claude_code` runtime's transport.** Same runtime, same seam, same accounts, usage guard and classification. It replaces
   argv assembly and stream parsing; `cli_path` points at the sandbox launcher; the shell hook is kept through inline `settings`, then moved
   in-process. The test is behaviour: the existing fake-`claude` transcripts and recorded result fixtures must produce identical
   `AgentResult`s and `TranscriptEvent`s.
2. **Claude Code as a kit-owned ACP agent** (`agent_build_kit.acp_agents.claude`), launched by the ACP runtime as a known agent in place of the
   unverified `claude-agent-acp` row. The proof of concept is a working sketch of it.
3. **Convergence.** Once stage 2 matches stage 1 on the usage guard, accounts, resume and classification, `claude_code` can become "the ACP
   runtime with the kit's Claude agent": one runtime and one policy path. Nothing is removed in the first release.

### The kit's Claude ACP agent: strategies from the Node adapter

1. **Skeleton.** One `ClaudeSDKClient` per session, options built per prompt, `session/cancel` mapped to `interrupt()` and to withdrawing
   pending permission requests, late output dropped after a cancel. The stop reason must be set to `cancelled` explicitly.
2. **Routing by what the client advertises.** The older adapter's design, kept: built-ins disallowed and in-process SDK tools exposed when the
   client advertises `fs` and `terminal`. The kit makes it a **delegation mode**: `none` (built-ins, the process sandbox only), `bash` (only
   Bash is delegated: that is where per-command policy, network control and the command rules matter) and `all` (`Read`, `Write`, `Edit`,
   `Bash`). Default for a policed run: `bash`.
3. **Why the Node adapter stopped: fidelity.** Replicated tools drift from Claude Code's native ones (edit matching, read formatting and
   limits, images, Bash timeouts and background behaviour). So `all` is allowed only where the kit needs it and a conformance test of each
   delegated tool against the native tool on the same inputs passes.
4. **The agent's own state.** The adapter lets the agent touch `CLAUDE_CONFIG_DIR` directly. The kit does the same, and the same folder is
   the sandbox's agent-state grant.
5. **Permissions.** Offer only `allow_once` and `reject_once`: an `allow_always` that writes durable rules would be policy written by the
   agent. The gate is the SDK in-process hook, not `can_use_tool`. Never `bypassPermissions`.
6. **Sessions.** Advertise only what is implemented: `list`, `resume`, `close`, `additionalDirectories`, `mcpCapabilities`. Use the SDK's `resume`
   and `list_sessions`; leave `session/load` (it replays history) and `session/fork` for later. The agent's process needs
   `use_unstable_protocol=True` for resume in the pinned library.
7. **Config options.** A `model` option (category `model`, which the kit's client already looks for) applied with `set_model()`, and a `mode`
   option limited to `default`, `acceptEdits` and `plan`.
8. **Usage.** Send `usage_update` with cumulative cost and the prompt-response usage, built from `ResultMessage`; add `_meta.quota` from
   `model_usage`.
9. **Stdout hygiene.** Send `print` and logging to stderr at start, nothing at import time, and test that stdout carries only frames.
10. **Errors and stop reasons.** Map `error_max_turns` and `error_max_budget_usd` to `max_turn_requests`, plus `refusal`, `max_tokens` and
    `cancelled`, with typed errors carrying a kind the kit client already maps to its own error types, so classification is reused.
11. **Tool-call rendering.** A small renderer from SDK tool use and results to ACP tool-call kinds and locations, and to `plan` updates from
    the todo tool, producing what the kit's `TranscriptEvent` mapping expects.
12. **Policy in, not options out.** The agent is the kit's own, so the policy arrives as a launch argument or environment (sandbox policy
    path, delegation mode, hook registration), not as client `_meta`.
13. **Context hygiene.** Account-level connectors and every deferred tool inflate a session's context: with tool search disabled one trivial
    prompt used about 340,000 tokens, and about 210,000 with claude.ai connectors turned off. The agent sets what it needs deliberately
    (`ENABLE_CLAUDEAI_MCP_SERVERS`, `strict_mcp_config`, `setting_sources`) and the step list includes measuring it cleanly.

## Sandbox compatibility

The ACP runtime and the SDK transport both start their agent process through `sandboxes.detect().command(policy, argv)`, so they inherit the
launcher with no change of design. The specifics:

- **Spawn points.** `claude_code` (SDK transport): the SDK's `cli_path` points at a wrapper that runs the launcher and then `claude`. The
  wrapper must pass arguments and stdio through untouched; the SDK's `env` is an overlay, so a clean environment needs the wrapper to
  start the child with exactly the variables the kit passes. ACP: the agent spawn and each terminal in `acp.py`, as `sandbox-acp` plans.
- **One enforcement point.** Claude Code's own Bash sandbox is switched off for kit builders (the SDK exposes it as a setting).
- **State folders.** The Claude agent needs its account folder and the temp folder writable; every ACP agent needs its own, listed per agent
  in `known_agents.py`.
- **Reads.** A process wrap with a read allowlist must leave the agent's own runtime and account folder readable.
- **Policy shape.** `ToolPolicy.sandbox` and `sandbox_coverage` from the sandbox design carry over; `sandbox_coverage` becomes a per-session
  result (next section).

## What ACP and the sandbox do together

Each item says why neither piece is enough alone.

1. **Delegation-minimal confinement.** For an agent that routes file and shell work through the client (the kit's Claude agent in `bash` or
   `all` mode, Hermes if configured so), the agent *process* needs no worktree write access at all. Its effects are client actions: checked
   by the kit and, for terminals, run under the sandbox. The process wrap shrinks to the agent's own state folder plus the model host, and the
   proof of concept confirmed the agent could not write the worktree yet finished a task. For an agent with its own tools (the Node adapter,
   Claude Code as a subprocess, Hermes' built-ins) it falls back to a worktree-writable wrap. `sandbox_coverage` is therefore **negotiated
   per session** from the agent's `initialize` response. ACP alone cannot bound an agent's own tools; the sandbox alone cannot narrow below
   what the agent legitimately needs.
2. **Per-command policies.** Because the client starts every terminal, each command can run under a policy chosen from what is known about
   that call: its tool kind, locations and the run's role. A reviewer's run and read-only commands get an **empty write list**: kernel-enforced
   read-only, which closes the reviewer-role follow-up left by `sandbox-retire-duplicate-guards`. Unit-test commands get **no network**;
   package commands get only their index hosts. A process wrap has one policy per step (and a per-command wrap broke Claude Code's shell
   state), and text rules alone cannot enforce any of it. This is only possible for delegating agents.
3. **Meaning and effect together.** The client's command rules see intent (`gh pr merge`, a push to a protected branch); the sandbox bounds
   effect (an interpreter one-liner the text rules cannot parse). Each covers the other's blind spot. It also answers the outside proposal's
   advice to run an agent with its own tools in a container: with the process wrap the kit is the boundary, no container needed.
4. **Refusals as structured feedback.** A sandbox refusal names the path or host. Reported as a failed tool call and a `permission` transcript
   event, it becomes feedback to the agent and the unit rather than a bare `Permission denied`, and a candidate for a person-approved list
   addition. Widening a list stays a person's decision.
5. **Credential isolation and metering through the proxy.** For key and gateway providers (not the Claude subscription, whose login cannot be
   injected), a loopback reverse proxy can add the credential, meter spend per unit and see rate-limit responses, so the agent never holds the
   key and the sandbox allows only that loopback port. It also fills the usage gap for ACP agents that report none.
6. **One audit trail with positive and negative events.** Client actions (exact commands and diffs) plus sandbox refusals give `abk explain`
   and transcript replay a complete answer to "what happened and what was blocked" on either runtime.
7. **Probe by pairing.** One probe measures both layers per agent (a text rule refuses, the sandbox refuses, or neither), so the
   "unverified against a real agent" label can be upgraded per agent when someone runs it.

## One capability policy

Today "which tools and commands may an agent use" is decided in several places that agree only by convention: Claude-syntax strings that are
**inert under ACP** except to infer a read-only run; a hook subprocess plus `--disallowedTools` flags for Claude (a second layer that exists
because a hook that crashes fails open); the ACP client's broker; and, for third-party ACP agents, edits to **the agent's own config file**
(`abk policy apply`, `policy_apply.py`, `recommended_policy.py`, `ApplyPolicy`, `policy_fix`, `policy_extra`, a policy step in `abk init`, and
about sixty tests). `abk policy check` is a static read of that file: it never runs an agent.

**Principle.** The decision is made once, in the kit's own process, for every runtime, by one function. The sandbox bounds effects. The
agent's own config stops being an enforcement point.

**`CapabilityPolicy`**, a frozen value built once per run from inputs that already exist (the role, the allowed-tools composition, the forge's
read and denied commands, the profile's `agent_commands`, `ToolPolicy`, `tracks.*`):

| Field | Meaning |
|---|---|
| `role` | implement, review, rework review, resolve, research, propose, plan, track, chat |
| `tools` | `read` (roots), `edit` (none, worktree, planning change), `exec` (none, commands), `network` (none, model only, hosts), `mcp` (none, allow-list) |
| `commands` | allow and deny as **parsed patterns** (one syntax, `tool_patterns`), plus the named meaning rules: no push, no commit, no `--no-verify`, protected branches, branch prefix, force-with-lease, planning repo, redirects into `$ABK_OUT` |
| `paths` | worktree, specs (read-only), fenced files, planning paths, the scratch folder |
| `mode` | `grants_nothing`, `read_only` or `edit`: replaces `permission_mode` and the planner's empty-list convention |

**Renderers**: the Claude flags (identical argv during migration), the SDK options plus an in-process hook that calls `evaluate(policy)`, the
ACP client's verdicts and the kit's Claude agent (the same `evaluate`, advertising `fs` and `terminal` for delegation), and the sandbox policy
(write, read and network lists).

**What stops being necessary**

| Machinery | Fate | Why |
|---|---|---|
| The hook subprocess registration (`hooks/policy.py` `hook_settings`, the hook script) | Goes with the SDK transport; `decide` stays as a pure function called in-process | No fail-open hook to defend against |
| `--disallowedTools` flags (`DISALLOWED`, `disallowed()`, `denied_prefixes`) | Goes with the same step | A second layer for the same reason; forge deny data stays |
| ACP's `_scope_warning`, `_cannot_honour`, and "`allowed_tools` is inert under acp" | Go | Symptoms of the string asymmetry |
| Read-only inferred from tool names (`EDIT_TOOLS`, `_is_read_only`) | Replaced by `edit: none` | An explicit field |
| `abk policy apply`, `policy_apply.py`, `recommended_policy.py`, `ApplyPolicy`, `policy_fix`, `policy_extra`, `policy: unchecked`, init's apply path | Optional, legacy | Only for an unmanaged third-party ACP agent; the kit can decide in-process for Hermes |
| Location rules (hook worktree check, fenced-config text rules, ACP's worktree snapshot) | Stand down when the step is confined | Already designed in `sandbox-retire-duplicate-guards` |
| The meaning rules, role tool lists (as role capabilities), forge deny and read data, `tool_patterns` (now the one matcher), `agent_commands`, `config_guard` (a warning when confined), `AgentPushed`, `abk install-config` | **Stay** | They say what, not where |

**`abk doctor`, `abk init`, `abk policy` after the change**

- *doctor.* One `capability policy` check per runtime and role that renders the policy and shows, per field, who enforces it (the kit
  in-process, the agent's own config, the sandbox), with `policy_coverage` and `sandbox_coverage`. It replaces `runtime coverage` and
  `runtime policy`, which carry about eighty lines of per-branch special cases. `merge guard` and `agent commands` stay.
- *init.* Choosing a runtime still probes candidates and models, but stops writing or offering per-agent policy files. For a third-party ACP
  agent it records that the kit decides in-process and shows the rendered policy; the apply path becomes an optional step for an agent the
  kit cannot confine.
- *policy.* `abk policy show --runtime X --role Y` renders the neutral policy; `patterns` and `apply` remain only for the legacy case.

**Migration order**, each step leaving argv and tests identical until the next: introduce `CapabilityPolicy` and the Claude flag renderer,
guarded by `test_claude_code_argv.py` and the tool-list tests; then the ACP client's verdicts from the policy; then the SDK renderer and the
in-process hook; then retire the string asymmetry and the legacy machinery. About sixty tests tied to the legacy paths become optional; the
command-policy, hook-as-function, ACP enforcement, `agent_commands` and tool-list tests stay and are retargeted.

**Ambiguities to settle.** Whether track runs on ACP enforce the planning-branch fence (`acp.py` never reads the planning-repo fields);
whether the kit's Claude agent can honour `read_only` and `grants_nothing`; that `policy_coverage` for ACP is hard-coded `agent_flagged`
even when the client executes, when it should depend on what the agent routes through the client; neutral classes for the agent, skill,
todo, web-search and web-fetch tools; and whether any installation sets `tracks.allowed_tools`, `tracks.disallowed_tools`, `policy_extra` or `policy_fix`.

## Usage and billing

ACP's usage features, in the pinned library: `usage_update` is stable (`used`, `size`, optional cumulative `cost` with an ISO currency); the
per-turn `usage` on the prompt response is still a draft (`totalTokens`, `inputTokens`, `outputTokens`, optional thought and cached counts);
the Node adapter also sends `_meta.quota` and a model id. The library salvages a malformed `usage` or `cost` to `None`, which is why the
kit reads the raw wire (`_wire_usage`), and that stays.

Rate-limit windows and account usage are outside ACP. The usage guard keeps polling its endpoint, and the SDK's `RateLimitEvent` becomes a
second signal into the same guard. ACP usage feeds the ledger rows the kit already writes (`usage_source=reported`). Billing: the kit builds
against Claude subscription authentication only and makes no direct API calls from its own code; per-token ACP agents are billed through
the spend gateway when it is configured.

## Testing

- **Unit.** The kit's scripted ACP agents and fake `claude` stay. Add a fake `ClaudeSDKClient` with golden ACP message logs for the kit's
  Claude agent (the Node adapter's scenario harness is the model), the scripted fake-agent layer from the client improvements, and a
  cross-runtime conformance test: a recorded Claude stream and a recorded ACP stream map to the same `TranscriptEvent` kinds and `AgentResult`
  fields.
- **Sandbox.** The same parametrised contract suite runs for every backend; the ACP paths add tests that a terminal's write outside its list
  fails, that a delegating agent's process cannot write the worktree, and that the environment of a terminal holds only what the kit passes.
- **No real ACP agent locally.** What is proven is the kit's side of the boundary; the probe the sandbox design ships is how a person with an
  agent upgrades the coverage label.

## Risks

| Risk | Mitigation |
|---|---|
| Delegated tools drift from Claude Code's native behaviour | `bash` as the default mode, a per-tool conformance test, `all` only where needed |
| The SDK or the ACP library changes under us | Optional extras, exact pins, the recorded-fixture tests, upgrade behind them |
| The SDK path loses what the kit built | Keep the kit's classification, accounts and usage guard; test parity on the existing fixtures before anything is removed |
| Claude Code's account connectors and deferred tools inflate every session | Set them deliberately; measure with a clean run |
| Terms of use for subscription login in SDK-based products | Read them for automated use before stage 2 (open question) |
| An agent that runs its own tools bypasses the client | Process wrap, the post-run worktree comparison and `agent_flagged` reporting; delegation where the agent supports it |
| Spec drift (the protocol has a v2 draft) | Pin, contract tests, follow release notes |
| A stage-2 agent we own is more to maintain | Keep it thin; it is a few hundred lines of glue over two libraries |

## Recommended steps

A recommendation, not a commitment, ordered after the sandbox chain.

1. **Conformance suite.** Recorded Claude and ACP streams map to the same transcript kinds and result fields.
2. **ACP client hardening.** Terminal environment scrubbing, a pinned notification order and drain, `_meta.quota`, cost tolerance, SIGTERM
   then SIGKILL, an external cancel, confined reads (some of this is already in `sandbox-acp`), and the scripted fake-agent layer.
3. **The SDK as the `claude_code` transport** (stage 1), behind an optional extra, with behaviour-identical tests and the teed transport; then
   the in-process hook.
4. **The Claude ACP agent** (stage 2): a spike for delegation routing and the launcher, then the build, in `bash` mode first.
5. **Capability negotiation.** Derive the process write list and `sandbox_coverage` from the agent's `initialize` response.
6. **Per-command sandbox policy** for delegating agents: read-only, no-network and package-host commands.
7. **`CapabilityPolicy`** and the Claude flag renderer (identical argv), then the ACP verdicts from it, then the SDK renderer; then retire the
   string asymmetry and the legacy agent-config machinery, with the rendered-policy `abk doctor` check and the simpler `abk init`.
8. **Refusals as events** through the protocol and into unit feedback.
9. **The loopback credential and metering proxy** for key and gateway providers.
10. **Convergence** (stage 3), decided from measured parity.

## Decisions made

- No new gateway: `AgentRuntime` is the seam.
- Python only. The Node adapter is a reference.
- Use the SDK where it is better, behind an optional extra; keep the kit's classification, accounts, usage guard and launcher.
- Claude over ACP is a kit-owned Python agent; the first release builds the SDK transport and the client hardening, and spikes the agent.
- Delegation modes `none`, `bash` and `all`; default `bash` for policed runs.
- One capability policy, decided in the kit's process; the agent's own config is not an enforcement point.
- ACP usage is described, not built on, in the first release.

## Open questions

- Do Anthropic's terms for SDK-based products and subscription login cover the kit's automated use? Who reads them?
- Does a delegated `Read` or `Edit` need to match Claude Code's native tools closely enough to make `all` the default, or does `bash` suffice?
- Should runtime selection stay workspace-wide, or become per role (the planner and the reviewer on different agents)? The sandbox policy and
  this one are built per role either way.
- Where do the kit's own agents live: in the kit, or in a separate package with its own release cycle?
- What is the cleanest way to keep account connectors out of builder sessions without losing the tools builders need?

## References

- Agent Client Protocol: https://agentclientprotocol.com/ and the Python SDK (PyPI `agent-client-protocol`)
- Claude Agent SDK for Python: https://code.claude.com/docs/en/agent-sdk/python (PyPI `claude-agent-sdk`)
- Reference implementations (not dependencies): `agentclientprotocol/claude-agent-acp` (Node, read for design only), `yazelin/claude-code-acp-py` (PyPI `claude-code-acp`), `VoixKz/hermes-acp-sdk` (PyPI `hermes-acp-sdk`)
- Hermes ACP: https://hermes-agent.nousresearch.com/docs/user-guide/features/acp
- In this repository: [agent-runtimes.md](../agent-runtimes.md), [sandbox-design.md](sandbox-design.md), [toolchain-profiles.md](../toolchain-profiles.md)
