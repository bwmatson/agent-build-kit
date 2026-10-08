# Changelog

## Unreleased

- A `Needs: ... merged` line added to a unit that has already started now gates it. A failed or
  held unit requeued before the dependency merges waits as `planned` with the cause `gated`,
  keeping its work, and `abk requeue` and `abk status` name the group it waits for; the tick
  resumes it in the mode it was requeued with once the dependency has merged. A unit sent back
  for rework waits the same way, and a running one is told once and left alone. A merge gate is
  never the unit's base, and an edit that only adds a `Needs:` line no longer re-plans the change.

- `ABK_GITHUB_API_URL` sets the address GitHub calls go to, for GitHub Enterprise or a
  stand-in host in a test. The forge and `abk doctor`'s credential check both use it, and
  a trailing slash is ignored. Unset, it is `https://api.github.com` as before.

- An ACP step now records its session id as soon as the session opens, so an interrupted step can
  be continued. When the agent declares that it can load sessions, the next run loads the recorded
  session; when it cannot, the step starts over in a new session with its full prompt, and the
  unit's log says the earlier one cannot be continued.

- The pipeline now keeps a local record of each tick's duration, each pause for usage, each
  unit's review rounds, each failed check and each unit's outcome in the usage ledger, whether
  or not telemetry is on, with the unit and change they belong to. Archiving a change rolls up
  its usage lines and leaves these records.

- `abk serve` starts a read-only web server on the loopback address (port 8765, or
  `--port`) over the pipeline's state: the units with their state, cause and history,
  each unit's run logs from a byte offset, and the usage report as `abk report --json`
  prints it. Units are addressed as `change/N`. Nothing it reads is changed. A port already in use is reported by
  name with a non-zero exit. It also serves a web UI: the pipeline overview, a page for each unit (state, cause,
  holder, note, review round, history, logs that follow a live run, usage) and the usage report. Build it
  once with `npm install --prefix web && npm run --prefix web build`; until then the pages say so.
  A metrics page lists every metric the code emits with its type, attributes and a chart
  (labelled series, axes and values), and says whether Prometheus (`ABK_PROMETHEUS_URL`) or
  local files drew the charts; without Prometheus, cost, tokens, turns, node and wait
  durations, the pipeline's own metric records (tick and unit durations, review rounds,
  check failures, usage pauses) and units by state are derived from the usage ledger and
  the unit store. It also
  lists recent traces from Tempo (`ABK_TEMPO_URL`), or from the ledger's spans when Tempo
  does not answer, and links to the pipeline dashboard in Grafana. The
  shipped dashboard now sums samples over each window instead of taking rates, which
  undercounted the exporter's delta data.

- A unit's run log now keeps the agent's replies and commands in full instead of clipped
  to a line. Line breaks are written as continuation lines indented by four spaces, so a
  line at the margin is always a new entry. The journal is unchanged: one clipped line
  per step. The `abk serve` log endpoint returns each reply as one entry, and a poll that
  begins inside a reply marks its further lines `continues`. Older logs still read as
  written.

- A step killed while its agent was editing now resumes over the files the agent left
  instead of failing on a dirty worktree. A recorded session is continued as before; a
  new session is told which paths are uncommitted work from an interrupted run, and the
  step's commit includes them. Uncommitted changes that are not a killed step's own, such
  as a hand edit, hold the unit with the cause `dirty_worktree` and the paths rather than
  failing it, and `abk status` lists it as parked until it is cleaned and requeued, which
  resumes a park at an agent step at that step with its inputs intact (a park elsewhere
  begins again at the start; a requeue before the tree is clean leaves it parked). A
  review never counts as editing, so a dirty tree under a killed review parks the unit.

- Every agent node now reaches its agent through one `run`, which takes the model for
  the call, and each completed node leaves its role's session (`build` or `review`) and
  the model the build began on in the unit's state. Nothing resumes a session yet and no
  behaviour changes; a unit saved by an earlier release loads with no sessions recorded.
  `abk.yaml` gains `session_reuse`, per agent role (`build` on, `review` off by default); a
  role it does not name is off, and `review: true` or an unknown role is refused. Nothing
  reads it yet.
  Agent calls that were labelled `rework` in usage records and in the `role` attribute of
  the `abk.agent.turns` and `abk.agent.tokens` metrics are now labelled `implement`, so a
  dashboard splitting by role loses its `rework` series; `abk report --by model` still
  tells them apart.

- A pull request description is shrunk to what the host accepts instead of being refused:
  a long tier 2 output loses its start first, then follow-ups are cut to whole items, and
  the output is dropped last, keeping the pass or fail line. A forge cuts anything still
  over its limit on a line, closing an open code fence or details block.

