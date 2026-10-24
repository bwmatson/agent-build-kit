# Sandboxing agent steps: design, proof of concept and recommended steps

The [command policy](agent-runtimes.md#policy-enforcement-without-a-hook-contract) decides what a builder may run by reading the
command. A command can be written a thousand ways (an interpreter one-liner, a copy tool, a redirect), so that list cannot be
finished, and `pipeline/config_guard.py` exists as the backstop that notices after the fact when a configuration file changed. This
document moves the line to what an agent step's processes can write and reach, enforced by the kernel and shared by every runtime. The
command policy stays for the rules that are about meaning (no merge, no force-push, no push to a protected branch).

It is a design with a proof of concept behind it, not a specification. Paths and function names are where the work happens today;
setting and type names are proposals. The [recommended implementation steps](#recommended-implementation-steps) are drawn from the
proof of concept, and each can become its own OpenSpec change.

## Goals and non-goals

**Goals**

- An agent step's processes can write only the unit's worktree, the parts of the repository's `.git` a commit needs, the temp
  folder, the agent's own state folder and a short list of tool caches, and can reach only a list of hosts, whatever the command is.
- The planning repo's configuration (`abk.yaml`, `abk.local.yaml`) cannot be written by any agent route, so a person may edit it while
  a run is in progress and a unit no longer fails with `ConfigChanged` for it.
- One policy, written once, applied by every runtime the kit can launch, on Linux, WSL2 and macOS.
- A sandbox that cannot start does not quietly run unsandboxed: the kit says so, and a repo can require it.
- Few installs: nothing that needs `sudo apt`, and no Node dependency, where the kernel or Python can do the job.

**Non-goals**

- Replacing the command policy. Rules about meaning stay in the hook and in ACP's broker.
- Restricting the kit's own code (the tick, the planner, the host and git calls the pipeline makes). Only **agent steps** are
  restricted: they are what the kit cannot control well.
- Containerising builders, or sandboxing a person's own sessions (`refusals_only` runs and the chat keep their current policy).

## Where the line is today

| Route | Enforced by | Gap |
|---|---|---|
| Claude Code Bash | `PreToolUse` hook reads the command text (`hooks/policy.py`) | any route the text rules do not name |
| Claude Code Edit/Write | the same hook (`Bash\|Edit\|Write\|MultiEdit\|NotebookEdit`) | none known |
| ACP file writes | the client does the write, inside the worktree, outside `specs_dir`, not a fenced file (`runtimes/acp.py` `_resolve_target`) | none known |
| ACP terminal | the client reads the command text, then spawns a plain process (`acp.py` `create_terminal`, `asyncio.create_subprocess_exec`) | the same gap as Bash, no network control, and the child inherits abk's whole environment |
| ACP file reads | `read_text_file` is unconfined | any readable file |
| Config files | `config_guard.config_unchanged` compares both files after each agent step (`pipeline/wiring.py`, `tracks/runner.py`) | detects, does not prevent, and cannot tell an agent from a person |
| Planning repo view | `add_dirs=(specs_dir,)`, read-only (`wiring.py`) | already narrow, but the live folder rather than a snapshot |

## The mechanism

The kit builds its own sandbox layer. It takes **Claude Code's pattern** (writable paths, denied paths, a network allowlist by
domain, a protected-path rule, a switch for what happens when the sandbox cannot start) and not its mechanism, which is `bubblewrap`
and `socat` (operating-system packages that need `sudo apt`, and an AppArmor setting on newer Ubuntu).

- **Files: Landlock, called from Python.** Landlock is a Linux kernel feature that lets a process restrict itself, and everything it
  later spawns, to a list of paths with read, write and execute rights, and to a list of TCP ports. It is three system calls through
  `ctypes` (`landlock_create_ruleset`, `landlock_add_rule`, `landlock_restrict_self`) after `prctl(PR_SET_NO_NEW_PRIVS)`. No helper
  binary, no root, no install.
- **Network: an allowlisting proxy inside the kit.** Landlock filters TCP by port, not by domain. The wrapper starts a small
  HTTP and `CONNECT` proxy (standard library `asyncio`), sets `HTTPS_PROXY` and `HTTP_PROXY` for the agent step, and the Landlock rule
  permits connections to the proxy's port only. A process that ignores the proxy settings cannot connect at all.
- **A launcher** (`python -S -m agent_build_kit.sandbox_exec <policy> -- <command>`) applies the restrictions to itself and `exec`s
  the command, so every child inherits them and nothing can lift them (`no_new_privs` also stops `sudo` working inside).

- **macOS: Seatbelt, through `sandbox-exec`.** No package is needed: `sandbox-exec` ships with macOS, and the kit generates a Seatbelt
  profile (SBPL) from the same policy. See [macOS](#macos).

The launcher has one interface and a backend per platform (Landlock on Linux and WSL2, Seatbelt on macOS), laid out in [the next section](#structure-a-base-layer-and-a-backend-per-platform). `@anthropic-ai/sandbox-runtime`
and Claude Code's sandbox are sources of ideas, not dependencies.

## Structure: a base layer and a backend per platform

The shape is the one the kit already uses for code hosts ([code-forges.md](code-forges.md)) and runtimes ([agent-runtimes.md](agent-runtimes.md)):
a base layer that holds the protocol and everything shared, a registry, and one implementation per platform. A new `sandboxes/` package:

```
sandboxes/
  base.py        SandboxBackend (a Protocol, not a base class), SandboxPolicy, Availability, SandboxUnavailable, Coverage
  __init__.py    register(), get(name), names(), detect(): the registry, and the choice of backend for this machine
  policy.py      assembling the lists (built-ins, runtime, profile, abk.yaml, abk.local.yaml) and resolving every path
  proxy.py       the allowlisting proxy, shared by every backend
  launcher.py    the minimal-import entry point the backends' commands start through
  landlock.py    the Linux and WSL2 backend: Landlock through ctypes
  seatbelt.py    the macOS backend: a generated SBPL profile run through sandbox-exec
  unavailable.py the backend for a platform with none (native Windows): reports why, confines nothing
```

**The base layer** (`base.py`) is a `Protocol`, for the reason `forges.Forge` is: a stand-in in a test is a plain class, and the shared parts are
free functions that need no inheritance (`tests/sandboxes/stand_in.py`). It declares:

| Member | What it answers |
|---|---|
| `name`, `platforms` | the key (`landlock`, `seatbelt`, `unavailable`) and the platforms it applies to (`linux`, `darwin`) |
| `availability()` | an `Availability`: whether this machine can apply the sandbox, the coverage it reaches (`process`, `files`, `none`) and, if not, the cause and the fix (kernel too old, `sandbox-exec` missing). It **probes**, by applying a trivial restriction in a subprocess and checking it held, not by looking for a file |
| `command(policy, argv)` | the argv that starts `argv` confined: for Landlock the launcher with the policy file, for Seatbelt `sandbox-exec -f <profile> -- argv`. A runtime calls only this, at the one place it spawns the agent |
| `environment(policy, env)` | the environment the confined process gets (the proxy settings, a scrubbed copy, the variables a backend needs) |
| `refusal(output)` | optional: reads a failed command's output for the path or host the sandbox refused, so the unit's feedback names it |

**The registry** (`__init__.py`) mirrors `forges`: `register`, `get`, `names`, and `detect()`, which returns the first backend whose
platform matches and whose `availability()` is ok, in a fixed order (`landlock`, `seatbelt`, then `unavailable`). A repo may name one in
`abk.yaml` (`sandbox.backend`, default `auto`), which fails at load for an unknown name, as an unknown forge does.

**What is shared** is most of the work, and none of it belongs in a backend: the policy and the lists, absolute-path resolution, the proxy,
the launcher's start-up discipline (minimal imports), the `sandbox_coverage` value derived from `availability()`, the doctor and init checks,
the config guard's rule, and the tests. A backend's own job is small: turn a `SandboxPolicy` into the platform's restrictions and its command.

**Testing** follows the forge pattern: one parametrised suite (`tests/sandboxes/`) runs the same assertions over every backend the machine
supports (writes inside and outside, the protected file by each route, an inherited child, no lifting, a refused host, a clean failure when
the backend cannot start), so a backend that drifts fails the same test as the others. On a Linux machine the Seatbelt cases are skipped
with the reason; a CI job on macOS runs them.

A runtime never names a backend. `claude_code.spawn()` and ACP's agent spawn call `sandboxes.detect().command(policy, argv)`, so adding a
backend (or replacing Landlock with `bubblewrap` for a case it cannot meet) touches `sandboxes/` only.

## What the kit needs from its wrapper

The mechanism is judged against this list, not against what Claude Code's sandbox happens to do. The proof of concept below probes each.

1. **Write confinement by path.** Only the worktree, the `.git` parts a commit needs (`objects`, `refs`, `logs`, `worktrees/<id>`,
   `packed-refs`, `HEAD`, `FETCH_HEAD`), `$ABK_OUT`, the temp folder, the agent's own state folder and the tool caches. Not
   `.git/hooks` or `.git/config`. Not the planning repo.
2. **Config files unwritable by every route.**
3. **Inherited by every child, and not liftable** by the agent.
4. **Network by allowlist**, with a refusal that names the host.
5. **Fail closed.** If the mechanism cannot be applied the step stops with a message naming the cause, unless the repo allows it.
6. **Both runtimes, one policy.**
7. **Few installs.**
8. **Observable.** A refusal names the path or host so the person can widen the list.
9. **Cheap.** An agent step is not noticeably slower.
10. **Absolute, resolved paths**, so one rule means one thing on every runtime.

## Proof of concept

Run on this machine (WSL2, kernel 6.18.54.1, Python 3.12, unprivileged, nothing installed), in a scratch folder, with `git clone --local`
copies of the kit and no change to any real repository. The code was a ~60-line `ctypes` module, a ~25-line launcher, and a ~50-line
proxy. A headless `claude -p` step (Haiku, the `personal` account) was run under it.

| # | Question | Result |
|---|---|---|
| 1 | Is Landlock usable here, unprivileged? | **Yes.** ABI 7 (the network rule needs 4). The kernel is built with it (`CONFIG_SECURITY_LANDLOCK=y`) and it is enabled. |
| 2 | Does confinement hold for every route? | **Yes** for a shell redirect, an interpreter one-liner, `cp`, `sed -i`, `mv` out of the folder, an append, and a write through a symlink or a `..` path into a protected folder. A nested launch asking for wider rights could not lift it, and `sudo` is blocked by `no_new_privs`. Not probed: delete (the harness refused a removal in the probe). |
| 3 | Network by proxy? | **Yes.** An allowed host through the proxy returned 200, a refused host returned 403 from the proxy, and a direct connection to a hostname, to an IP, and to another local port all failed with `Permission denied`. |
| 4 | Does `claude -p` work under it? | **Yes.** It authenticated, reached the model through the proxy (only `api.anthropic.com` and `mcp-proxy.anthropic.com` were needed), wrote an allowed file and was refused a protected one. The connector hosts it also tried (Google, Datadog, Shopify and others) were refused without failing the step. It needs write access to `/tmp` (its per-session folder `/tmp/claude-<uid>/…` and a `/tmp/claude-*-cwd` file), its account folder, and the device files (`/dev/null` and friends). |
| 5 | Real work: git, `uv`, `npm`? | **Yes.** In a linked worktree a commit, push, amend, fetch and rebase worked with writes granted to the worktree and only the `.git` parts above, and `git config` and a hook install were refused. `uv sync` needed `~/.cache/uv` and `pypi.org`. `npm ci` ran from its cache with no extra grant (a cold cache would need `registry.npmjs.org`; not probed). |
| 6 | Path rules? | **Yes.** `~`, relative paths, `..`, doubled slashes and symlinks all resolve to one absolute path before a rule is added. Landlock binds a rule to the inode, so replacing a granted path with a symlink later does not widen it. |
| 7 | ACP's boundary? | **Simulated.** The kit starts an ACP agent, and its terminals, with `asyncio.create_subprocess_exec(*argv, …)`; prefixing `argv` with the launcher confines what that process runs (an inside write worked, an outside write was refused). This used the kit's call shape, not its `_Session` class, and no real ACP agent. |
| 8 | Overhead? | See [the table](#overhead). Small. |
| 9 | Can the hook rewrite each Bash command to run under the launcher? | **Yes**, silent or answering `allow`, **but it breaks Claude Code's shell state** (see [Where the layer is applied](#where-the-layer-is-applied)), so it is not used. |
| 10 | Failure message? | **Simulated** with the two errnos Landlock gives: `ENOSYS` (kernel without Landlock) and `EOPNOTSUPP` (disabled at boot). The launcher exits 97 with "sandbox could not start: … - <cause>". Not seen on a real kernel without Landlock. |
| 11 | Read confinement (not in the plan; added)? | **Yes.** With reads limited to system folders, the toolchain caches and the worktree, `git status` and the kit's `tests/config` (280 tests) pass, and `abk.yaml`, a credentials file and another repo's files are unreadable. |

### Overhead

Median of interleaved runs (wrapped and unwrapped alternating, both warmed), so cache effects are shared. The launcher is a minimal
Python start (`python -S`, no `argparse`, no `json`): the first version with `argparse` cost about 70 ms per start, the minimal one about 21 ms.

| Workload | Unwrapped | Wrapped | Difference |
|---|---|---|---|
| Launcher start (`true`, 100 runs) | 2.8 ms | 23.6 ms | +21 ms per launch |
| `git status` | 9.1 ms | 30.5 ms | +21 ms (the launch) |
| `git diff --stat HEAD~300` | 526 ms | 553 ms | +5% |
| `git log -p -50` (many objects) | 700 ms | 751 ms | +7% |
| `uv sync` (cached) | 42 ms | 68 ms | +26 ms (the launch) |
| `pytest tests/config` | 11.7 s | 11.8 s | +1.3% |
| Python import of the kit's dependencies | 1004 ms | 1042 ms | +3.8% |

Two costs, then: about 21 ms per launch, and a few percent on file-heavy work (Landlock checks each path access). A process wrap
pays the launch once per step; a per-command wrap pays it once per command, which for a step of a few hundred commands is a few seconds
against minutes. Neither is noticeable.

## Where the layer is applied

**One place: the agent process.** The whole `claude -p` or ACP agent process starts under the launcher once per step, so everything it
does is covered, including the file tools and every command, and every runtime is handled the same way. A second layer that wrapped only
the agent's commands was considered and dropped:

- For Claude Code it is not workable. The hook can rewrite each Bash call to start under the launcher, but Claude Code keeps the working
  directory between calls with a file it writes after each command: with the rewrite, a `cd` happened in the inner `bash -c` and the next
  call started back in the original folder (an exported variable is lost either way). The workaround (read the inner shell's final
  directory and `cd` the outer shell to it) is fiddly and was not tried.
- Doing it for ACP alone would leave two layers to build, test and explain, for one benefit (hiding the agent's credentials from its own commands).

The price of one layer is that a command the agent runs can read what the agent process itself needs, including the account's credentials
folder. The network allowlist (the model host only) limits what a command could do with it. It costs one launch per step, about 21 ms.

**ACP needs two wraps, not one.** The client starts every terminal itself, as a child of the kit and not of the agent, so wrapping the agent's
spawn does not confine the terminals: both the agent process and each terminal (`create_terminal`, one `create_subprocess_exec` call) start through
the launcher. The client still serves file reads and writes, and those checks (the worktree, `specs_dir`, fenced files) stay, because the kit's own
process performs those writes and is not sandboxed. `read_text_file` is limited to the policy's read list, and `create_terminal` ignores its `env`
argument today, so the child inherits abk's whole environment, the model gateway key among it: terminals get a scrubbed environment plus the proxy
settings. An agent that does its own file access, outside the client's methods, is covered by the process wrap.

## macOS

macOS needs a different backend, and **no package is needed for it**: Seatbelt is built into macOS and its command-line front end,
`sandbox-exec`, ships with it. The kit generates a Seatbelt profile (SBPL, a small Lisp-like language) from the same policy and runs
`sandbox-exec -f <profile> -- <agent command>` in the launcher's place. Anthropic's own sandbox runtime does the same on macOS and uses
`bubblewrap` on Linux, so the approach has a precedent (the agent vendor's open-source sandbox runtime,
[Anthropic's write-up](https://anthropic.com/engineering/claude-code-sandboxing)).

How the policy maps, from published descriptions of the profile language (not tried here):

| Policy | Seatbelt |
|---|---|
| default | `(version 1)` and `(deny default)`; a later `deny` beats an earlier `allow` for the same operation and path |
| write | `(allow file-write* (subpath "<dir>"))` per entry; `literal` for one file, `regex` for patterns |
| read allowlist | `(allow file-read* (subpath "<dir>"))` per entry, over a deny default |
| network | allow outbound to the proxy's loopback port only, `(allow network-outbound (remote ip "localhost:<port>"))`; everything else stays denied |
| parameters | `sandbox-exec -D NAME=value` fills paths into one profile text |
| debugging | `(debug deny)` in the profile and `log stream` on the `com.apple.sandbox` subsystem show what a profile refused |

The sandbox is inherited by every child and cannot be lifted, as Landlock's is. Known caveats from the sources:

- Apple marks `sandbox-exec` deprecated. It works through macOS 14 and is what browsers, Nix and Claude Code itself rely on, but it is a
  risk the kit should check on each new macOS release, and `abk doctor` should test it by running a probe, not by looking for the binary.
- Granting any network access tends to leave DNS (UDP 53) and Unix sockets reachable; the same limits as Landlock's, and to be listed in
  the doc's limits.
- A network setting in a profile can be silently ineffective on some versions (OpenAI's Codex hit "too effective" network enforcement),
  so the probe must prove a direct connection fails, as step 3 did on Linux.

The profile's base rules are a first guess, and the Mac proof of concept checks each of them:

- **Signals.** `(allow signal (target same-sandbox))` lets a confined process signal its descendants and nothing outside the sandbox
  (`(target self)` would stop a timeout or an interrupt killing a child). Check that a Bash timeout, `kill` and a test runner stopping
  its workers work.
- **Operations a toolchain may still need** under `(deny default)`: `ipc-posix-shm*` and `ipc-posix-sem` (Python multiprocessing, node),
  `file-ioctl` and `pseudo-tty` (terminals), `iokit-open`, `user-preference-read` and `system-socket`. Add each one a run shows is
  needed, with its reason.
- **`mach-lookup` is unfiltered.** `(allow mach-lookup)` reaches every launchd service, and a service can write a file or open a
  connection on a caller's behalf, which would get around the write list and the network rule. Narrow it to a `(global-name …)` list
  once the proof of concept shows which services `claude`, git and the toolchains use. Open until then.

**Not proven here.** There is no Mac on the development machine, so the macOS backend (`sandboxes/seatbelt.py`) was written from the
published descriptions and its behavioural cases have not run on a Mac. A person runs the proof of concept on one: the profile above, the
same eleven checks (writes by every route, no lifting, the proxy, `claude -p`, git, `uv`, `npm`, path
resolution, overhead, the failure message), and records what changed here. The proxy, the policy, the launcher interface and the lists are shared with Linux; only the
backend that applies them differs. Native Windows has no backend; it runs and warns.

## What it covers, and what it does not

Landlock's limits, found in the proof of concept:

- **Metadata is not governed.** `chmod` and setting timestamps on a protected file succeeded (a protected file went to mode 666; its
  contents could not be changed). Harmless for the config guard's purpose, and noted.
- **Path-name Unix sockets are reachable** on this ABI (the user's D-Bus socket connected). A Docker socket or an SSH agent would be
  reachable too. This machine has no Docker socket and no SSH agent. The launcher should also drop `SSH_AUTH_SOCK` and the D-Bus address from the agent's
  environment (not built; a step in the plan below).
  Governing them needs a newer ABI, or `bubblewrap`, which can hide a path.
- **UDP and DNS are not restricted.** A process can resolve names; it still cannot connect except to the proxy.
- **A rule only adds access.** A path inside a granted folder cannot be carved out (Claude Code's sandbox protects `.git/hooks` this
  way). The kit grants the `.git` parts one at a time instead, which worked.
- **It cannot hide a path**, only deny it; a read allowlist (note 11) gives the same effect.
- **Seatbelt's limits on macOS.** Apple marks `sandbox-exec` deprecated; it works through macOS 14, but each new release needs checking,
  which is why `abk doctor` runs a probe. Granting any network access leaves DNS and Unix socket paths reachable, as on Linux. A network
  rule can be silently ineffective on some versions, so the probe proves a direct connection fails and does not trust the profile.
- **Linux and WSL2 only for Landlock.** Landlock is a Linux feature. macOS uses Seatbelt (see [macOS](#macos)); native Windows has no backend and
  runs the step and warns.

What it does not do: judge a command (`gh pr merge` stays refused by the hook), or protect a path the agent is allowed to write.

## `sandbox_coverage`

`policy_coverage` (`runtimes/base.py`) says how much of what an agent does **the kit can interpose on**: `all_calls`, `agent_flagged`,
`none`. It is about reading a call. `sandbox_coverage` says how much of what the agent's **processes can do the kernel confines**,
whatever the kit saw. The two are independent: an `agent_flagged` ACP agent has full sandbox coverage when its process is confined.

| Value | Meaning | When |
|---|---|---|
| `process` | the agent process and every child run with their files **and** network confined | both runtimes, on a platform with a backend |
| `files` | files are confined but the network is not | Linux older than kernel 6.7 (Landlock without the TCP rule) |
| `none` | nothing is confined by the kernel; only the text and path policy applies | a runtime the kit cannot launch itself (hosted, remote), and a platform with no backend (native Windows) |

It is used three ways. `abk policy check` reports it per runtime beside `policy_coverage`. A repo that requires a sandbox level reads it,
and **when the level is not met the unit runs and warns**: the tick and `abk status` say the sandbox was not in force for the unit, and
at which level. And the config guard reads it: it can drop from failing the unit to a warning only where the step was confined (`process`
or `files`, since both stop writes to the file), because only then can an agent not have written it.

ACP's value carries the note **unverified against a real agent**: there is no ACP agent on the development machine, so what is proven is
the kit's side of the boundary, and `abk policy check` reports it that way until someone with an agent runs its probe.

## The policy

One new value on `ToolPolicy` (`runtimes/base.py`), built where the policy is built today (`wiring.py`, `init/propose.py`,
`serve/chat.py`):

```
sandbox:
  write:    the worktree, the .git parts a commit needs, $ABK_OUT, the temp folder, the agent's state folder, the profile's caches, /dev (files only)
  read:     an allowlist, not "/": system folders, the agent's own runtime and account folder, the profile's toolchain folders, the worktree, the specs snapshot
  network:  the model API host or gateway, the forge host, the profile's package index hosts, hosts the repo adds
  required: process | files | none        # what the repo needs; "run and warn" when the runtime falls short
```

**Where each list comes from.** The lists are assembled, not written out per repo:

1. **The kit's built-ins:** system folders to read, the temp folder and `/dev` to write, the model host.
2. **The runtime:** what the agent process itself needs, per runtime (for Claude Code its install and account folder and `~/.claude.json`;
   for ACP, per agent in `known_agents`, since each agent keeps its own state).
3. **The language profile.** `ToolchainProfile` (`profiles/base.py`) gains an optional member, `sandbox_paths(repo)`, declared like
   `created_files` (a profile without it adds nothing): the toolchain folders to read, the cache folders to write, and the package
   index hosts. `python-uv` names uv's cache and data directories (`.cache/uv` and `.local/share/uv` under the home directory) and `pypi.org` /
   `files.pythonhosted.org`; `node-npm` names npm's cache directory (`.npm` under the home directory) and `registry.npmjs.org`. A repo's profile, and the profile of each of its projects, contribute.
4. **`abk.yaml`, appended per repo (and per project):** `repos.<name>.sandbox.read`, `.write` and `.hosts` add to the lists, for what a
   repo needs that no profile knows (a vendored tool, a private package index).
5. **`abk.local.yaml`, for this machine:** the same three keys, for paths and hosts that differ by machine (a cache folder somewhere
   else, a gateway host).

The policy is the same on every machine (items 1 to 4); only item 5 differs. Every path is resolved to an absolute one (`~`, relative,
`..`, symlinks) before a rule is added.

## The planning repo, narrowed

Builders are already given only the specs folder, read-only. The design adds a per-unit **snapshot** of the files the unit needs (its
change's `tasks.md`, spec and follow-ups), written under the unit's `$ABK_OUT` and passed instead of the live folder, so a spec edited
mid-run does not change a unit under it. With a read allowlist the rest of the planning repo is unreadable, not just un-handed-over.

## The config guard afterwards

With the sandbox denying the two files, an agent cannot change them. The guard changes from "fail the unit on any difference" to
"warn": the tick logs that a configuration file changed during the run, shows the diff, and carries on with the settings it loaded.
It fails only when the step was not confined. A person can then edit `abk.local.yaml` at any time.

## Failure modes

- **No backend** (Landlock missing or disabled: an old kernel, a build without it, a locked-down container; or a macOS where `sandbox-exec`
  is gone; or native Windows): the step stops with the cause named, unless the repo's `required` is `none`. `abk doctor` and `abk init` check it before a unit starts. The TCP rule needs ABI 4 (kernel 6.7);
  on an older kernel files can still be confined and the network cannot, and the check says which.
- **A path the builder needs is not on the list:** the command fails with a permission error and the unit's feedback names the path.
  A first run is expected to need a few. A note for the person: Claude Code's own per-session folder is `/tmp/claude-<uid>/…`, so
  granting that exact parent also grants anything else kept there; the launcher grants `/tmp` as the temp folder instead.
- **A step that needs a running service is an e2e step, by rule.** A server on localhost, `docker`, a database, a message broker: anything
  that must be running for the test to pass makes it an e2e test and not an integration test (an integration test checks functionality
  across modules of one package and needs nothing running). Such a step runs under the e2e policy, its own path and host lists named in
  the project's configuration, and is held to the e2e rules for availability and schedule. The unit-test and integration policies never
  grant localhost or `docker`.
- **A hook or launcher bug fails closed:** the launcher exits non-zero with a message; it never `exec`s the command unrestricted.

## What is not confirmed

- **ACP against a real agent.** No agent is installed here. Whether an agent routes its commands and file work through the client, and
  does not do its own file access, is only known by running it. For an agent that does its own, `process` is the answer and the launcher supports it.
- **`@anthropic-ai/sandbox-runtime`'s source** was not read, only Claude Code's published sandbox documentation (through a research pass).
- **Delete and rename-over** of a protected file were not probed (a removal was refused by the harness); `mv` out of the protected folder was refused.
- **A cold `npm` cache** (it would need `registry.npmjs.org`), a cold `uv` cache with a git dependency, and other toolchains.
- **macOS.** The Seatbelt backend is designed from published descriptions and has not been run on a Mac.
- **Other kernels:** one WSL2 kernel was tested. CI images and other developers' machines are not covered.
- **A real `ENOSYS` or `EOPNOTSUPP` failure** (simulated here).
- **Whether an unknown ACP agent runs under a process wrap** with a short read and write list; its own state folders have to be found per agent.
- **The read allowlist on a whole agent process.** The process wrap was run with reads of `/`; the read allowlist was shown for
  commands only (note 11). A process wrap needs the agent's own runtime and account folders on the list, and for ACP each agent's own folders.
- **MCP servers and plugins** a builder might start inherit the restrictions under a process wrap, and may need paths or hosts the list lacks.

## Guards the sandbox makes duplicate, and those it does not

A read-only inventory of the kit's guards (2026-10-21) sorted them by what they say. A guard that only says **where** an agent may write is a
second, weaker copy of the sandbox once the step is confined, so it stands down **when the step is confined** and stays as the fallback
otherwise (native Windows, `required: none`, a backend that fails to start). A guard about **meaning**, or about a location the sandbox cannot
express, stays in both modes. The table below is kept in code in `runtimes/guards.py`, and `abk policy check` and `abk status` list each
guard per runtime as active, skipped (confined) or kept (meaning) from it, so the listing and the behaviour cannot drift.

| Guard | Class | When the step is confined |
|---|---|---|
| Hook: Edit/Write/MultiEdit/NotebookEdit must resolve inside the worktree (`hooks/policy.py`) | location | skipped; the sandbox refuses the write |
| Hook: the specs folder is read-only (`--specs`) | location | skipped; specs are outside the write list |
| Command rules: no redirect, `tee`, `cp`, `mv`, `dd` or `sed -i` onto the planning repo's `abk.yaml` and `abk.local.yaml` (`command_policy._check_fenced`) | location | skipped, except for a config file inside the checkout |
| ACP client: the same text fence on terminal commands (`acp.py` `_config_files`, `_fenced`) | location | skipped; terminals run under the launcher |
| Config guard: fail the unit if a configuration file differs after the step (`config_guard.py`) | location, after the fact | a warning with the diff; fails only when the step was not confined |
| `planning_paths`: paths inside the worktree the pipeline owns | looks like location, is ownership | **kept**: the worktree is one granted tree, and a rule cannot carve an exception out of it |
| Redirect must land in `.abk/out/<run>/` | convention inside the worktree | **kept**: the worktree is writable, so this still decides what a redirect may overwrite |
| ACP client: `_resolve_target`, `write_text_file`, the edit/delete/move verdict | location | **kept**: the kit's own, unsandboxed process performs those writes |
| Role tool lists (a reviewer cannot edit) | role | **kept**: the sandbox has no per-role write list |
| `--disallowedTools`, no merge, no push to protected branches, force-push and lease rules, no commit, no `--no-verify`, `AgentPushed`, `abk policy` | meaning | **kept** |
| `abk install-config` | a sanctioned write route | **kept**; it is a child of the confined agent and its write list already covers the worktree |

There is **no network or host guard** in the kit today: the proxy adds a capability and replaces nothing. Left for later: track and propose runs
(their checkout is the planning repo itself, so the state-directory rule cannot be a path list), and deleting the fallback guards once the
sandbox is required on every platform the kit supports.

## Specs

The recommended steps are written as seven changes in the planning repo, all priority 3: `sandbox-backends` (the base layer, the policy, the Linux
backend, the proxy, doctor and init), `sandbox-profile-paths`, `sandbox-claude-code` (with the config guard demoted to a warning),
`sandbox-acp`, `sandbox-e2e-policy`, `sandbox-macos-backend` (specced before the Mac proof of concept was run) and
`sandbox-retire-duplicate-guards`. Once built, what each does is specified in `openspec/specs/sandbox-backends` and its sibling
capability folders under `openspec/specs/`.

## Alternatives considered

- **`bubblewrap` and `socat`** (Claude Code's own choice). A fine mechanism, and the right fallback for hiding paths or governing sockets,
  but each machine needs `sudo apt` installs and, on newer Ubuntu, an AppArmor profile. The proof of concept found no requirement in the
  list that Landlock fails, so it is not needed now.
- **Claude Code's built-in sandbox** through `--settings`. It covers Bash and its children only, is configured in Claude Code's own
  terms that ACP ignores, and fails open by default. The kit turns it off for builders so there is one enforcement point.
- **Containers per builder.** The strongest isolation and the heaviest: git credentials, each account's login, caches and the Azure
  settings all have to be passed in. A later option if the sandbox proves too leaky.
- **A separate Unix user.** Cheap OS isolation, but each account's login and tool state must be set up for that user.
- **Read-only config files.** In the way of the person, and the builder runs as the person.
- **Detect only, with a smarter guard** (read the transcript for writes). It depends on parsing every tool call, the gap that made the
  whole-file comparison necessary.

## Divergences from Claude Code's pattern

| Divergence | Reason |
|---|---|
| The mechanism is Landlock plus an internal proxy, not `bubblewrap` plus `socat` | no operating-system install |
| Claude Code's sandbox is off for kit builders | one enforcement point and one set of failures; two layers would double the paths to allow |
| The kit wraps the agent process for every runtime, where Claude Code's sandbox wraps Bash commands only | ACP has no equivalent, a per-command wrap breaks Claude Code's shell state, and the same lists must hold for both |
| The `.git` parts are granted one by one | a Landlock rule cannot carve an exception out of a granted folder |
| Reads are an allowlist | Landlock cannot deny inside a granted folder, and it hides secrets |
| Fail closed is the default | Claude Code's default is to run unsandboxed; the kit's repos can opt down per runtime with `required` |
| A launcher that must stay minimal (`python -S`, no `argparse`) | 70 ms against 21 ms per launch |

## Recommended implementation steps

A recommendation from the proof of concept, not a commitment. Each step can become one OpenSpec change, tests first; the order proves
the cheap parts first and changes behaviour last.

1. **The base layer and the Linux backend.** The `sandboxes/` package: `base.py` (the protocol, `SandboxPolicy`, `Availability`), the registry,
   `policy.py` (assembling the lists and resolving paths), the launcher, and `landlock.py` (Landlock through `ctypes`, minimal imports, device
   grants, fail closed with the messages above), plus `ToolPolicy.sandbox` and the stand-in backend for tests. The parametrised suite runs
   the real restrictions in a subprocess: writes inside and outside, the protected file by each route, an inherited child, no lifting.
   Behind a switch, off by default.
2. **The profiles' `sandbox_paths`.** The optional `ToolchainProfile` member, filled in for `python-uv` and `node-npm`, with `abk doctor`
   reporting the assembled lists for a repo (so a missing path is found before a unit fails on it).
3. **The proxy.** The allowlist proxy, the proxy environment, the Landlock TCP rule, refusals that name the host; tests with a local
   upstream. Include the connector hosts Claude Code probes (refused, not fatal).
4. **Doctor and init.** `abk doctor` and `abk init` report whether a sandbox backend works (a probe, not a file check): Landlock present,
   its ABI and the TCP rule on Linux, `sandbox-exec` on macOS. The README's requirements line says Linux, WSL2 or macOS. No install helper
   is needed, because nothing is installed.
5. **Claude Code through the launcher**, for one repo (the kit's own): the `claude -p` process starts under it, with a probe test that a
   `claude -p` step cannot write the planning repo's config.
6. **The config guard becomes a warning** when the step was confined (`sandbox_coverage` is `process` or `files`); a person's edit no
   longer fails a unit.
7. **ACP through the launcher**: the agent process starts under it, `read_text_file` is held to the policy's read list, the terminals get a
   scrubbed environment and the proxy settings, and `abk policy check` reports `sandbox_coverage` per runtime (ACP marked unverified
   against a real agent). No e2e test: no agent is available. Unit tests use the kit's existing fake agents
   (`tests/runtimes/policy_fake_agents.py`) with the real launcher restrictions applied, and one parametrised suite asserts the same
   outcomes for the Claude Code path and the ACP path, so the two cannot drift. `abk policy check` ships with a probe a person with an
   agent can run.
8. **The e2e policy** for steps that need a service, and the rule that such a step is `[e2e-test]`.
9. **The macOS backend.** First a small proof of concept on a Mac (the checks listed in [macOS](#macos)), then `seatbelt.py` (the profile
   generator and its `sandbox-exec` command) behind the same `SandboxBackend` protocol, with the same parametrised suite running on a macOS CI job.
10. **The planning-repo snapshot** per unit.
11. **Default on**, once the units of the first repo have run under it cleanly.

## Decisions made

- The policy lives in `abk.yaml`, with machine-specific paths and hosts in `abk.local.yaml`.
- No operating-system install and no Node dependency where Python or the kernel can do the job; the install helper is built only if an
  OS package is later needed.
- When a repo requires a sandbox level the runtime does not meet, the unit **runs and warns**.
- A step that needs a running service is an e2e test by rule.
- ACP is written to the best standard possible without a local agent and reported as unverified against one.
- **One layer: the agent process.** There is no per-command layer, for either runtime.
- **A base layer and a backend per platform**, laid out like the forges: a `Protocol`, a registry, shared policy, proxy and tests, and a Landlock and a Seatbelt implementation (plus `unavailable` for a platform with none).
- **macOS is in scope**, through Seatbelt and `sandbox-exec`, which needs no package. It gets its own proof of concept on a Mac first.
- **The read allowlist comes from the language profile**, with `abk.yaml` (and `abk.local.yaml` for this machine) appending to it.

## Open questions

- **Who runs the macOS proof of concept**, and on which macOS versions (the sources say `sandbox-exec` works through macOS 14).
- **Each ACP agent's own folders.** The runtime part of the read and write lists has to be found per agent in `known_agents`, and cannot be
  checked until an agent is available.
- **Which paths each profile names.** The `python-uv` and `node-npm` lists above are what the proof of concept needed; a real run of a
  repo's units will find the rest, and the doc should say who keeps them current as profiles are added.
