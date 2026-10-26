# Design

## What init does today, and the gap

Verified against agent-build-kit at the time of writing:

- `cmd_init` (`cli/init.py`) runs: detect repos, `draft_config`, an optional notification question (skipped under
  `--yes` and when `abk.yaml` is kept), write the planning repo, write code-repo conventions, research, propose,
  commit, then `_check_runtime_policy`, then the next-steps text. **Nothing in it asks about the runtime.**
- `draft_config` (`init/scaffold.py`) takes detections and consumes overrides only; the draft has no `runtime:`, so
  `runtimes.DEFAULT` (`claude_code`) applies. `config.runtime_name()` is `ABK_RUNTIME`, else the file's `runtime:`.
- `research()` and `propose()` take an optional `runtime`; `cmd_init` passes none, so `runtime_for` (`init/claude_call.py`)
  resolves `runtimes.active()` — the default on an unconfigured machine. A selection that cannot work fails at config
  load (`config._check_runtime`): unknown name, or a `requires` fact (`command`, for ACP) missing from the entry.
- `_check_runtime_policy` runs **after** the write, on the already selected runtime. For ACP, `check_policy` opens a
  session in a throwaway worktree and **sends a prompt** (`_probe_prompt`) asking the agent to attempt each forbidden
  class: it spends tokens. For Claude Code it is answered locally. `abk doctor`'s `_runtime` reports a missing agent
  command only for a runtime already named in the file, and calls the same policy check (cached 15 minutes).
- `RuntimeConfig` holds `command`, `policy_fix`, `models`, `context_windows`, `limits`. The ACP runtime
  `requires = ("command",)`, `agent_command = ()`, every role's default model empty (the agent's own).

The gap: the runtime is assumed, nothing checks what the machine can run, and the agent steps run before a choice.

## The probe: deterministic, bounded, no model call

