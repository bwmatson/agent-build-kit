# One orchestrator, many workers: a local and a cloud deployment

The kit runs on one machine today. A timer starts `abk tick`, which builds units in its own threads or, in `processes` mode, starts `abk worker build <unit>`
processes on the same host ([worker-design.md](worker-design.md)). Every piece of coordination between them is a local file: `fcntl.flock` locks, pid-file
branch locks judged by the process start time and the host name, about twenty-five read-modify-write JSON stores and ten JSONL ledgers in `state_dir`, a SQLite
checkpointer and the locks in the machine's `local_dir`, and a wake file watched by a systemd path unit. The documents say one pipeline host is supported, and the capacity of a run is the capacity of that host.

This document describes one model for the pipeline with two deployments of it. The model is an **orchestrator** that decides what runs and **workers** that each
carry one piece of work, over a shared **store** and **queue**. A **local** deployment runs all of it on one machine; a **cloud** deployment runs the orchestrator
and the workers as cloud jobs over managed services. Each moving part is an interface with an implementation per deployment, the way a repository chooses its
forge today (`forges/base.py`, with a GitHub, an Azure DevOps and a local forge). The first cloud is Azure. It is a design, not a specification: paths and
function names are where the work happens today, and names for new things are proposals. Each [roadmap](#roadmap) item can become its own OpenSpec change.

## Goals and non-goals

**Goals**

- One model and one code path for scheduling, admission, building and landing, whichever deployment runs it.
- Capacity that is not one machine's: many workers at once, sized per job, with nothing shared on a local disk.
- Correctness that does not depend on a process being alive on a particular host: leases with fencing tokens instead of pid files, compare-and-swap writes instead of
  whole-file locks.
- A local deployment that keeps working at every step, on one laptop, with no cloud account.
- A cloud deployment on Azure, with the interfaces written so another cloud is another set of implementations.
- Work that needs something only one machine has (a live stack, a deploy key, a subscription login) still runs, on a machine that has it.

**Non-goals**

- Rewriting the unit graph, the build steps, the review loop or the policy code. They call interfaces; they do not change.
- Several installations sharing one cloud deployment. One deployment serves one installation.
- A long-running daemon. The orchestrator is a short round, started by a schedule or an event, as [worker-design.md](worker-design.md) decided.
- Moving the live stack of e2e tests into the cloud. E2E and deploy-and-test verification keep running where the stack is.

## The model

| Part | What it does |
|---|---|
| Orchestrator | One round at a time: planning sync, collection of the outside world, landing, gates, archive, readiness, admission and enqueueing, then it exits. It is the only part that polls a forge or a usage source. |
| Worker | Claims one work item (build, resolve or verify a unit), runs it to its next wait, records the outcome and exits. |
| Runner | A host that claims work items it has the capabilities for. A cloud job is a runner of one item; a laptop running `abk runner` is a runner for what only it can do. |
| Store | The units, the records the pipeline keeps (plans, verdicts, pauses, snapshots, landing intents and the rest) and the ledgers, with versioned writes. |
| Coordination | Leases with fencing tokens and semaphores: the dispatcher, the branch of each unit, chat sessions, the e2e stack, the unit-test slots. |
| Queue | The work items the orchestrator admitted and the workers claim. |
| Artifacts | Unit logs, failure bundles, transcripts and spec snapshots. |
| Secrets | Model keys, forge and push tokens, deploy credentials. |
| Model accounts | What a worker's agent runs on, and the budget or the usage window that bounds it. |
| Workspaces | The checkout a worker builds in. |
| Events | What starts a round sooner than the schedule: a worker that finished, a person's request. |

The rules that hold whatever the deployment:

- The orchestrator holds the **dispatcher lease** for its round. Its fencing token is written with every admission, so a round that lost its lease (a slow or
  suspended process) cannot admit on stale facts.
- A worker holds the **branch lease** of its unit while it runs and renews it with a heartbeat. Every store write it makes for the unit (the unit's row and the
  records it writes, such as verdicts) carries the lease's token, and the store refuses a write with a stale token. A worker that wakes from a suspend finds its
  token stale and runs its step again instead of recording a result.
- The token fences only the store. Effects outside it (a push, a pull request comment, model spend) are made safe to repeat instead: pushes use
  `--force-with-lease`, comments carry markers the kit already reads back, and spend is counted where it happened.
- Workers never poll. They read the outside world from snapshots the orchestrator keeps in the store (`pipeline/snapshots.py`: `pr`, `usage`, `pauses`) and ask for a
  fresh one with `request_refresh`, as they do today.
- Workers never write the planning repository. They read the spec snapshot taken at admission and the configuration at the planning commit named in their work item,
  and a fix change a worker needs is a request record the orchestrator turns into a commit.
- A work item names the code and configuration it runs: `kit_ref` (the kit's commit in the worker's image or checkout), `config_ref` (the planning commit plus a digest
  of the machine overlay) and `planning_sha`. The merge-edge rule (`pipeline/units.py`, `merge_loaded`) admits a dependent of a kit merge once the code the workers
  run contains that merge.
- People act through intents: `requeue` and `approve` as today, and new unit `hold`, `release` and `prioritize` commands (today `hold` and `release` act on an e2e
  split, not a unit), write a record and an event, and the next round acts on them. Running ticks by hand to push a unit through is not needed.

## Two deployments

`deployment.kind` in `abk.yaml` names the deployment: `local` (the default) or `azure`. Its settings that belong to one machine or one subscription (endpoints,
resource names, identities) go in `abk.local.yaml` or the secret store, never in committed configuration, the rule account directories follow today. A repository
keeps choosing its forge as it does now; the deployment does not change which forge a repository uses.

| | Local | Azure |
|---|---|---|
| Orchestrator | `abk tick` from the timer and the wake path | Two Container Apps jobs from one image (a job has one trigger type): a scheduled job every one to two minutes, and a manual job that the CLI or a finishing worker starts through the Azure Resource Manager API. The dispatcher lease keeps their rounds from overlapping. |
| Workers | Processes (`pipeline/spawn.py`: a transient systemd unit, else `Popen`) or a local container | A manual Container Apps job: the orchestrator starts one execution per work item |
| Store, coordination, queue, checkpoints | SQLite under `state_dir`, on a local disk (SQLite's locking does not work on a network drive; sharing state between hosts means the PostgreSQL store), one schema | Azure Database for PostgreSQL, the same schema |
| Artifacts | Files under `state_dir` | Azure Blob Storage |
| Secrets | The environment, `.env`, secret files, `gh` and `az` logins, SSH keys | Azure Key Vault through a managed identity |
| Model accounts | Subscription logins and API-key accounts, keys from the environment | API-key accounts only, keys from Key Vault |
| Workspaces | Worktrees on `repos.<name>.path` | Partial clones on the job's disk |
| Events | The wake file and its path unit | Starting the manual orchestrator job |
| Images | The kit checkout | Azure Container Registry |
| Telemetry | The existing OTLP export, journald and run logs | The same export to Azure Monitor (through the environment's OpenTelemetry agent or native ingestion; which signals each carries is to verify) |
| Sandbox | Landlock, as [sandbox-design.md](sandbox-design.md) describes | The container and its network as the boundary (see [Workers](#workers)) |

## Interfaces

Each interface is a Protocol under `agent_build_kit/orchestration/` with an implementation in `orchestration/local/` and one in `orchestration/azure/`, and a stand-in
for tests, the layout `forges/` already has. The Azure implementations need their SDKs, which are an optional extra (`agent-build-kit[azure]`), so a local install
needs nothing new. Every interface has a conformance suite that both implementations pass, in the change that adds the interface: locally, and for Azure against PostgreSQL and
Azurite in containers in CI. Telemetry, at the end of this section, is configuration of the existing export rather than a Protocol.

### Store

- Units: `get(id) -> (unit, version)`, `list(filter)`, `put_if(id, unit, version, fence)`, `update(id, fn, fence)` (a compare-and-swap retry loop) and
  `append_history(id, entry)`. `UnitStore` (`pipeline/unit_store.py`) stays the façade with its domain methods; only its reads and writes move under it.
  `UnitStore.replace_if_unchanged` is already a compare-and-swap over a set of units (it writes the changed ones, removes some, and runs a callback while the store
  is locked); it becomes one transaction of `put_if`s and deletes that fails as a whole.
- Records, one kind per JSON store of today, named by area rather than file (`planned`, `verified`, `snapshots`, `prs` for `prs-<repo>.json`, `pauses` for the
  pause markers, `usage-cache`, `verdicts`, `audits`, `landing`, `e2e-held`, `tracker`, `notifications`, `tick`, and the rest): `get(kind, key)`,
  `put_if(kind, key, body, version, fence)`, `scan(kind)`.
- Ledgers, one stream per JSONL file of today (`usage-ledger`, `test-runs`, `flakes`, `decisions`, `admissions`, `product-defects`, and the rest): `append(stream,
  record)` and `read(stream, since)`.
- Local: SQLite on a local disk. Azure: PostgreSQL. One schema serves both; a unit is a row with a version column, a record kind is a table, a ledger is an append-only table.
- Today's files move into the store once, with `abk state import`.

### Coordination

- `acquire(name, holder, ttl) -> Lease{token}`, `renew(lease)`, `release(lease)`, `holder(name)`, and `semaphore(name, capacity)` with `acquire(holder, ttl, rank)`.
- Tokens only increase, and the store checks them on fenced writes.
- Two scopes. **Installation** scope is shared by every host: the dispatcher, each unit's branch, chat sessions, the e2e stack, the environment, per-account build
  places. **Host** scope is one machine's: the unit-test slots (they share that machine's CPUs) and the git directory a local worktree shares.
- Local: lease rows in the SQLite store, and the host-scoped semaphores on the machine. Azure: lease rows in PostgreSQL (a conditional update on `expires_at` and the
  token sequence). No separate lock service is needed.
- It replaces `workspaces.branch_lock`, `lease.Leases`, the slots of `pipeline/unit_test_slots.py`, `e2e.lock`, `environment.lock`, `dispatcher.lock` and the
  `.admission` lock, and with them the rule that a lock written by another host always counts as alive. The repository's `repo_turn` stays, as the local
  `Workspaces.git_lock`.

### Queue

- `enqueue(item, dedupe_key)`, `claim(capabilities, visibility) -> claim`, `heartbeat(claim)`, `complete(claim, outcome)`, `abandon(claim)`.
- A work item carries its kind (`build`, `resolve`, `verify`), the unit, the attempt, the capabilities it needs, `kit_ref`, `config_ref`, `planning_sha` and the
  admission's fencing token. The visibility timeout is what the `starting` marker (`STARTING_TTL`) is today.
- Local and Azure: a queue table in the store, claimed with `FOR UPDATE SKIP LOCKED` on PostgreSQL and a conditional update on SQLite. A managed queue is a later
  option, not a need.

### Launcher

- `launch(item) -> handle`, `status(handle) -> running | exited(code) | unknown`, `cancel(handle)`, `capabilities()`.
- Local: `pipeline/spawn.py`, as today. Azure: one execution of the manual worker job per item, started by the orchestrator; `status` comes from the job's execution and its exit code maps to a unit's
  state as a process's does today, for `reconcile_running` and `reclaim_stranded`.

### Artifacts

- `put(key, data)`, `get(key)`, `list(prefix)` and a streaming `writer(key)` for a unit's log while it runs. Redaction runs before a write, as it does for stored output
  today.
- Local: files under `state_dir`, where they are today. Azure: Blob Storage, read through short-lived links by the CLI and the web UI.

### Checkpoints

- `open() -> BaseCheckpointSaver`, with the serialisation allowlist the checkpointer uses today.
- Local: the SQLite saver `graph/checkpointer.open_unit_graphs` opens today. Azure: LangGraph's PostgreSQL saver on the same server. An Entra token used as the
  database password expires, so each new connection of the store's pool and of the saver's pool fetches a fresh one (to verify for the saver's pool). The branch lease keeps one writer per
  unit's thread.

### Secrets

- `get(name)`, `env_for(names, ttl)`.
- Local: the environment, `.env`, secret files at their configured paths, the `gh` and `az` logins and SSH keys, read where they are read today. Azure: Key Vault
  through the job's managed identity, with tokens that expire: a GitHub App installation token for GitHub (the App's private key is in Key Vault and the orchestrator
  mints the token), an Entra token for Azure DevOps (the identity is added to the organization as a licensed user), and a push over HTTPS with the token instead
  of an SSH key. These tokens last about an hour and a build can last longer, so a git credential helper fetches a fresh one during a run.

### Model accounts

- An account has a kind. A `subscription` account is today's Claude Code login (`claude_account.py`, a config directory, the usage window and the usage guard in
  `pipeline/usage_guard.py`); it is local only. An `api_key` account names a secret, an endpoint (the Anthropic API, or Claude models on Microsoft Foundry), a budget
  per window and per unit, and a rate.
- `environment_for(account, step)`, `reading(account)`, `reserve(account, estimate)`, `settle(reservation, actual)`.
- An API key's budget is a soft limit. The orchestrator sums the spend of each account and window from the usage ledger (or from a gateway's figures,
  `pipeline/gateway_usage.py`) and publishes it as the reading the usage guard already reads (`runtimes/providers.ProviderReading` already models a budget in money).
  Admission stops starting units at the budget, and a per-unit cap is checked between agent steps. A rate-limit answer becomes a shared backoff snapshot.
- Local: subscription and API-key accounts, keys from the environment. Azure: API-key accounts only, keys from Key Vault, readings from the ledger.

### Workspaces

- `prepare(repo, base, branch) -> workspace`, `fetch(refs)`, `push(branch, force_with_lease)`, `dispose()`, `git_lock()`.
- Local: `git worktree add` on `repos.<name>.path`, as today, with the repository's `repo_turn` as `git_lock` (worktrees share one git directory).
- Azure: a partial clone into the job's disk with a git directory of its own, so no refs, `rr-cache` or lock files are shared, from an optional mirror. `git_lock` does
  nothing there; correctness between hosts comes from `--force-with-lease` and the branch lease's token.

### Events

- `notify(kind, key)`, `subscribe()`.
- Local: the wake file and its path unit, and the timer (`pipeline/wake.py`). Azure: starting an execution of the manual orchestrator job through the Azure
  Resource Manager API; the scheduled job is the fallback. Forge webhooks can feed it later.

### Telemetry (not a Protocol)

- The OTLP export the kit has, with resource attributes for the installation, the worker and `kit_ref`. Local: journald and the run logs. Azure: Azure Monitor through
  the same export (which signals arrive is to verify).

## The orchestrator

A round is one function over the interfaces, the round `abk tick` runs today (`cli/pipeline.py`: `cmd_tick`, `_tick_with`, `_dispatch`). It keeps:

- the admission functions, which are already pure (`pipeline/occupancy.py`: `occupied`, `free`, `account_room`, `emergency_free`, `capacity`) and
  `pipeline/admission.admit`, reading live leases from coordination instead of pid files, with a capability filter in front;
- the rebuild budget (`REBUILD_BUDGET`, `REBUILD_WINDOW`);
- the snapshot server (`serve_snapshots`, after the PR collection in `poll_all`) and the drift test that keeps the poll and usage-endpoint functions out of a worker's entry point.

Verify runs as a worker kind (step 4 of [worker-design.md](worker-design.md), "Resolve and verify workers", in progress as the change
`worker-restack-verify-cutover` in the installation's planning repository), so a deploy that takes an hour no longer holds a round, and every round is short.
Locally the round is `abk tick`; on Azure it is the scheduled job or the manual one an event starts. Either way it holds the dispatcher lease for its round and exits.

`abk status`, `abk explain` and `abk serve` read through the interfaces, so they show the same thing for either deployment. The CLI talks to the deployment its
`abk.local.yaml` names. A hosted `abk serve` behind Entra sign-in is a later step.

## Workers

The worker's contract is the same in both deployments: claim an item, check its `kit_ref` and `config_ref`, take the branch lease, run the unit's graph to its next
wait from the checkpoint (`cli/worker.py` calling `cli/pipeline.build_unit` with `from_snapshot=True`), record the outcome, complete the item, notify, exit.

**The image.** It has Python 3.12 with the kit installed at `kit_ref` (the policy hook runs `sys.executable -m agent_build_kit.hooks.policy`), uv, git, node and npx
with the pinned OpenSpec CLI, the `claude` command, the allowlist proxy, and a layer per toolchain profile. Publishing a new image on each kit merge is what moves
`kit_ref` forward in the cloud. Locally the same entry point runs from the checkout or in a local container.

**What is injected per item.** The model account's environment, the forge and push tokens, the store, queue and artifact endpoints, the item's id and the telemetry
endpoint. No account directory and no SSH key go into a cloud worker.

**The sandbox in a container.** Landlock needs the host kernel's Landlock module and syscalls that container runtimes may filter, and Azure does not document
either for Container Apps, so a cloud worker does not depend on it. The boundary is the container and its network: the agent runs as a separate unprivileged user
set in the image; the kit, its hooks and the agent's settings are owned by another user and not writable by it; and egress is limited by the environment's network
(a workload-profiles environment with a user-defined route through a firewall, or a network security group), with the kit's allowlist proxy as the list of allowed
hosts, since a process can ignore the proxy settings. Whether the root filesystem can be made read-only, which Container Apps may not expose, is to verify, and so is
Landlock on its runtime, which is added where it works. A new coverage value `container` describes this; where it ranks against `process` and `files`
(`sandboxes/base.py`, `Coverage` and `reaches()`) and which `sandbox.required` it satisfies is decided in the `worker-image` change. Locally the sandbox is Landlock
as today.

**Capabilities.** A runner advertises what it can do: `build`, `resolve`, `verify`, `e2e:<dimension>`, `subscription:<account>`, and a size class. Admission matches
a work item's needs to them. `tests.e2e_available` becomes a local runner's capabilities. A laptop running `abk runner` claims, from a cloud queue, the items only it
can run. It is not a daemon: a timer starts it for one claim pass, and it polls the queue, never a forge: e2e and verify, which need the live stack, the deploy keys and the secret files there, and units on a subscription account.

**Resources.** A unit-test slot is host-scoped, so a cloud job has its own, and `tests.max_workers` follows the CPUs the job asked for. Package caches come from the
image or a cache volume.

## The planning repository

The orchestrator owns the planning repository: it keeps a clone and commits through the existing publish path (`planning.publish`). The tracking copies of a change's
`tasks.md` become store records, written into the repository when the change archives. `tracker.yaml` and `external.yaml` stay files people write, read and committed
by the orchestrator. A worker that needs a fix change (a flake, a failure on the base) writes a request record, and the orchestrator writes and commits the change.

## Today's state, and how it moves

| Today | In the model |
|---|---|
| `units.json` under one `flock`, rewritten whole | Unit rows with versions; `UnitStore.update(fn)` |
| About twenty-five JSON stores, most under a `flock`, a few with none | Record kinds with versioned writes |
| About ten JSONL ledgers, some trimmed in place | Append-only ledger streams |
| Branch locks, leases, slots, `e2e.lock`, `dispatcher.lock`, `.admission` | Coordination leases and semaphores with tokens |
| `starting` markers in `units.json` | The queue's visibility timeout |
| Run logs, failure bundles, transcripts, spec snapshots | Artifacts |
| `unit-graphs.sqlite` | Checkpoints |
| `runs/wake` and the path unit | Events |
| Worktrees sharing one git directory per repository | Workspaces (worktrees locally, clones in the cloud) |

`abk state import` moves an installation's files into the store once. After that the files are not written.

## Roadmap

Each wave ships the local and the Azure implementation together, each passing the interface's conformance suite in that wave. At every step a local install keeps working: a local implementation replaces the file-based code in
the same change that adds the interface.

**Wave 0** — `worker-restack-verify-cutover` (in flight): resolve and verify become worker kinds and the tick's thread pool is deleted.

**Wave 1: the store, in both deployments**

- `deployment-selects-implementations`: `deployment.kind`, the registry of implementations, and `abk doctor` checks for each deployment.
- `units-and-records-live-in-the-store`: the schema for units, record kinds and ledgers with SQLite and PostgreSQL implementations; `UnitStore` as the façade with
  `update(fn)`; the writers moved one area at a time; `abk state import`.
- `coordination-has-leases-and-fencing`: leases and semaphores in the store, fenced writes, and a heartbeat that finds a stale token after a suspend and runs the step
  again.
- `artifacts-and-checkpoints-have-implementations`: files and Blob Storage; the SQLite and PostgreSQL savers.

**Wave 2: workers from a queue, in both deployments**

- `workers-claim-work-items`: the work item, the queue table, and the launcher with its process and Container Apps job implementations.
- `worker-image`: the image's contract, publishing to the registry on a kit merge, the separate user, the network egress limit with the proxy's allowlist, the
  `container` coverage value, and the telemetry resource attributes.
- `workspaces-have-a-clone-implementation`: worktrees locally and clones in the cloud.
- `secrets-have-implementations`: the environment and files locally; Key Vault with a managed identity, and tokens that expire and are refreshed during a run,
  in the cloud.
- `model-accounts-have-kinds`: subscription and API-key accounts, the Anthropic API and Microsoft Foundry endpoints, budget readings from the ledger, a per-unit cap,
  a shared backoff. It is in this wave because a cloud worker needs an API-key account to run on.

**Wave 3: the orchestrator, in both deployments**

- `the-round-runs-over-the-interfaces`: events, admission under the dispatcher lease, capability matching; the timer locally, and the scheduled and manual
  orchestrator jobs in the cloud.
- `the-orchestrator-owns-the-planning-repo`: tracking records, fix-change requests, the spec snapshot and the planning commit for workers.
- `cli-writes-intents`: requeue, approve, and new unit hold, release and prioritize, against either deployment.

**Wave 4: running on Azure**

- `azure-deployment-as-code`: Bicep for the database, the Container Apps environment (workload profiles, with the network egress limit) and its scheduled,
  manual orchestrator and worker jobs, the registry, Blob Storage, Key Vault, the managed identities and monitoring; `abk deploy azure` and its doctor checks.
- `hybrid-runner`: `abk runner` claims e2e, verify and subscription items from the cloud queue.
- `two-host-conformance-suite`: races between two rounds and two runners against a real deployment, and the authentication paths Azurite does not cover (Blob
  user-delegation links, Entra sign-in to the database). The per-interface suites already run in each wave.

**Wave 5: operations**

- `budgets-alerts-and-spend-report`, `forge-webhooks-as-events`, `hosted-serve-with-entra-auth`.

The kit's own open changes `state-can-live-on-a-network-drive` and `task-progress-is-tracked-in-the-state-home-and-archived-to-the-repo` are taken up by this roadmap:
sharing state between hosts is the PostgreSQL store's job rather than a network drive's (the SQLite file stays on a local disk), and the second becomes the tracking records of wave 3.

## Decisions

- One model, two deployments, chosen by `deployment.kind`; interfaces with an implementation per deployment, as forges have.
- Azure is the first cloud.
- PostgreSQL-compatible SQL for the store, coordination, queue and checkpoints, with SQLite for the same schema locally.
- API-key accounts in the cloud; subscription logins stay a local account kind.
- A soft spend limit: admission stops at the budget, and a per-unit cap is checked between agent steps.
- The container and its network are the cloud sandbox; Landlock where the runtime allows it.
- E2E, verify and subscription-account work runs on a runner that has them (hybrid).
- No daemon: the orchestrator is a short round, and `abk runner` is a timer-started claim pass.

## Open questions

- One installation per cloud deployment is assumed. Is any form of sharing ever needed?
- Does Claude Code on Microsoft Foundry cover everything the agent steps use, or is the Anthropic API the first endpoint?
- Is a GitHub App available for the repositories, and an Entra service principal for Azure DevOps, so every forge token expires?
- Do deploy keys ever leave the machine that runs verify?
- Should the resolutions git's `rerere` learns be kept per repository as an artifact, now that a cloud workspace starts empty?
- What are the default budget windows and caps, and who is told when one is reached?