- An archived change keeps its usage breakdown: the per-unit summary written when a change
  is archived now carries one item per node, role, model and source, summing to the
  totals, so `abk report --by node`, `--by role` and `--by model` split archived work as
  they did before it was archived instead of showing it as one `(summary)` row. Totals
  are unchanged. A summary from an older ledger still loads and shows as one
  `(archived, no breakdown)` row.

- Breaking: a `units.json` with a unit that still carries a value in one of the previous
  engine's fields (`review_rounds`, `deferred`, `pending_replies`, `person_comments`,
  `resume_from` or `classic_run`) no longer loads; the error names the unit and the field.
  Finish or requeue that work with the release that wrote it first. The empty
  `resume_from` and `classic_run` the last release wrote on every unit are dropped on
  read, so a store it wrote loads as it is. The tick no longer moves such units onto
  threads.

- `abk telemetry push-dashboard` works with `ABK_GRAFANA_URL` alone: without
  `ABK_GRAFANA_TOKEN` it sends no authorization header, for a Grafana that accepts anonymous
  editing. With a token nothing changes. When an anonymous push is refused (401 or 403) the
  message names `ABK_GRAFANA_TOKEN`, and `abk doctor` reports whether a configured Grafana is
  used with a token or anonymously.

- Units are planned smaller by default: a floor of 400 and a ceiling of 750 estimated
  lines. The planner is told what an estimate counts (every file, deletions for code a
  group removes, no generated files, high when unsure). Each unit's actual changed lines
  are recorded from the host when its pull request is opened and after each push, less the
  new `limits.generated_files` patterns (lockfiles by default). A unit over the ceiling is
  logged, marked on the graph page and listed by `abk status`, and is not blocked.

- Each agent run has its own ignored scratch folder, `.abk/out/<run>/` in the worktree, and
  is told where it is in `ABK_OUT`. The build, rework and resolver prompts tell the agent
  to redirect long command output and exit status there, read it with `tail`, `grep` or
  `sed -n`, and not rerun a command to see more of it; the reviewer is told to run its own
  commands. The command policy allows a redirect into the folder and refuses one onto a
  tracked file or anywhere else in the worktree. The folder is git-excluded through the
  repository's local exclude file, removed when the run ends, and a killed run's leftovers
  are removed when the unit next runs or its change is archived. A file in a live run's
  folder past a size cap is cut to its tail. No agent's output reaches another agent or
  replaces tier 1's own run.

- Each repo has a `changelog` setting in `abk.yaml`: the path of its changelog (default
  `CHANGELOG.md`), or `null` to turn the changelog convention off. For a repo with it on,
  the build, rework, test-writing, resolver and review prompts carry the convention, from
  the repo's own `## Changelog` section in `AGENTS.md` or else `CLAUDE.md`, or from a
  packaged text where it has none, and tier 1 runs the new `abk changelog check [PATH]`,
  which reports a conflict marker, bullets run together or repeated, a bullet outside a
  section and headings out of order with the file and line. A repo with no changelog
  file yet passes the check with a note, and `abk doctor` warns about it.
  `abk init` also writes the convention into each such repo: a marked block in its
  `AGENTS.md` (else `CLAUDE.md`, else a new `AGENTS.md`), a changelog where it has
  none and a `merge=union` rule in `.gitattributes`, so concurrent entries merge
  without a conflict. A second run changes nothing, `--dry-run` lists each action,
  nothing is committed in the repos, and `abk doctor` warns about a changelog with
  no union rule.