`AgentRuntime` gains an optional hook (the Protocol stays satisfiable by existing runtimes; absence means "offers no
candidates"):

```
detect(which, run) -> list[Candidate]
Candidate(runtime, command, label, usable, reasons[], note, verified)
```

Checks, in order, stopping at the first that fails (the reason is the finding): the program is on the path
(`which`, injected as `abk doctor`'s `Which` is); the optional library imports (the `acp` extra); and, only for an
agent whose flag spelling varies, one `--help`/`--version` run through the injected `run` with a **5 second timeout
and no network**, whose output selects among the table's argv variants. A help run that times out makes the entry
unusable with that reason. The probe never starts a session and never prompts a model. A program on the path is
not proof the agent works (a bridge needs its backend; credentials may be missing), so an entry's `needs` is shown
as a note on a usable candidate, never silently dropped.

Claude Code's detection is its own runtime's: the executable on the path, nothing else.

## The known-agent table: data in the ACP runtime module

Everything outside `runtimes/` and `init/` stays product-neutral (the existing guard on product names in framework
text). The table is data in the ACP runtime's module: per entry `name`, `program`, `argv variants` in order of
preference each with the `--help` marker that selects it, `needs` (a running backend, an API key, an adapter),
`verified` (how it was checked, or "documented only"), `source`. Product names appear in this table and its tests
and nowhere else.

| Agent | Start as ACP server | Needs | Verified |
|---|---|---|---|
| <redacted> | `<redacted>` | its own config and credentials | run, on a machine where it was installed: `session/new` returned a session id and `modes` only (agent `<redacted>-agent` 0.21.6) |
| OpenClaw | `openclaw acp` | a running gateway, maybe a password | `--help` only ("an ACP bridge backed by the Gateway") |
| OpenCode | `opencode acp` | — | documented only (stdio JSON-RPC, exits when stdin closes) |
| Goose | `goose acp` | — | documented only |
| Qwen Code | `qwen --acp` | — | documented only |
| Gemini CLI | `gemini --acp`, older `gemini --experimental-acp` | — | documented only; flag varies by version, chosen from `--help` |
| Kimi CLI | `kimi acp`, older `kimi --experimental-acp` | — | documented only; sources disagree, chosen from `--help` |
| Codex | adapter `codex-acp` (npm `@zed-industries/codex-acp`, newer `@agentclientprotocol/codex-acp`) | an API key or login | documented only |
| Claude via an adapter | `claude-agent-acp` (npm `@zed-industries/claude-agent-acp`) | — | **UNVERIFIED**: the standalone run command is not confirmed. Claude Code itself is the `claude_code` runtime, not ACP |

Left out until someone verifies a command: the other adapters and agents the protocol's agent list names (Cursor's
adapter, `pi-acp`, `bub-acp-server`, Copilot, Augment, Cline, Junie, Kiro, ...). The table is meant to be extended;
`docs/agent-runtimes.md` gets an "adding an agent" section. **Every entry not run on the machine that wrote the
research is UNVERIFIED** until a person runs it; the `verified` note says so and doctor repeats it for a selected
entry. Sources are secondary (docs, registries) for every entry but the first. See
`docs/research/acp-agent-commands.md`.

## The flow in `cmd_init`

In order: detect repos → **probe** → show candidates → ask which → ask that runtime's setup questions → guided
policy step → show the fragment and confirm → write → **then** research and propose, passing the chosen runtime
explicitly so they never call the default. The notification question keeps its place. Two ordering consequences:

- The policy step runs *before* the write, so it works on a fragment held in memory. `check_policy` reads the command
  from the loaded configuration (`config.runtime_entry`), so the step needs the runtime to be checkable against the
  in-memory choice (builder detail: a loaded configuration built from the fragment, never a file). **UNVERIFIED**
  that the existing check can be pointed at an unwritten configuration without a change; if not, the policy step
  runs after the write, and a write that declined the check records `unchecked`, as below.
- `--dry-run` prints the same fragment and writes nothing, including nothing a question would otherwise have
  changed.
- `--policy-only` skips all of this flow except loading the existing file and the policy step (below).

**The list.** Every candidate the probe found, usable ones first (a number to pick, Enter for the default), each
unusable one with the reason it cannot be used yet, and always a last line "Other / my own configuration". A
candidate and "Other" lead to the same questions; "Other" starts with empty answers. The default is the only usable
candidate; with several there is no default and the person picks.

**`--yes`.** Exactly one usable: use it. Several: refuse, print the list, exit 2, unless `--runtime NAME` (and
`--agent-command ARGV` for ACP) names one. None: print what each candidate needs and exit 2 **without writing
anything**.

**A kept `abk.yaml`.** If `runtime:` is already set the question is skipped, as for notifications. `--runtime`
overrides only after confirmation, or with `--force`.

**Several runtimes in one file.** One `runtime:` is written; a second may be configured under `runtimes:` as a
fallback ("also configure another runtime as a fallback?", asked only when another usable candidate exists,
default no), so switching later is `ABK_RUNTIME=<name>`.

## Setup questions come from the runtime

An optional hook `setup_questions()` returns `Question(key, prompt, default, kind, validate, writes_to)`. Init asks
them in order, shows the default (Enter accepts), validates each answer on the spot (program on the path, library
importable, argv non-empty, name known) and re-asks on a bad one; the person may go back and pick another runtime.
A future runtime adds its own questions and needs no change to init.

- **Claude Code:** which `claude` executable (the one found, or a path/argv typed, e.g. a wrapper); models, as one
  question first: use the default models (recommended) / choose per role / type names. Defaults are the framework's
  current alias defaults, shown. "Choose" picks per role from the alias list; Claude Code has no command that lists
  models, so the list is the documented aliases carried in the runtime module, and said to be so. "Type" accepts
  anything. The scheduled tracks' model is asked the same way.
- **ACP agent:** the start command (the table's argv, with the variant chosen from `--help`, or the person's own
  argv); extra environment variable **names** the agent needs (values stay in the uncommitted `.env`, never in
  `abk.yaml`; no secret is asked for or written); the table's `needs` as a yes/no ("this bridge needs a running
  gateway: is it running? continue anyway?"); the guided policy step; and models, below.

## Models: only choices that need no model call

Choosing a model never makes an <redacted> call and spends no tokens, for any runtime. Where a list comes from, in order:

1. What the agent **advertises when a session opens** (`session/new`'s model config option; the protocol's `models`
   state is the other place a list may appear). `list_models()` starts the agent, opens a session in a temporary
   directory, sends **no prompt**, then closes. The existing adapter reads the config-option form
   (`_model_option`); **UNVERIFIED** that it, or any code in the repo, reads the `models` state form — the builder
   confirms and reads both, or documents that only the first is read.
2. A `models_command` in the table entry, if an agent has a command that prints its list. None is known yet.
3. The documented aliases, for Claude Code (static data).

If none gives a list, init offers **no choice list**: it says "this agent does not list its models; it will use its
own default", leaves the role models empty (an empty role is the agent's default, never tested by asking), and
accepts a typed name that is **not verified now** — a wrong name is reported by the run's existing "agent does not
offer model X; running on its default" notice. Init never "tries" a model by sending a message. When a list is
advertised it is shown per role with the agent's current model marked as default and "keep the agent's default for
all roles" first. The choice lands under `models:` (or the runtime's own `runtimes.<name>.models`, per the existing
resolution order).