- Why a unit stopped is a recorded cause (rework, base changed, upstream went back, usage,
  depth, toolchain, review escalation, a reviewer's hold, requeued, and the like) kept on each
  change that stops, holds or sends back a unit, and the
  pass lets a unit it already built back in by that cause alone: only rework and a changed
  base. Rewording a note changes no decision, and the depth hold keeps the branch it is still
  on as a field. A record with no cause is not readmitted mid-pass, and `abk status` lists it under
  `no recorded cause`. In the same way a requeue carries a reason, a rework
  the kind that sent the unit back, and saved feedback its source, as fields: the words of a
  person that begin like a check failure are still review feedback, and a run ends in one
  `UnitOutcome`, and a unit's state is a `UnitState`. Feedback saved before the upgrade
  has no source and is treated as review feedback, so `abk requeue --rework` on an older
  tier 1 failure sends its output under the review prompt; `--restart` avoids this. A toolchain profile the framework does not implement raises
  `ProfileUnsupported`, and only that holds a unit as toolchain; any other
  `NotImplementedError` fails the unit.

- A running pass now does everything a tick does before building, at each refresh as well
  as at the start. A change added or edited while builds run is planned, a change whose
  units have all merged is verified live and archived, a killed run is reclaimed, and the
  usage guard is asked again, instead of all of it waiting for the next tick. Live
  verification takes the live-stack lock without waiting and is skipped for that round
  while a tier 2 run holds it. A step that fails is logged and the rest still run. A unit
  whose thread a review comment resumed is started again within the pass, and holds no
  build slot while it waits for one.

- An archive that fails, or a finished change whose directory is gone (withdrawn), no longer
  ends the tick before the other changes are archived or anything is built. The failure is
  logged with its reason and the change is skipped; the next tick tries it again. `abk verify`
  exits 1 when the change it verified was not archived, and says why.

- GitHub is reached over its REST and GraphQL APIs through `githubkit` (a new dependency,
  pinned to one minor version; it brings `httpx`, which the transport already used) instead
  of `gh` subprocesses, with one client per repo owner built from that owner's credential,
  HTTP caching off and a timeout and a bounded retry on every call.
  Listing pull requests is one query per page and reads every page, no operation starts a
  process, and results are unchanged. `gh` is now only a credential source (and the agent's
  own `gh pr view`); `shell.gh`, `gh_out` and `gh_json` are removed. Taking a label off a
  pull request now raises on a 404 that is not "label does not exist", so a credential that
  cannot see the repository is no longer read as success. A refused host call
  raises a `TransportError`, now a `RuntimeError`, that carries the host's status and body,
  and `Forge.client` may be left unset by a forge that needs no command on the machine.

- Azure DevOps is reached over typed REST through the shared transport instead of `az`
  subprocesses. A listing starts no process, reads every page (pull requests, policy
  evaluations, an iteration's changes), and keeps its reads of open pull requests within a
  bounded pool; results are unchanged. A PAT is sent as a Basic credential and, without one,
  the `az` sign-in session's token as a Bearer, read again once the host rejects it (it expires), so
  `az` is now only a credential source. A response that is not the document expected raises an
  error naming the endpoint. `pipeline/az.py` and the `permitted_commands` carve-out for
  `az repos pr update` are removed: nothing the pipeline does needs a command exception.

- The build, rework and restack resolver prompts carry the `## Changelog` section of the built
  repo's own AGENTS.md; a repo without one is told nothing about the changelog. The resolver
  keeps both sides' bullets and folds two that describe one change when CHANGELOG.md conflicts
  or the repo has the section. The reviewer leaves the changelog's form and wording to the
  repo's own checks only where the repo states a convention. `tests/test_changelog.py` fails
  tier 1 in this repo on a conflict marker, bullets run together or repeated, a bullet outside a
  section or headings out of order.

- A push is read in one place, `pipeline/git_output.py`: it runs with `--porcelain` and a fixed
  locale, and only a stale lease is reported as someone else's push. A remote's refusal (a hook,
  branch protection) or a non-fast-forward is now an ordinary push failure carrying the remote's
  message, where it used to be reported as a stale lease. The rerere replay notice is read there
  too. A failed `claude` run comes from the closing event's `is_error` and subtype, whatever
  the exit status (only an explicit success subtype is a success), a closing event with an
  `api_error_status` of 429 is a rate limit without reading its words, and a denied ACP tool call
  from its status and a known denial code, with the phrase lists as the fallback. The red check
  judges each failing test's exception type from pytest's JUnit report (words inside an
  assertion's own message no longer decide), ignoring stderr around it, and says in the log when it falls back to the console. Recorded output under
  `tests/fixtures/external/` pins git, the agent tools and pytest.

- `CHANGELOG.md` merges with git's union driver (`.gitattributes`), so two units that each add an
  entry under Unreleased no longer conflict on it, and the restack that used to resolve it by hand
  keeps both. Existing entries were also consolidated: bullets that described one change in
  pieces are now one bullet, wording that contradicted later entries was corrected, and the
  spacing between bullets is regular.

- Telemetry for the shape of a run, when `ABK_OTEL_ENABLED` is set: a tick is a `tick` span, each
  unit run a `unit` span below it (a unit that runs again links to its earlier trace, kept on the
  stored unit as `trace`), each graph step a span with its round, and each agent call an `agent`
  span with runtime, model, role, turns and outcome. The metrics are the tick, unit and step
  durations, review rounds, check failures by kind, agent turns and tokens, usage pauses, reclaimed
  units and a gauge of units by state; none carries a unit id or change name, and no span or metric
  carries a prompt, diff, feedback or commit message. A tick flushes before it returns.
  `AgentResult` gains `turns` and `tokens`. The usage ledger's figures are also exported as metrics:
  `abk.agent.cost`, `abk.agent.tokens` (with a `source`), `abk.node.duration` and
  `abk.wait.duration`, with bounded attributes only and never a unit id or change name; measured and
  estimated figures are separate series. The pipeline dashboard gains panels for them. See
  docs/architecture.md.

- `abk telemetry push-dashboard` pushes the framework's Grafana dashboard (shipped as package
  data, querying only metrics the telemetry module emits) to the Grafana named by
  `ABK_GRAFANA_URL` and `ABK_GRAFANA_TOKEN`, into the folder `ABK_GRAFANA_FOLDER` (default
  `agent-build-kit`). It is idempotent: the folder is created if missing and the dashboard is
  overwritten.

- A tier-2 acceptance run for telemetry: `tests/integration/test_telemetry_stack.py` ticks a fixture
  unit with telemetry on and finds its trace by unit id and its `abk.unit.duration` and
  `abk.step.duration` series, without a unit id, in the shared stack's stores; with the endpoint
  pointing at nothing the tick still finishes and writes nothing. It needs the stack's dev
  instance up and the four `ABK_ACCEPTANCE_*` endpoint variables set (docs/agent-runtimes.md).

- A usage ledger: each agent call of a unit's graph appends a line to
  `<state_dir>/usage-ledger.jsonl` (gitignored by the template) with where it was made, the runtime,
  model, session and the figures it reported, each marked by `usage_source`. Claude Code's result
  event and an `acp` agent's response usage and `usage_update` cost are read; a call ended by a
  usage limit is recorded too. A write that fails never affects a run and is reported once.
  `AgentRequest` gains `on_result`; `AgentResult` gains `usage`, `cost_usd`, `duration_ms`,
  `session_id` and `usage_source`, and its `tokens` is now derived from `usage`, so the `acp`
  runtime reports tokens too. Time accounting: the ledger also takes `kind: span` lines with UTC
  `started`/`ended` and `duration_ms` for each node of a unit's graph (with the failure outcome when
  it raises), the wait for a build slot (`waited: slot`), a usage pause (`waited: usage_pause`,
  measured from the interrupt across processes) and each tier 1 command. Recording never affects a
  run. The usage reader ignores these lines. See docs/architecture.md.

- Gateway usage attribution: with `ABK_GATEWAY_URL` and `ABK_GATEWAY_MASTER_KEY` set, each agent
  call of a unit's graph runs on a gateway key of its own (alias `abk:<unit>:<node>:<round>:...`,
  handed over in `ABK_GATEWAY_KEY`), the totals the gateway logged for it are recorded in the
  usage ledger with `usage_source` `gateway`, and the agent's own report is kept beside them
  (`reported`, `reported_cost_usd`). The key is revoked however the call ends; any gateway
  failure falls back to the agent's figures with one warning. `AgentRequest` gains `env` (added
  to an `acp` agent's environment). Spend rows are waited for up to `ABK_GATEWAY_SETTLE_SECONDS`
  (30) and until they have stopped growing for `ABK_GATEWAY_QUIET_SECONDS` (10), since a gateway
  writes its logs in batches.

- `abk report` reads the usage ledger and the unit store and reports tokens by kind, cost and
  time by bucket grouped by unit, change, node, role, model, repo or day, filtered with
  `--since`, `--change` and `--unit`, as a table or `--json`. Estimates have their own columns
  and stay out of totals unless `--include-estimates`; a figure never recorded reads as absent;
  each row shows its sources and, where the gateway and the agent both reported, the
  difference. `planning.usage_page` (default `docs/unit_cost.md`) holds per-change totals and
  the most expensive units, rewritten on every store write without ever failing it. Archiving a
  change rolls its ledger lines into one `summary` line per unit, so its totals survive.

- `forges/transport.py`: one HTTP transport for code hosts. Credentials come per owner (the
  `GH_TOKEN` setting, else `gh auth token --user <owner>`, cached once per owner), every call
  has a timeout, failures are retried with backoff and `Retry-After` (never a create-style
  POST), and a sign-in page, a refusal or a not-found is a typed error naming the account.
  New settings `ABK_FORGE_TIMEOUT_SECONDS` (30) and `ABK_FORGE_RETRIES` (3); `httpx` is now a
  direct dependency. `abk doctor` checks each GitHub repo's credential against the host and
  reports the account it acts as.

- A rework addresses comments added while it runs. Just before the push
  (including after a clean move onto a new base) the pull request's notes and conversation are
  read again; any comment the rework was not given, other than the pipeline's own, goes back to
  the rework agent, is reviewed, and is answered in its thread, all in the same push. Comments given to
  the agent this way are not reported again by the poller after the push; they are kept in
  `given-comments.json`, apart from the pipeline's own posts. A person's rework counts as given only
  the comments its feedback was built from (the poller's listing and the notes the dispatch read), so one
  posted since goes back to the agent. This costs one read before each push attempt, being the pull
  request's review notes and its conversation; a failed read is logged and the work pushes.

- Time accounting: the usage ledger also takes `kind: span` lines with UTC `started`/`ended` and
  `duration_ms` for each node of a unit's graph (with the failure outcome when it raises), the
  wait for a build slot (`waited: slot`), a usage pause (`waited: usage_pause`, measured from the
  interrupt across processes) and each tier 1 command. Recording never affects a run. The usage
  reader ignores these lines.

- Infrastructure profiles (`infra/`), a second profile kind beside the toolchain profiles: a repo
  names one with `infra:` (`docker` or `none`, default `none`; an unknown name fails when
  `abk.yaml` loads) and `abk init` writes `docker` when the repo root has a compose file or a
  `Dockerfile`. The stack-versions command resolves as `verify.stack_versions_command` when a
  list, else the repo's infra profile's, with an explicit `null` recording nothing. **Behaviour
  change:** the key no longer defaults to the `docker ps` listing, so a repo that does not name
  `infra: docker` stops recording the stack in PR bodies; add `infra: docker` to each repo (or
  re-run `abk init`), or set `verify.stack_versions_command` to the old listing to keep it. A
  stack-versions command that cannot start (missing executable, no permission) is logged and
  records nothing instead of failing the unit.

- Tier 2 runs each workspace member from its own directory with no collection path
  (`uv run --directory <member> ... pytest -m <marker> -v`), so the member's own `testpaths`
  decides what is collected.

- A task group can say `Independent: <reason>` to be built without waiting for the groups before
  it. Its unit has no dependency, the chain closes around it, it is never joined into a
  neighbouring unit, and `[acceptance]`/`[narrow]` units depend on every earlier unit. `abk tags`
  rejects the line with no reason, on group 1, or beside a flag. A change without the line plans
  as before.

- The unit graph is the only engine. A unit waiting for review or held waits in an interrupt of its
  thread that holds no branch lock, the poller's events and `abk requeue` resume the thread as
  commands, a usage refusal interrupts the thread before an agent step, and a run killed mid-node is
  resumed at that node. An agent runtime declares `supports_session_resume`; Claude Code's does
  (`--resume`), so a node killed mid-agent continues its session. A tick starts a unit's thread and
  resumes the ones a kill or a usage pause left; an event for a thread whose node is running, or
  held by another process's branch lock, is kept for a later poll. A killed run is resumed from its
  thread by the next tick, not reclaimed: `reclaim_stale`, the classic engine's `UnitRunner.run`,
  `checkpoint()` and `record_step` are gone, and so is the `wip:` commit of a killed run's
  leftovers. A usage pause leaves the unit `running`, with its thread interrupted before the agent
  node, until a tick the usage guard allows; it is no longer set back to `planned` with a `paused
  before <step>` note. A planned unit counts as started when a run recorded a branch, a pushed or
  approved commit or a pull request, not a resume step. New runtime dependencies: `langgraph`,
  `langgraph-checkpoint`, `langgraph-checkpoint-sqlite` and `aiosqlite`, for the unit graph. There
  is no setting that chooses an engine: `ABK_ENGINE` was never released and does not exist.

- Units in flight are moved onto threads on the first tick after the upgrade: each is positioned
  at the node its stored `resume_from` step names, carrying the review rounds, deferred follow-ups,
  pending replies and the comments they answer an old store held, and a `running` unit with no
  thread starts at `prepare`. The conversion runs on every tick but only seeds a unit that has no
  thread. An old `units.json` still loads: its in-run keys are gathered into `classic_run` and
  moved to the thread, then cleared. `approved` and `predecessor_note` stay in the store, since
  the push gate and the restack write them with no run in progress. The first run of a converted
  unit skips `prepare`'s fetch and restack onto a moved base; a base moved before the upgrade is
  caught at `verify_base`.

- Removing `agent-hold` releases the unit. The poller dispatches a new `release` event, and a unit
  the label held returns to `in_review` with its thread resumed. The stored unit records why it was
  held (`held_by`, absent in older records): a hold the review loop, a depth cap or the toolchain
  made stays, and the log says so. A comment or failing check that arrived during the hold is
  delivered by the next poll. A comment left on a held unit's pull request is no longer lost: the
  poller keeps it new until the unit takes it, so releasing the unit delivers it as a rework. A
  comment on a satisfied unit or a pull request with no unit is still consumed. The "held, ignoring"
  line is logged once, not every poll.

- A held unit no longer counts against `limits.max_units_in_progress`: holding sets
  a unit aside until a person releases it, and it should not keep new work from
  starting. It counts again once requeued and started.

- A cancelled check is no longer a failing one. A host cancels a check when a runner never came or
  a newer run superseded it, which says nothing about the commit, yet it sent the unit back for
  rework. `PullRequest` gains `cancelled_checks` (GitHub `CANCELLED`; an Azure DevOps build policy
  whose build ended `canceled`), the poller dispatches a new `rerun_checks` event, and the forge's
  new `rerun_checks` operation runs them again with no agent, up to `limits.max_check_reruns`
  (default 2) per head commit, counted on the stored unit. `FAILURE` and `TIMED_OUT` still rework.

- A rework sent back for a failing check is told how to reproduce it, from the repo's own toolchain
  (`uv run pre-commit run --all-files` for a Python repo, then the tests), on every host. It used to
  depend on the host's log: GitHub had none for a run still going and Azure DevOps only ever gives a
  status and a link. The unit's run log also records each command tier 1 ran, where, and how it
  ended, so a pass that CI then contradicts can be explained. The rework is also handed the failure
  when the run is still going: the poller reports a check the moment it fails, usually while the
  run's other jobs are running, and `gh run view --log-failed` has no log for such a run, so the
  rework was handed an empty block. The failed job's own log is fetched instead, up to its
  `##[error]` line; with no log at all the rework is told that, and to run `pre-commit run
  --all-files`.

- The lock owns the Python tool versions. This repo's ruff and pyrefly hooks are `repo: local` hooks
  running `uv run --frozen`, with no `rev` and no interpreter-path argument, so the locked version
  is the one tier 1, CI and the editor run. `abk doctor` warns when a tool is pinned in both the
  dependency group and a hook `rev`, and when a `language: system` hook runs a tool the group does
  not hold. The Python recommendations seed describes the arrangement. Tier 1 also type-checks
  `tests` in a unit's worktree: the old pre-commit hook pinned pyrefly 1.2.0, which dropped the
  `tests` include in a worktree under the pipeline's state directory, so a unit's checks passed on
  test files CI then failed. The dev pin is 1.3.1.

- `poe test` and CI run the suite with `pytest-xdist` (a new dev dependency): a parallel pass in
  up to 8 workers, then a serial pass of tests carrying the new `serial` marker. A single
  `pytest <file>` still runs in one process. The python-uv profile's tier 1 does the same for a
  repo that declares `pytest-xdist` (and treats "no tests collected" in the serial pass as a pass);
  a repo without it keeps `uv run pytest -q`.

- A branch the host rewrote to different commits holding the same change, or holds at an older
  restack of the same work, is no longer refused at the push: its head is recorded as the last push,
  the approval stands, and the approved head goes out leased on it. The commits replayed over a
  host head are those made since the last push, chosen by patch with `git cherry` when a restack
  has left the branch off its last push. A host change that does not combine with
  local work still stops the unit with `StaleRemote`.

- A unit fetches its repo before it restacks and again before it pushes, asks
  the forge whether its parent merged (recording a merge the store missed) and
  moves onto the base as it now is. The move before a push never runs the
  conflict resolver: a conflict, or a tier 1 or tier 2 failure on the moved
  commit, resumes the unit at its restack in the same run, once, where
  resolution runs under the usage gate and review is told of it (a second such
  hold is left planned for the next tick). A pull request refused for a missing
  base asks the forge for the base again, so a parent that merged meanwhile
  gives its merged-to branch, and resumes from that; each forge recognises its
  own error for that.

- A pull request event is matched to its unit by repo and number, not by number
  alone. Once two repos in a workspace had reached the same number, a merge,
  comment, hold or close in one was applied to the other's unit: the merge went
  unrecorded, what was stacked on it was never moved, and a finished unit could
  be requeued for feedback that was not its own.

- A unit's approval now carries across a clean rebase when the base had edited lines near
  its change. The change's id was taken over its context lines too, so a parent that touched a
  line three lines away gave the same change a new id; the approval did not carry, and the unit
  was failed at the push ("refusing to push … review approved …") for a branch review had in
  effect read. The id covers only the changed lines. And a clean move whose approval does not
  carry is read again by review instead of refused.

- The review loop can converge instead of only approving or asking again.
  Every round is told which round it is, how many remain, and what running
  out costs. A verdict may approve while deferring an optional follow-up,
  recorded against the change for its next unit and the PR to see —
  correctness, a test that would pass regardless, a missing test a task
  asked for, and anything the command policy forbids stay non-deferrable. A
  reviewer that meets another instance of a kind it cannot enumerate, or that
  still disagrees after the builder declined a point once, escalates instead
  of spending another round, holding the unit for a person with its reasoning
  recorded. When the round budget is spent with blocking work still
  outstanding, the branch is pushed and its PR carries the open points
  instead of the work being discarded.

- The review after a rework of a person's comments is shown those comments, quoted as the
  reviewer's words and not instructions, each with the builder's reply (or "no reply"). The review
  may now read its pull request through the forge's read commands, and nothing that writes.

- `abk tick` keeps its build slots full: every finished build is followed by a fetch, a poll and a
  fresh readiness check, and the pass goes on until nothing is ready or in flight. A pass can now
  run for hours; a timer's next tick waits for it. Poll events for a unit whose build is running are
  left for a later poll instead of being acted on mid-build, and a unit whose parent merged while it
  built stops before pushing and is restacked when it resumes. A pass refreshes from the code host
  every five minutes while builds run, not only when one finishes, and starts again a unit it
  already built that a poll sent back (a conflict, a failing check, a review comment), at most twice
  per pass. A pass with one long build used to hear nothing until it ended, and the timer cannot
  start another tick while one is running.

- The usage threshold ramps instead of being flat: each window (five-hour session, seven-day week)
  may be run from `usage_pause_pct` up to `usage_pause_ceiling_pct` over the last
  `usage_relief_fraction` of *that* window, measured against its own reset. Quota unused at a reset
  is lost, and the ceiling stays below the point where credits pay. A pause now resumes when the
  ramp would offer `usage_resume_buffer_pct` of room above current usage, capped at six hours
  so a weekly window resetting days out re-reads rather than sleeping through it. The keys are set
  per window under `runtimes.claude_code.limits` (`session` and `weekly`). `abk status` prints each
  window as `used%/threshold%` with its time to reset. A usage pause lasts until the guard's own
  answer — the moment the ramp towards a window's reset offers room — instead of until the reset,
  and it ends on the first tick the guard allows: a paused tick asks again rather than sleeping to
  its deadline, so a threshold raised by hand takes effect at once. A pause no longer schedules a
  transient systemd resume; the tick timer is the resume. A rate-limit refusal from the model is
  still kept to its deadline.

- New `limits.max_units_in_progress` (default 5, at least 1) caps the units
  started and not finished across all repos, whether or not they have a pull
  request: running, in review, held, failed, or planned with a pull request or
  a step to resume from. At the limit no unit that has never started does: it
  stays `planned`, and the tick log and `abk status` say "queue is full: N
  units in progress, limit M" with the count in each state. Reworks, resumes,
  restacks, further review rounds and PR opening continue, so the count can go
  past the limit. Free slots go to units with an open PR first, then resuming
  builds, then new units. **Behaviour change:** installations that were
  unbounded now stop starting new units at 5 in progress; a workspace wanting
  the old behaviour sets the key high.

- `limits.stack_depth_cap` is renamed `limits.stack_depth_build_cap`. An `abk.yaml` still using the
  old name fails to load with the schema's unknown-key error, so existing installations must rename
  it. New `limits.stack_depth_rebase_cap` (default: the build cap) bounds how deep a merge restacks
  a dependent: one left beyond it is held with a note naming the depth and cap, its PR is retargeted
  and its parent's branch kept, and a later merge in the same repo restacks it once its depth is
  within the cap.

- A unit whose groups already landed in its predecessor and whose tier 1 passes
  on the whole repo ends `satisfied` instead of failing: its PR is closed with
  the reason, its groups are ticked and its dependents look through it. A
  change archives once its satisfied units' work has merged. **Breaking for
  third-party integrations:** `Forge` gains `close_pr` and `permitted_commands`,
  and toolchain profiles gain `lint_command_all_files()` and
  `test_commands_all(repo, root_extras)`.

- Each unit run writes a file of its own under `<state_dir>/unit-logs/`, named
  for the unit, its start (UTC) and the step; the unit's record names the
  latest (`run_log`). The last three runs of a unit are kept and archiving a
  change removes them. Gitignored; an existing installation adds
  `runs/unit-logs/` to its `.gitignore`.

- What an agent may run to read its PR comes from its repo's forge (`read_commands`), so an Azure
  DevOps agent can read its PR with `az repos pr show` and is no longer offered `gh`. The tracks'
  default allow-list carries every forge's read commands in place of `Bash(gh pr *)`. An Azure
  DevOps poll reads each open PR's conversation and checks on a pool of four. The `github:` section
  of `abk.yaml` is now `git:`; the old name is refused at load like any unknown key. `RUN_URL`,
  `LOG_PREFIX` and `CHECK_LOG_CHARS` are gone from `pipeline/events.py`.

- `abk init --update-rules` brings `openspec/config.yaml` up to the framework's rules
  version without rewriting it: each newer version's paragraph goes at the end of the
  `context:`, the `# abk-rules:` stamp is raised, and nothing else changes. `abk doctor`
  names it when the stamp is behind.

- **Breaking:** three more compatibility shims are removed.
  - The `github:` section of `abk.yaml` is no longer read as `git:`, and
    `abk doctor` no longer asks for the rename; a file that still has it is
    refused at load like any unknown key.
  - `limits.stack_depth_cap` is refused with the schema's usual unknown-key
    error instead of one naming `stack_depth_build_cap`.
  - A units store or PR poll snapshot written by an older version is no longer
    translated on read: the `open` unit state (now `in_review`) and the poll
    snapshot's earlier shape (`merged: true`, `CHANGES_REQUESTED`). Both are
    state files that older code wrote; let the old version finish its work
    first if one might still hold either.

- **Breaking:** the `limits.usage_pause_pct`, `usage_ceiling_pct`,
  `usage_relief_fraction` and `usage_resume_buffer_pct` keys are no longer read
  as the Claude runtime's thresholds, and `abk doctor` no longer warns about
  them. Set them per window under `runtimes.claude_code.limits` (`session` and
  `weekly`, with `usage_pause_ceiling_pct` for the ceiling); a file that still
  has them is refused at load.

- A workspace names its agent runtime in `abk.yaml` (`runtime:`, default `claude_code`), with an
  optional `runtimes.<name>` entry for its command, its policy fix and its own model names;
  `ABK_RUNTIME` overrides it on one machine. An unknown runtime or a missing required fact fails at
  load. `abk doctor` reports the runtime, its policy coverage, and any forbidden command class it
  does not refuse; `abk init` offers to run the installation's fix, only once asked. Its answer is
  kept for a few minutes in `runs/policy-check.json`: an existing installation adds that path to its
  `.gitignore` (new ones get it from `abk init`). `tracks.model` still defaults to Claude Code's
  `sonnet` and is not resolved per runtime: a workspace selecting another runtime sets it.

- Contributor conventions moved to `AGENTS.md`, with `CLAUDE.md` loading it, and now say that
  code changes go through the spec process, not ad hoc sessions (docs and supporting files may still
  be edited in a session).

- Runs on the Claude Code runtime no longer add its `Co-Authored-By` trailer to commits or its
  "Generated with" line to pull requests. Every run passes `attribution` empty in its
  `--settings` (and `includeCoAuthoredBy: false` for an older CLI). A repo that forbids the
  trailer used to hold the unit for a person to rewrite the commits, since an agent cannot.

- The Python recommendations seed prefers `enum.StrEnum` over repeated string literals for
  closed sets of strings on Python 3.11 and later, so `abk init`'s research proposes it.

## 0.1.0 — 2026-09-28

First release.

- `abk` CLI: `tick`, `status`, `graph`, `verify`, `tags`, `check`, `archive`,
  `openspec`, `gate`, `init`, `install-skills`, `doctor`, `config`,
  `scrub-check`, `track`.

- Every installation fact — repos, owners, deploy rules, relationships,
  limits, models — comes from the planning repo's `abk.yaml`; nothing is
  derived from where the framework's source sits.

- Toolchain profiles: `python-uv` implemented; `node-npm` declared.

- Deploy conventions: test and documentation paths deploy nothing; a change
  in a workspace library redeploys the members that declare it as a
  dependency.

- The OpenSpec CLI runs through `npx`, pinned by `settings.openspec_version`.

- The policy hook is registered as `<interpreter> -m agent_build_kit.hooks.policy --specs <dir>`.

- One tier-2 lock, in the state directory, shared by tier 2 and the
  post-merge verify (they used to lock different files).