Verified, on a machine where the agent was installed: the first table entry advertises neither a list nor a current
model in `session/new` (only `modes` and the session id), and its model command is an interactive picker, so it
falls into the "no list" case. Every other agent: UNVERIFIED. What an empty `tracks.model` means on ACP is also
**UNVERIFIED** (`TracksConfig.model` defaults to `sonnet`, a Claude Code alias, which the config comment says a
workspace on another runtime sets); the builder confirms and asks the question accordingly.

## The guided policy step

The build agent must never merge a pull request, push to the default branch, force-push or call the host's raw API;
the pipeline pushes and a person merges. The runtime's `policy_check` asks whether the agent refuses those command
classes; `runtimes.<name>.policy_fix` is the command that makes a given agent refuse them. A fix cannot be a fixed
script per agent, so the step works for any agent, known or not:

1. **Check.** Run the existing check against the chosen command. Passing: nothing more is asked. For ACP the check
   **spends model tokens** (it prompts the agent to attempt the classes — verified in `_probe`), so init says so and
   asks before running it, consistent with "choosing makes no model call". Declined: recorded as unchecked (below).
   Claude Code's check is local and runs without asking.
2. **A known agent with a fix:** the table's fix (a command, or a documentation pointer) is offered, "run it? [y/N]".
3. **An unknown agent, or no fix in the table:** init does not guess. Three choices: (a) rely on abk's own ACP layer,
   which already receives the agent's permission requests and applies the command rules to them — what it cannot see
   is what the agent never asks about, so the runtime's coverage stays `agent_flagged` and the check says how much
   abk sees; the builder verifies what the layer can intercept and writes the honest limit into the docs
   (**UNVERIFIED** here beyond what the adapter's design records); (b) supply a fix command (validated as an
   existing executable, recorded as `policy_fix`) that init runs and re-checks; (c) continue without, recorded as
   `policy: unchecked` on the runtime's entry (a new optional key), with a `abk doctor` warning on every run **and
   no probe** (so doctor never spends tokens for an entry the person declined to check).
4. After any fix, **re-run the check** and report what was observed. Init never claims a pass it did not observe.

`policy_fix` is offered only when the check finds an unrefused class and a fix is configured (today's behaviour,
moved earlier and extended).

**What the step prints.** Before a fix runs: the fix command and the unrefused classes with their spellings. The fix
runs with its output shown, never captured or silenced, because the person must see what it did to their agent's
configuration. After it, the check runs again and the step prints, per class and spelling (the report
`acp-policy-covers-global-option-spellings` produces), what is now refused and what still is not. Two outcomes get their
own wording: a fix that exits non-zero is reported with its exit status (the check still runs again, since a partial
patch may have landed); a fix that exits 0 with every unrefused spelling still unrefused says "the fix made no change;
still not refused: <spellings>", so the person learns that the policy content the fix applies, not the fix itself, is
what is missing. Init never claims a pass it did not observe.

Scenario: an agent that lets one spelling through is named by that spelling before init finishes (the check
`acp-policy-covers-global-option-spellings` reports per class and spelling, and this step prints it as `abk doctor`
does). A known-agent table row may say a spelling is covered only when a live check has shown it; otherwise its note
reads UNVERIFIED.

### Applying a fix to an existing installation: `--policy-only` and `--policy-fix`

Today `cmd_init` already ends with the policy check, also when `abk.yaml` is kept: a kept file is only filled, never
rewritten, and the runtime question is skipped, so a person who reruns init on an installation reaches the step and the
configured fix is offered (this is stated and tested here, not new). What is missing is a way to run **just** that step
without repo detection, research and propose, which are slow, spend tokens and are irrelevant to a policy patch.

- **`abk init --policy-only`** loads the existing `abk.yaml`, identifies the selected runtime (`--runtime` may name
  another entry already in the file), runs the guided policy step and stops. No detection, no research, no propose, no
  commit. Exit 0 when the check passes after the step, 1 when a class is still not refused, 2 on a usage problem (no
  `abk.yaml`, an unknown runtime, a flag that cannot combine with it).
- **What it may write.** Only `runtimes.<name>.policy_fix` or `policy: unchecked`, and only when the person chose to
  record them in this run: the change is shown and a confirmation precedes the write (under `--yes`, only a value given
  by flag is recorded). A configured fix is run from the file as it is; declining to record changes nothing in the file.
- **`--policy-fix ARGV`** supplies the fix command, validated as an existing executable by the same validator as the
  typed answer, recorded as `policy_fix` after the confirmation and used for this run. It works with or without
  `--yes` and with or without `--policy-only`.
- **`--yes` and a configured fix.** `--yes` keeps its meaning (accept defaults, ask nothing) but does not by itself run
  a fix: with a configured fix and an unrefused class, `--yes` runs it only when `--policy-fix` or `--run-policy-fix`
  is also given. Recommended and justified: a fix is an operator-supplied command that rewrites the agent's own
  configuration, and running it unattended because a general "assume yes" was typed is a surprise a script should not
  inherit; the explicit flag makes the intent readable in the command line and in the shell history. Without either,
  `--yes` prints the unrefused classes and spellings, runs no fix and exits 1.
- **The check spends tokens for a protocol agent**, so `--policy-only` asks before running it unless `--yes` is given
  (the existing token-spend rule, unchanged). A refusal exits 1, recording nothing.

The framework names no installation's fix script: the installation sets `runtimes.<name>.policy_fix` in its own
`abk.yaml`, and a fix only applies what its own policy file lists.

## Alternative routes, one fragment

Three ways produce the same `abk.yaml` fragment: typed answers; flags `--runtime NAME`, `--agent-command ARGV`,
repeatable `--set key=value` for any answer (`--set models.review=opus`, `--set runtimes.acp.command=...`), each
validated by the same validators; and `--runtime-config FILE`, a YAML fragment merged into the draft and validated
against the configuration schema. Unknown keys fail naming the key, as the strict schema does elsewhere. **Nothing is
written until confirmed:** init prints the fragment (the text `--dry-run` prints), asks to proceed, and writes only
then; `--yes` is the confirmation for a fully specified run.

## `abk doctor` shares the probe

`_runtime` gains an info line "other usable runtimes on this machine: ..." from the same probe, and a warning when
the selected entry's `verified` is "documented only". Doctor's existing behaviour for the selected runtime is
unchanged, apart from not probing an entry marked `policy: unchecked`.

## Testing

Unit-test uses fakes for `which`, `run` and the agent: a fake agent that records every request and **fails on any
prompt**, so "listing sends no prompt" is asserted rather than hoped. A fake future runtime with its own questions
proves init needs no change for it. The table gets a structural test (every entry names a program and an argv and
carries a `verified` note). E2e-test (the acceptance group) runs the real `abk init` as a subprocess against a stub
agent that is a real process speaking the protocol, on the path under a known-agent program name, and fails the run
if it ever receives a prompt. That run passes `--skip-research --skip-propose` because those steps are, by design,
model calls; a tier-1 test proves they receive the chosen runtime. It also declines the policy check, which is a
prompt for ACP. If an installed agent is present, a check that is skipped otherwise lists against the real one and
asserts no prompt is sent and no model list is reported. It needs the same tools as the existing end-to-end init test
(node for the OpenSpec CLI); the marker is the tier-2 one the repository already uses for runs against a real agent
on the host.

## What stays out

Installing an agent or the extra (init prints the exact command; how abk was installed decides it), and testing
whether an agent's credentials work (a model call; the policy check or the first unit finds it).
