# Changelog

## Unreleased

- The poll now records when it last read a definite answer on whether a pull request
  merges, and since when it has conflicted. A conflict still standing after a unit's own
  push is offered to the pipeline on every poll, not only when it begins; nothing acts on
  it yet.

- A clean move of a unit's branch onto a moved base, before a push or when a merge releases
  a dependent, now tells tier 1 which base it left. Tier 1 classifies the move as scoped (no
  file the move brought in is one the unit changes) or full (one is, the unit produced
  nothing, or there is no old base) and logs a `moved base:` line saying which and why. The
  new `limits.restack_check` (`affected`, the default, or `full`) selects between them; the
  run itself is still the whole suite for now.

- The conflict resolver's cost is now in the usage ledger under the node `restack`, one row
  per resolver call with the unit being moved and its change and repository, so what a
  conflict costs shows in the report. The ledger's reader keeps each such row as its own
  call, and a row with no unit never counts as a unit in the usage estimate or its
  calibration. A guard test now fails on a new agent call
  that records nothing; the planner, track runs, init, the policy probe, the login refresh and
  chat are still to be recorded.

- A restack no longer keeps the whole repository waiting while an agent resolves a conflict:
  the repository's turn is held only for the git commands that write shared state, so other
  units' worktree adds and pushes go on meanwhile. A unit's own restack in a run takes the turn
  the same way. A branch that moved during the resolution is moved again once, then the unit
  is left planned with the heads named. A branch with no worktree is now moved in a temporary
  worktree, so the repository's own checkout is never switched; a branch checked out elsewhere
  is left alone and the unit waits. A conflict is now settled in one agent session, smallest
  change first: the conflicting hunks only, then, when a check fails (a marker left, one of the
  unit's own tokens or tests gone), the unit's other files that depend on the conflict, the
  failed check named in the second call. In a run the calls continue the unit's build session
  (or start it on the rework model) and each is a `restack` row in the usage ledger; files
  changed beyond the conflict are named to review. A rejected replayed resolution now fails
  that check instead of aborting the move. A conflict those two steps cannot settle is
  ported in the same session, told which steps were tried and what their checks said; the
  test accounting applies to the port only.

- A unit that has never started and has two or more open same-repo parents, neither built on
  the other, now waits for all but one of them instead of starting on one branch and missing the
  other's work. It builds on the deepest parent (the newest of a chain, whatever order its
  dependencies are listed in), the status says `waiting for <parent> to merge (second open
  parent)` and the graph draws it blocked. Started units are untouched. `abk tags` and `abk
  check` warn about the task-group shapes that produce such a unit.

- The usage allowance of each window, the points a unit is assumed to spend when a start is
  allowed on an estimate, is now calibrated from the readings and ledger the installation has
  recorded, instead of a flat 10 (session) and 2 (week). Each tick takes a high quantile of
  points gained per unit over recent pairs of readings, never below a floor or above twice the
  default, and only with enough pairs; `abk status` prints which allowances are in force and the
  pairs behind them. `usage_unit_allowance_pct` now takes `auto` (the default) or a whole
  number, which is the fallback and the cap; `calibrate_usage_allowances: false` restores the
  fixed allowances. New settings: `usage_allowance_quantile`, `usage_allowance_window`,
  `usage_allowance_min_pairs` and, per window, `usage_allowance_floor_pct`. `abk usage replay`
  re-runs the estimate over the recorded readings and prints each gap's estimate against the
  actual reading, with counts of underestimates, misses beyond the margin, false pauses and
  false allows; it writes and asks nothing.

- A failed unit that waits on another unit (a prerequisite not yet reviewed or merged, or a
  predecessor being reworked, failed or held) no longer holds a place under
  `limits.max_units_in_progress`, so units like it cannot fill the queue and keep the work they
  wait on from starting. It stays failed and is never requeued by the pipeline; it counts again
  when the wait ends. The full-queue report says how many are not counted, the status says what
  each waits on, and the graph labels it `failed, waiting on <units>`.

- A project registered in `abk.yaml` before its directory exists is now pending, not an
  error: tier 1 and tier 2 run nothing in it and name it in their output, `abk doctor`
  lists it as information, and it is checked in full once a unit creates the directory.
  An `environment` whose inputs are all missing is likewise pending, running no `sync` or
  `check` until an input appears.

- Tier 1 now judges each project by its own toolchain: a project's own checks, such as the
  type check, run in its directory, a failure is classified by that project's profile, and a
  build run may use the tools of every project's profile. Checks about the whole checkout,
  such as the changelog, still run once at its root. The node-npm profile lints and checks the
  format of the changed files and type-checks the project as its own check.

- The kit now carries a recommended command policy for build agents: deny globs for each
  forbidden class (merging a pull request by the CLI, the raw API or GraphQL, amending a
  commit, pushing or force pushing to the default branch), checked against the spellings the
  policy check attempts. Its glob dialect is documented, and the classes it leaves uncovered
  (skipping the commit gate, hard reset, discarding untracked work, force-deleting a branch,
  a recursive delete, a bare force push) are listed with the reason. `abk policy patterns`
  prints the globs (one per line, as JSON or as a YAML list, for all classes or those named,
  with `--extra` adding `runtimes.<name>.policy_extra`, which needs an installation; nothing
  else does), and `abk policy show` prints the recommendation, its gaps, false positives and
  dialect. The kit can also merge that list into a known agent's own configuration (add
  only, by inserting lines into the original text so every other byte of the file stays as it
  was; the original is backed up once beside it, the write is atomic, and a file it cannot
  change that way, such as an inline or single-string list, is refused with the reason and left
  alone; the agent's recommended toolset is replaced only when asked); only the first known
  agent has the recipe so far. `abk policy apply [--runtime NAME] [--agent NAME] [--dry-run]
  [--yes] [--toolset]` runs it: it shows the diff, asks, writes, and names `abk doctor` as the
  live check (which spends model tokens) without running it; it exits 0 when written or
  nothing to change, 1 when declined, 2 on a usage problem, an absent or unreadable
  configuration or an agent it cannot write to. `abk policy show` now also compares that
  agent's configuration with the recommendation, and `abk doctor`'s fix text names
  `abk policy apply` (or `abk policy patterns`) when the installation has no fix of its own.
  `abk init`'s policy step offers the same policy as its fix for such an agent when no
  `policy_fix` is set: it shows the file and the diff, asks, applies, checks again and says
  what is now refused (under `--yes` only with `--run-policy-fix`); the toolset is left
  alone, and an agent it cannot write to is offered `abk policy patterns`.

- A requeued unit now builds on the base the store names, not one its thread remembers, so a
  failed unit whose predecessor has since merged is no longer failed again counting commits
  against a deleted branch. A remembered base that no longer resolves is replaced by the
  store's, and the run log says so.

- A fresh usage reading in Claude Code's own cache (`~/.claude.json`) now decides a start
  before the usage endpoint is asked, so interactive use of the account is seen without a
  call that may be refused. It is used when fetched within the new
  `usage_claude_cache_minutes` (default `usage_cache_minutes`, 0 turns it off), no window has
  reset and it is fresher than the guard's own reading. The reason says
  `(claude.json, 6m old)`, the call record counts it as `claude-json`, and the status
  call-rate line gains a `% from claude.json` share.

- A dependency that would close a cycle with units already stored is no longer applied,
  so two changes can no longer leave planned units waiting on each other forever. An
  edge the planner proposes is dropped and logged with the cycle it would have made; a
  `Needs:` line that would close one is refused and logged, and `abk replan` exits
  non-zero naming it. A replan also clears such a stale planner edge from a unit that
  has not started, and never touches the dependencies of one that has. A cycle in the
  `Needs:` lines of two changes is reported by `abk tags` and `abk check` before any
  planning, a deadlock already stored is listed once per cycle as `deadlocked:` in
  `abk status` and named when a pass starts nothing, and the planner is told not to
  make unstarted work depend on the change it is planning.

- The tier 2 result now records how long each phase of each test took (a second or
  more), so a slow test can be told from a hung one. The command asks for the
  durations, the kept output leaves pytest's durations section out so it cannot push
  the failures from it, and the posted result opens with the three slowest entries and
  lists the slowest `limits.tier2_durations_shown` (15 by default, 0 for all) above the
  output, so a small description never cuts the listing. Each entry also becomes a
  `test_time` ledger row and feeds the `abk.tier2.test.duration` and
  `abk.tier2.test.time` histograms, whose attributes are never a unit, change or test
  name. A test that drives the scratch installation now prints, per phase, its time
  split into agent time by role, checks and the rest (the `tests/time_split.py`
  plugin), and the result shows the split beside the entry.

- `abk init` now asks which agent runtime to use, before research and propose run on
  it. It looks at what this machine can run without calling a model, lists the usable
  candidates first and each unusable one with its reason, and always offers your own
  configuration; the runtime's own setup questions follow, and the choice is recorded
  in `abk.yaml` (a second usable runtime may be added as a fallback). `--yes` takes
  the only usable runtime and otherwise exits 2 without writing anything; `--runtime`
  and `--agent-command` name the choice, and a kept file's runtime is overridden only
  after you confirm, or with `--force` (`--yes` alone leaves it). Research and propose
  run with the command and models recorded there. A new start command replaces the one
  already recorded for that runtime, and `--agent-command` on a kept file that is not
  changed says so. It also asks whether what an agent needs (a running gateway, say)
  is in place, and which models to use, from what the agent advertises when a session
  opens, Claude Code's documented aliases, or a name you type; no model is ever
  called to choose. It shows what it will record and writes only after you confirm.
  Any answer can be given without a prompt with repeatable `--set key=value` or
  `--runtime-config FILE`, an unknown key is refused by name, and `--dry-run` prints
  the choice it would record. Its policy step is guided: before a fix runs it prints
  the fix and each unrefused class and spelling, runs it with its output visible, then
  checks again and prints what is refused now (a fix that changes nothing says so). A
  check that prompts the agent says it spends tokens and asks first; an agent with no
  known fix offers to rely on abk's own layer, take a fix command, or continue without
  (recorded as `policy: unchecked`). `abk init --policy-only` runs just that step on an
  existing installation and exits 0, 1 or 2; `--policy-fix ARGV` records the fix and
  `--run-policy-fix` lets `--yes` run a configured one. `abk doctor` lists other usable
  runtimes, warns about an entry that is documented only, and for an unchecked one warns
  without spending a prompt.

- An agent run that ends because the internet or the model service is down no longer
  fails its unit. The unit is parked as `planned`, shown in `abk status` and the graph as
  waiting for the network or for the model service, and resumes at the same step after a
  backoff of 1, 2, 5, 10 then 30 minutes. A name that cannot be resolved parks it
  straight away; a refused or timed-out connection is checked with a probe of the model's
  host and a control group. `limits.network_probe_timeout_seconds` and
  `limits.network_control_hosts` set the probe, and `abk config --show` lists them. A
  model service answering 5xx or 529 parks the unit the same way, without the probe, up to
  `limits.service_unavailable_attempts` times in a row (default 5); the next such failure
  fails it with its error text. A parking for the network also writes a `network` pause:
  while it stands a tick starts no agent run and the status shows it as waiting for the
  network, and the first tick whose control hosts connect ends it. Planning is the same:
  a planner call that meets an outage no longer spends one of a change's three attempts.
  The change waits (the same backoff, ended early when the network pause clears), `abk
  replan` and `abk status` show it as waiting for the network or the model service, and a
  plan that is given up names `abk replan --failed`. Every failed plan now keeps the first
  line of its reason, at most 300 characters and redacted.

- A `Needs: <change> group <n>` line is now only a dependency: the dependent starts on
  the parent's branch once the parent is in review, instead of waiting for it to merge
  (a parent in another repository still has to merge). The word `merged` after a
  `Needs:` line is deprecated and changes nothing; `abk tags` and `abk check` warn
  about each such line, and a gate stored by an earlier version is cleared on the next
  tick. A `Needs:` line added to a unit that has started works the same way: requeueing
  a failed or held unit whose parent is not yet in review leaves it waiting, and it
  resumes restacked onto the parent's branch; the line written for a flaky test no
  longer says `merged`. A running unit now notices a `Needs:` line added since it
  started and stops at its next check. The merge gate is removed: a store that still
  carries one loads and drops it, the unit page no longer lists merge gates, and the
  unit graph draws a `Needs:` dependency as a thick edge labelled `needs` (the
  planner's own edges stay plain).

- A runtime entry in `abk.yaml` may now carry `policy: unchecked`, recording that the
  agent's policy check was knowingly skipped. The only value is `unchecked`, and a file
  without the key loads as before.

- A failed tier 2 run now sorts its failed tests into the unit's own (in a file the
  branch changed, or beside a changed `conftest.py`) and untouched ones, and runs the
  untouched ones once, together, on the base in a clean temporary worktree inside the
  same stack hold. A test the base run also fails is pre-existing; one it passes, lacks
  or does not name is the unit's to fix. `limits.tier2_base_runs` (0 or 1, default 1)
  turns the base run off. A recorded pre-existing failure is listed by `abk status`
  with its count and fix change, gets one `fix-failing-…` change per test id written
  without a model, previewed as `exists:` or `would write:` (`abk tick --dry-run` prints
  the same lines and writes nothing), and the change that fixes a flaky test is now
  written at priority 1 too. A unit whose every tier 2 failure is pre-existing no longer
  fails: it waits, gated, on the fix changes and runs tier 2 again once they merge (the
  fix change's own unit does not wait). A unit with a failure of its own still fails, and
  the feedback it is given holds only its own failures, with the pre-existing tests named
  once as recorded.

- The full output of each tier 2 run is now kept in a redacted file under the state
  directory's `tier2-output/`, named for the unit and the time. The tier 2 result, the
  unit's run log and `abk status` for a unit that failed tier 2 name the file, so the
  first error is never lost to the cut of the posted output. The last three files of a
  unit are kept, and archiving a change removes its files.

- A refused or unreadable usage read no longer pauses the pipeline while the last good
  reading leaves ample room. Each window is estimated as that reading plus a flat
  allowance for every unit that has spent or started since (`usage_unit_allowance_pct`
  per window, 10 for the session and 2 for the week), a window that has reset is
  estimated from its reset, and a start is allowed while both estimates plus
  `usage_headroom_margin_pct` (5) stay under their thresholds. At most
  `usage_estimate_max_starts` (3) units start on one reading. The reason and
  `abk status` show the estimate, so raising `usage_fallback_minutes` is no longer
  needed to keep work moving. A refusal that asks for no wait (a retry time of zero)
  no longer widens the time a reading is kept, and `usage_cache_max_minutes` now
  defaults to 30 minutes instead of 60.

- A failed tier 2 run now lists every failed or errored test with its first failure
  line above the output that may be cut, so the pull request description and the
  feedback handed back to the builder show each failure even when the tail of the
  output holds only the last one. The python profile asks pytest for a short summary
  to read them from; other toolchains list none.

- A unit no longer fails for waiting its turn at the tier 2 lock: it waits as long as the
  holder runs. The wait is logged when it begins and every five minutes, naming the unit
  that holds the lock and for how long, and is recorded as a `tier2_lock` span. The lock
  file now names its holder (unit, process, start) and is empty when free; a record left by
  a process that is gone is reported as stale and overwritten, and a held lock is never
  broken. `limits.tier2_lock_wait_seconds` (default 5400, a bad value refused at load)
  now bounds only post-merge verification, whose busy message names it. `abk status` shows
  `tier 2: held by <unit> for <age>` while the lock is held, a record left by a process that
  is gone as stale, and a held lock whose recorded process is gone as held, and says nothing
  when the lock is free; it only probes the lock, never leaves it held, and never changes the file.

- A unit whose agent run was killed mid-edit now resumes over the edits it left, as
  intended, instead of failing with a `TypeError` on the worktree request. The wrapper
  that holds the repository's turn dropped the option that allows a dirty worktree.

- The planner is now told which groups a started unit already builds: the change text
  marks each such heading `(built by <unit id>)` and the prompt says never to claim them.
  When a plan is refused, the plan record keeps the unit ids the planner returned and the
  reason, and a bare `abk replan` shows the reason beside the plan state.

- The command rules now judge a command as its tool would run it: git's global options
  (`-C`, `-c`, `--no-pager`, `--git-dir`, `--work-tree`, in both the `=` and two-word forms)
  and the host CLI's repository option no longer hide an amend, a push to the default branch,
  a force push, a hard reset, a branch force-delete or a pull request merge, and a merge sent
  through the host's raw API is refused while reads through it are not. A privilege wrapper's
  option value (`sudo -u root`) no longer hides the command either. The policy check now
  also attempts the global-option spellings of the amend, the push to the default branch and
  the force push, the repository-option spellings of the merge and two raw-API merge
  spellings, all in its one prompt, and reports, per class and spelling, which one an agent
  ran without asking. `abk doctor` and `abk init` print an unrefused spelling by class and
  spelling, with the class's other spellings as refused.

- Known secret values (`verify.env`, the credential settings, variables named in the
  new `redact` list, and each gateway key minted) are gathered when an installation
  is activated, and a redaction function replaces them with `[redacted:<NAME>]` in any text it is
  given, along with token-shaped strings. Values shorter than 8 characters are not replaced.
  Saved feedback, run logs, transcripts, the usage ledger's outcome, printed output and tier-1
  and tier-2 results are redacted before they are written; when redaction fails the text is
  replaced by `[redaction failed: text withheld]` and the failure is logged once. Text sent to a code host
  (pull request titles and descriptions, comments, replies, statuses) and the prompt a rework
  agent is given are redacted the same way. `abk doctor` warns, by name, about a `verify.env` or
  `redact` variable whose value is under 8 characters and a `redact` name that is not set.
  History already saved is not rewritten by the pipeline: the temporary `abk redact-history`
  reports (dry run) or, with `--apply`, replaces known values in the unit store, run logs,
  transcripts and ledger, keeping a `.pre-redact` copy of each changed file (ignored by the
  planning repo's `.gitignore` template; it holds the original values). `--apply` refuses
  unless the pipeline is paused. It is removed once installations have run it. A secret already sent to a provider cannot be recalled;
  whether to rotate it is the operator's decision.

- Editing the text of a change's groups once every group belongs to a started unit no longer asks
  the planner: the edit is recorded and a requeued unit reads it from `tasks.md`. A changed repo,
  tier or flag under a started unit is reported with the way out and not recorded as planned, and
  `abk replan` prints which of the two happened.

- A test marked `local_stack` may start a real agent: the suite's guards on the runtime's spawn
  and on a direct `claude` start no longer refuse it. Every other test is refused as before, and
  the guards on the login refresh, the usage window, `gh` and the code host apply to all.

- `start_server` takes an `agent_environment`: the whole environment the agents a chat starts
  (turns, new and continued sessions, the resume check) run in, so a test's own variables do not
  reach them. `abk serve` passes none and is unchanged.

- The decision log is kept to `retention.decision_log_mb` megabytes (default 50), dropping its
  oldest lines, and a unit's run log older than `retention.unit_log_days` days (default 30) is
  removed once the unit's summary is in the usage ledger; a unit with no summary keeps its log.

- `abk requeue --rework` and `--restart` take `--note TEXT` or `--note-file PATH`: a
  person's instruction that the agent's next run sees first, ahead of any saved failure,
  and that the review of the work that follows is told. With a note, `--rework` no longer
  needs a saved failure. A note with a plain requeue is refused, since a resume would
  not read it. An agent session that is continued is also told which of the change's spec
  files were edited since it last ran, with the diff (cut at 6000 characters).

- After tier 1 passes, the tests a unit added or changed are run again three times under the
  same parallel load, and a failure in any run fails tier 1 with its output, so a flaky new
  test is caught before review. `limits.tier1_repeat_runs` sets the count (0 turns it off); a
  toolchain profile supports it with an optional `repeat_command` hook, which the Python
  profile provides. The test-writing prompt and the reviewer's checklist now carry rules for
  deterministic tests, and a reviewer treats a violation a change introduces as required.

- A file a toolchain profile's own commands create in a unit's worktree, such as a lock file
  the repository does not commit, no longer holds the next step of the unit as a leftover and
  is never committed, even in a repository with no `environment` section. A profile names
  these files with an optional `created_files(repo)` hook; the Python profile names its lock
  file. A tracked file follows the lock rule only where the environment declares dependency
  inputs, and is ordinary work otherwise.

- The acceptance tests that start a real agent can now give it a scratch home of its own, set
  by three `verify.env` entries (`ABK_ACCEPTANCE_AGENT_HOME_VAR`, `ABK_ACCEPTANCE_AGENT_HOME`,
  `ABK_ACCEPTANCE_AGENT_HOME_FILES`), so an agent that refuses its real session store under a
  test process still keeps the sessions a later step resumes. An acceptance test that
  resumes a session now checks after its first agent step that the agent lists it, and fails
  there naming the three variables to check. Unset, nothing changes.

- Every unit that is not running now has one recorded reason (blocked, queue full, slot, usage
  pause, lease, backoff, waiting for review, needs a person, or ready). A decision log in the
  state directory records a change of reason once, and a wait for a full queue, a lease, a backoff
  or a person that ends is one span in the usage ledger, beside the slot and usage-pause spans
  that already were. A unit's record gains `ready_at` and `first_human_activity_at`, written only
  once set, a unit a usage pause has parked shows as `paused`, and each refresh of a running pass
  adds a `sample` row to the ledger and sets the `abk.slots.free` and `abk.slots.idle_with_ready`
  gauges. A units store with the two new fields set needs this release to be read. An installation
  adds `runs/decisions.jsonl` to its planning repo's `.gitignore` (beside
  `runs/usage-ledger.jsonl`; new ones get it from `abk init`). A rework or adapt round's ledger
  span says why it ran (`review`, `check` or `conflict`), and a running unit that a pause in force
  has parked (no run holds it) reads as `paused` in status, the graph, labels and the web UI.
  `abk report --waits` shows each unit's wall time by cause, the hours nothing ran (with a full
  queue or with room) and the estimate ratio per kind, by unit or by day; and a change's summary
  at archive carries its slot, pause and review waits, review split into a person's and the
  checks', with the rounds' time beside them.

- The reviewer now searches for an existing equivalent of each new function, constant,
  pattern or test helper in a diff, and for a second copy within it, naming the existing one
  by file and line. A duplicate the change introduces or makes worse is a required finding;
  duplication the change leaves alone is not reported.

- A new `notifications` section of `abk.yaml` tells a person when a unit waits on them. After
  each round the pipeline works out the cards the units call for (a unit in review with no
  rework pending, a failed unit, a unit held for a person), shows the new ones and clears the
  ones whose reason has ended, so a card goes when its unit is requeued, merged or sent back.
  A card is held back for `delay_minutes` (default 10), sounded again after
  `remind_after_minutes` (default 30), and kept in `notifications.json` so a restart repeats
  none. The `command` provider runs a configured argv template with `{id}`, `{title}`,
  `{body}` and `{link}`, never through a shell. Off by default, and a provider that fails is
  logged and never fails a tick. A `windows` provider raises toasts through the BurntToast
  module (pinned to the release its scripts are written for) from WSL or Windows; `abk init`
  offers it on those hosts when it writes a new `abk.yaml`, showing the install command before
  running it only on a yes, and `abk doctor` checks the chosen provider's prerequisites.

- A pull request whose unit has merged, been closed, satisfied or unplanned now has its
  state label taken off, so a merged pull request no longer keeps saying `in-review`.
  Change labels and labels a person added stay. The code forges gain a `labels_on` read
  to see what a pull request carries. Pull requests of units that finished earlier are
  cleaned the same way, a few each tick (`limits.label_sweep_per_tick`, default 20), with no
  command to run, on ticks that have work.

- A unit in review that follows a changing predecessor back to `planned` now does so
  through an event to its thread, so the thread records the move and stays waiting for
  review instead of believing the unit is still in review; the release is unchanged. The web UI and API unit summary keep the stored
  state in `state` and carry the display name (`reworking`, `rebasing`, `blocked`) in a new
  `status`, and the `abk.units` gauge counts by stored state.

- A plan's unit estimates are now corrected by what units of the same kind (repo, tier and
  group flag) actually landed at: the median of the last merged units' actual over estimated
  lines, pulled toward 1 when there are few samples and never below 1. A unit over the
  ceiling after that correction is rejected at planning, with the ratio and the sample count
  in the message, so it is split before it is built, and a group joined onto a unit is held
  to the same figure. The planner is told the ratios, a unit keeps both its own estimate and
  the calibrated figure (listed by `abk status`), and `limits.calibrate_estimates: false`
  turns it off; the other `limits.calibration_*` keys tune it. The planner is also told,
  per calibrated kind, the largest raw estimate a unit may carry and its few most recent
  merged units (`calibration_examples`, `calibration_kinds_listed`), and a rejection for
  size names that figure and how many groups the unit carries, and says to split it by group.

- A repo can now set `checks.affected` so the check after a failed check and a fix runs
  only the tests the change affects, instead of the whole suite again. `profile` asks
  the toolchain profile, through a new optional `affected_test_commands`; `command` runs
  a template whose `{changed_files}` and `{failed_ids}` become separate arguments. A
  failing selected run goes straight back to the fixer, and a passing one is confirmed
  by one full run, which alone makes a unit green; the first check, a rework's check
  and every gate stay full, as does a selection that cannot be made or run. The default
  is `off`, which changes nothing. The Python profile selects by coverage when an earlier
  full run in the unit's worktree left its data (full runs record it, without
  selecting), and otherwise runs the failed tests alone; with none named, the full suite
  runs. Each selected run writes an `affected` line to the usage ledger with the tests
  selected and in all, the estimated seconds saved and whether the full run agreed. The
  recorded data lives under the project's git-excluded `.abk/` folder, so a commit never
  holds it, and when the coverage plugin cannot be installed the tests run without it.

- An environment's `inputs` are now path patterns, `**` included, so a repository with
  many nested manifests and locks can list them and a new module is no longer missed. A
  pattern matching nothing is reported by `abk doctor`, and an absolute pattern, or one
  with a wildcard and a `..`, is refused at load. An input that is a plain path leaving
  the repository, such as a sibling checkout's manifest, still loads for this release with
  a warning and is hashed as before; the next release refuses it, so move such an input
  into the repository or drop it before then. A new `environment.artifacts` list names
  what `sync` and `check` produce, such as a dependency folder: it never holds a unit, is
  never committed or discarded and is left out of the hash, even when the repository does
  not ignore it. A tracked file under an artifact pattern is ordinary work, and `abk
  doctor` warns about the pattern.

- The framework's own tier-2 tests can record the calls their code makes outside the stack
  (a model provider, a package index) and replay them on a rerun: a reverse proxy in front of
  each configured upstream stores a passing test's calls as cassettes keyed by the request,
  answers an identical request from them and sends any difference live. `ABK_REPLAY_MODE` is
  `off` (the default), `record`, `replay` or `live`. A `repos.<name>.tests.replay` section is
  accepted and documented, but the pytest plugin does not read it yet: a test gives its
  upstreams by overriding the plugin's `replay_config` fixture. `abk status`, `abk doctor` and
  `abk replay review` find a repository's cassettes through its `tests.replay.directory`.
  Credentials are in no key or file, a response holding a configured secret is not stored,
  and nothing is stored from a failing test. A run reports what replayed and what went live, with where each live request differs from the nearest earlier recording; a
  test that replayed is labelled with its counts. A recording no run asked for, or one a live
  call superseded, is held for review rather than deleted: `abk replay review` lists them and
  keeps or deletes each, `abk status` and `abk doctor` count them, and a run warns when one
  has waited through more than `review_after_runs` runs. The summary ends with a run total,
  and the same report is written as `report.json` in the cassette directory, which ignores
  it. A held recording a later run uses again is cleared, and one kept by hand is held again
  when a later passing run does not ask for it, even if another recording answered its call.
  Replay runs must not use xdist workers: a worker's session neither counts runs nor writes
  the report. `abk replay review --keep` or `--delete` exits 1 when no repository has the
  section.

- `abk init` now drafts a repository's `environment` section through its toolchain
  profile, so a profile can describe its own ecosystem and init needs no change for a
  new one. A Python repository gets the section it always did, except that one whose
  manifest has path sources no longer gets inputs for those checkouts' own manifests
  and locks (a pattern cannot leave the repository): its `check` runs `uv lock --check`
  and `uv sync --check` before the import check, with a comment saying why, and the
  warning for an input outside the repository now says to use `check` to detect drift.
  A node repository with
  a `package.json` now gets a proposal: the manager from the manifest's
  `packageManager` field or its lock file, the manifest, lock and workspaces as inputs,
  and the dependency folder as an artifact.

- The repository now states that framework code is language- and tool-independent, and a
  test fails when source outside the toolchain profiles and `abk init` names a package
  manager or lock file. The `limits.generated_files` example no longer suggests listing
  lock files there.

- The fake GitHub hosts the tests use now answer the pull, review, comment, status and
  label routes from one table over one state, so the in-process host and the HTTP server
  give the same answer and a review written through the server is what the other reads.
  The draft mutations, stacks, branch protection and the check and job routes are in the
  table too, and a test fails if a route is answered anywhere else. A route a test
  scripts still overrides the table for that test only. This is test support: nothing
  changes in what `abk` does.

- A pause the model's refusal records while a tick is deciding whether to go on is no
  longer cleared by that tick, so no further build starts until the pause's deadline.
  Pauses are also changed one at a time and written in one step, so a tick reading one can
  never see half a file.

- An agent step in a repo with no `origin` no longer fails with "the agent pushed" when
  the agent commits to the unit's branch. With no remote there is nothing to push to, so
  the check is skipped; with an `origin` it is unchanged.

- Each agent call now records how full the model's context window was, in tokens: where the
  step started, where it ended, the peak, how much it added, the compactions and the window.
  `abk report --context` shows it per step kind and per session, with the steps that add the
  most; a step ending above `context.warn_share` of the window (0.8) logs a warning, and
  `context.compaction_drop_share` (0.3) sets what counts as a compaction where the runtime
  has no marker. The window comes from the agent or, for Claude Code, from
  `runtimes.claude_code.context_windows`.
  Telemetry gains the gauges `abk.agent.context_used` and `abk.agent.context_max` and the
  counter `abk.agent.compactions`. Rows written before this have no context and it cannot be
  rebuilt from retained transcripts.

- A unit that waits on another unit no longer holds a place in the limit on units in
  progress, however much work it has. The unit it waits on starts into that place ahead of
  the usual order, so a full queue of waiting units cannot keep their prerequisite from
  starting. When a waiting unit is no longer blocked, it starts only while there is room.
  The queue line, the reason nothing started and `abk status` count the blocked units and
  say what each waits on, and the graph shows them as blocked.

- A pull request's description now opens with why the change exists (the `Why` of its
  proposal, cut at a paragraph with a pointer to the rest) and what the pull request does
  (the "Done when" sentence of each task group it builds), ahead of the stack position,
  scope and verification. "How this was built" is one line, a follow-up recorded both as a
  summary and as a located line is listed once, and when the description is fitted to a
  host's limit the reason and the goal are the last to be shortened. When the reviewer
  approves it also describes the branch (a summary and its core changes, from the diff, in
  the same reply); the changes are stored with the approval and shown under what the pull
  request does, and a malformed description is ignored. A release older than this one
  refuses a unit record that holds a description.

- Units that have never run now start in order of their stack's age: after priority, a
  ready unit takes the age of the oldest unit that waits on it, directly or through a chain,
  so a prerequisite of old work no longer sits idle behind newer, unrelated units. The ready queue in `abk status` says "stack age, from <unit>" for such a
  place, and the tick logs which unit started ahead of which. A failed unit with others
  waiting on it is named in `abk status` and in the reason nothing started, with the number
  waiting and a hint to requeue it.

- The usage module is now the only authority on usage. One process refreshes the cached
  reading at its expiry under a lock, and any other asker is served the last good reading
  instead of calling the endpoint. A reading from the editor's cache is no longer used past
  the reset of its window. A leftover usage pause marker no longer shows a tick as paused:
  only a rate-limit pause does, and it stops new builds only until its deadline, within the
  same pass. The cache counts its hits, misses, expiries and waits (`abk.usage.cache`).

- A lock file named in a repository's environment lock inputs no longer holds a unit for
  "uncommitted changes" when the environment's sync creates or rewrites it. It is never
  listed as a leftover or discarded. A unit that changed a dependency input commits the
  rewritten tracked lock with it; otherwise the lock is restored to the branch's version
  before a commit or a restack, and a lock the branch does not track is never committed.

- Every use of the usage endpoint, and every reading answered from its cache, is now recorded
  in `usage-calls.jsonl` in the state directory (gitignored, a week's worth, no token): when,
  who asked, the outcome, the status, the latency and any rate-limit or retry headers.
  `abk status` prints one line from it (calls in the hour, refusals, the cache's share and the
  shortest interval between successful calls not followed by a refusal), and the figures are
  exported as a counter by outcome and caller and a gauge of that interval in seconds, drawn
  from the record when the metrics store is not available. The time a usage reading is kept
  now adapts to what the record shows: each refusal doubles it (up to the new
  `usage_cache_max_minutes`, an hour by default), a refusal's own retry time is respected when
  longer, and each further stretch of that time without one halves it, never below
  `usage_cache_minutes`. `abk status` says the time in use and what set it.

- The usage endpoint is now asked only when a fresh reading could change a decision. A
  refusal on a reading of a window that has not reset stands without a call, and an allowance
  stands while the usage could not have climbed to the threshold since the reading, judged by
  the fastest climb seen in the record (`usage_climb_floor` and `usage_climb_margin_pct` set
  the lower bound and the margin). A reading of a window that has reset, or none, is asked for,
  never more often than the cache time: inside it a start is refused for the time left and the
  reason says so. A round asks for no reading for units that `--only`, a lease or a backoff
  leave out. `abk status` shows the held reading with its age and calls the endpoint only with
  the new `--refresh`. The docs no longer claim that a step ending with nothing written is
  judged against the usage window.

- New `abk replan` plans changes again on demand: name changes (or a unit id), or use
  `--all` or `--failed`, and each is planned now whatever its recorded plan says, with
  the `Needs:` lines linked as a tick does. This is the way out of a stale dependency, a
  change that gave up planning, or a plan made beside neighbours that have changed. Started
  work is never touched, and the command prints only what differs. `--forget` clears the
  records and leaves the planning to the next tick, and with no selector the command lists
  each change's plan state. The give-up and failing-plan messages now name it, and the
  recorded plans are written under a lock so a command beside a running pass loses nothing.
  A change with a failed or held unit can now be planned again, where it was refused.

- Text that has to fit a size is now cut and shared out by one module: cuts that keep the
  head, the tail or both on a character, line or paragraph boundary and close any open code
  fence or collapsible block, and a fitter that gives each section of a text its smallest
  honest form, shares the rest by weight and passes on what a short section does not use.
  The general description cut is now a thin wrapper over it and cuts the same way. A pull
  request description is fitted once, to the lowest limit any registered code host allows,
  instead of being cut by whichever host receives it, so it reads the same on every host
  and a host added later with a lower limit lowers it; the hosts send what they are given.

- The agents that write tests, implement, fix checks and rework are now told to look for
  existing code before adding any: search by behaviour as well as name, use or extend a
  helper, constant or fixture that exists, write shared logic once, give calls that must
  change together one function, delete what the change makes dead and stay within the
  change. A session that is continued is not told again, and rework now also looks for the
  others of the kind when feedback names one duplicate. The agent that writes tests first
  searches and decides whether to reuse, generalize or create before it stubs a function a
  task names, puts new tests only in files where every test fails, and the implementing
  agent may repoint a test whose stub duplicates existing code; the reviewer counts such a
  stub. The authoring skill now tells authors to describe behaviour and name code only when
  the name is a contract; copies of the skill in planning repositories stay as they were
  until `abk install-skills` is run.

- Tests carrying the tier-2 marker now run under their own time limit, thirty minutes
  by default and set by `--tier2-test-time-limit` (zero turns it off), instead of the
  sixty seconds every test had, which failed live acceptance runs that take minutes.
  Every other test keeps `--test-time-limit`, and a failure says which kind of limit
  it passed.

- Configuration can now describe the environment the pipeline runs in: an `environment`
  section with a required `sync` command, a required `check` command and the dependency,
  lock and other files that decide when a sync is needed. A repository entry takes the same
  section. `abk init` writes it where it recognises the layout (and says to set the commands
  by hand where it does not), and fills it, and `limits.generated_files`, when an existing
  file lacks them, leaving a section already there alone. `abk doctor` warns where none is
  managed, reports a listed file that does not exist and runs `check`. The lock files named
  in the environments are left out of a unit's size, and the built-in list of lock file
  names is gone: an installation relying on it must run init's fill step, or list them.
  The tick now keeps that environment current: when work is found it syncs on a changed
  input, checks, syncs once more if the check fails, and stops with a non-zero exit and the
  output when the environment stays unhealthy; `abk status` shows its state. A unit whose
  tier 1 cannot run because the check fails is failed with the new cause `environment`
  before any agent round is spent, keeps its slot, is named as waiting for the environment,
  and is resumed by the tick once the environment is healthy again. A unit's own failure
  while the check passes is handled as before. A repository's own `environment` section is
  now kept current in each unit's worktree: before the tests and before every tier 1, `sync`
  runs there when its inputs changed since the worktree was last synced, then `check`. A
  failure with inputs equal to the base branch's is the environment's (the same cause); a
  failing `sync` or `check` after the unit changed its own manifest goes to the fix round
  with the output.

- Cost in the ledger is now each call's own spend. A Claude Code call's reported cost is the
  session's running total, so every report, summary, the web UI and the `abk.agent.cost`
  counter counted a session's earlier calls again in each resumed call. Each agent row now
  carries a `cost` object (the call's `incremental_usd`, the session's `cumulative_usd`, a
  `basis` and, with a gateway, the runtime's own figure), and every sum adds the incremental
  figure. Older rows with a flat `cost_usd` are read as `legacy`: counted, listed and totalled
  apart in `abk report`, never added to the cost. `abk report` also shows each session's
  cumulative cost and flags one whose increments do not add up. The counter is right from this
  release; figures exported before it stay overstated. `abk usage backfill-costs` repairs an
  existing ledger once (temporary: removed once every installation has run it): a dry run
  shows the before and after totals per unit, `--apply` keeps a timestamped copy and rewrites
  the ledger, and sessions whose figures fall and summaries with no detail left are listed.

- A test that fails under load and passes alone no longer fails the unit that met it. When
  tier 1 fails on tests, the profile reads which ones from the output and they are run again,
  serially, twice (python-uv has the hooks; a profile without them behaves as before). If
  they pass both times the flake is recorded in `flakes.jsonl` in the state directory and
  `abk status` lists each flaky test with its count and fix change. The pipeline writes one
  change that makes the test deterministic, with no model, and every unit that met the
  flake gets a `Needs: ... merged` line on it and is parked gated until it merges, then
  runs tier 1 again. A flake on a moved base no longer sends the unit back as a moved base.

- The review tab now shows a unit's uncommitted changes from a chat in their own section,
  marked as not yet committed. Their lines can be highlighted but not commented on, because a
  comment belongs to a commit. A selection in the diff can be sent to the unit's agent with
  **Ask the agent**: the agent tab opens with the file, lines, hunk and text attached to the
  next turn, and uncommitted lines are marked as such.

- A task group can now say how urgent it is with a `Priority:` line, 1 (most urgent) to 5,
  3 when unsaid; a line above the first group sets the default for the change. A unit takes
  the most urgent priority of its groups and keeps it once started, and `abk tags` shows a
  priority that is not 3. A priority is written to the units store only when it is not 3, so an
  older release refuses a store holding one with its usual message for a newer field.
  Ready units start by effective priority within their class, a prerequisite taking the
  priority of the most urgent unit waiting on it. `abk status` lists every unit whose priority
  is not 3 and the ready queue in start order with the reason for each place, and the graph
  page marks a priority that is not 3.

- A unit in review now reads `checking` while its pull request's checks are still running, or
  it was pushed moments ago and none has registered yet (`limits.checks_register_seconds`,
  default 120). It reads `in_review` once the checks pass. `abk status` lists a checking unit
  apart from one awaiting review, and the graph and the pull request's state label show the new
  name. Scheduling is unchanged.

- The graph page no longer marks a unit that landed over the size ceiling, so a merged unit
  stops looking unfinished. Its node reads as any other; the unit still records its actual
  size, the log still says it is over, and `abk status` still lists it.

- A chat with a unit's agent can now change files in the unit's worktree, and nothing is
  committed until you say so: those turns refuse `git commit` and `git push`, and sessions
  that are not the unit's own get only that refusal. The chat's lease records the changed
  files and outlives the page and the server, so the tick never mistakes them for a killed
  run's leftovers: it parks the unit as `attached` and `abk status` lists it with the number
  of files. `abk attach release <unit>` ends the attachment with `--commit MESSAGE` or
  `--discard` (never while a step is running on the unit, and a rejecting hook prints its
  output and keeps the changes), a started server takes over what a server left, and the
  page can list and discard the changes, including those it took over. A unit the store has
  as running, paused or not, is read-only with that reason, and taking a lease clears a
  killed run's recorded start so its files are the chat's. Committing is one request that
  retries a reformatting hook, has the unit's agent fix a rejecting one, hands the unit to
  its checks and review without using a review round or the earlier approval, and releases
  the attachment; a commit made but not delivered is finished by the next server start,
  `abk attach release` or tick. `abk attach release` also leaves a unit the store has as
  running alone. The unit's own session is now given its change (proposal, design, spec
  deltas and its task groups, read-only) and told to change tests and code together; when a
  request contradicts a requirement it replies with a `spec-conflict` flag and edits
  nothing, which the page shows as a callout with Proceed anyway, Change the spec instead
  (a planning session opened with the flag as its first message) and Cancel, and a review
  comment that contradicts the change is answered in its thread with the flag. A session on
  the planning repo can be opened with `repo` set to `planning`. A session that is not the
  unit's own may change code and a change's task file together; its lease covers both
  checkouts. A commit names one checkout (the worktree or the planning checkout), never
  both. The planning checkout is committed on its own through `abk check` and `abk tags`
  of the change, with the agent fixing what they reject, and the answer lists what the
  commit means for started units (a `Needs:` edit, a plan change, a requirement a unit was
  built to) without changing any of them. When a session other than the unit's own commits
  to its branch, the unit's next check fix, review and rework prompts list that commit as
  authoritative and not to be reverted.

- A repo can now set `forge: local`: its pull requests, and the review comments and decision
  made in the web UI, are kept in the state directory instead of on a code host, with no
  network call. Labels, drafts, statuses, checks and stacks do nothing for it. The setting is
  never inferred from a remote. A merge you make with git (merge commit, fast-forward or
  squash) is detected and remembered even if you delete the branch afterwards, a repo with no remote is built, fetched and pushed against its own
  trunk and local branches, and an agent can read its pull request with `abk pr view` and
  `abk pr diff`, which find the installation through `ABK_CONFIG`, now set in every agent
  run's environment.

- New `abk approve <unit>`, and the web UI's approve button now works: both record your
  approval of the unit's current review round, with the head commit of its pull request, and
  merge nothing, push nothing and vote on nothing. They are refused, with a reason, for a unit
  with no pull request or head and for a round that already has a decision. Stored review
  decisions now carry the head they were made at; older ones read as before.

- Tier 1 now ends a command that does not finish. A command past `limits.tier1_command_seconds`
  (an hour by default) is asked to abort so its runtime can dump its threads, killed after
  `limits.tier1_abort_grace_seconds`, and fails tier 1 naming the command and the time with the
  end of its output. The output cap is now idempotent, so an idle file is no longer rewritten
  every pass. In this repo's tests, a hung test fails after a minute, and a guard rejects a new
  bare sleep, unjoined thread or fixed port.

- A start the usage guard refuses now pauses only that unit. The pass keeps running its rounds,
  recording merges and comments, asks the guard again at each one, admits builds as soon as it
  allows and resumes the paused units, instead of ending at the first refusal. A window that is
  used up still refuses every start; a build the model itself refuses still holds new builds
  until its pause ends.

- A usage pause no longer ends before it was written. The grace after a reset is added once, a
  reset time that has already passed counts as unknown (retry in thirty minutes), and a reading
  too old to trust pauses for a short, new `usage_stale_retry_minutes` (five by default) and
  says it is stale and where it came from. A reading served from the cache file now reports
  its own source instead of passing for live. The pause line shows local time.

- The usage endpoint is asked less and one failed request no longer pauses anything. A good
  reading is reused for fifteen minutes (`usage_cache_minutes`) by every process, a rate-limit
  answer starts a cool-down that all processes honour, a timeout is retried once, and a failed
  call falls back to the last good reading younger than `usage_fallback_minutes` before the
  editor's. The cause of a failed call is logged once per tick, a refused start names the rate
  limit and when the next call is made, an expired token answered with an HTTP error is still
  refreshed, and a unit's gate takes one reading for both its answer and its resume time.

- A runtime that names no models, such as ACP, now builds units: the nodes that write tests,
  implement, fix checks, rework and adapt, and a continued session, no longer fail at once with
  a missing `model` argument before the agent starts. An empty model means the agent's own
  default.

- A unit in review now goes back to planned while a unit it is stacked on in the same repo is
  changing its branch (a rework that has committed, a rebase, or a failed or held run with
  commits it has not pushed), instead of staying ready for review on a base about to move.
  It keeps its approval, branch and pull request, and when the predecessor is back in review
  it restacks onto the new head, keeping the approval if the restack is clean.

- A pull request's checks are now one list, each with a name, a status (`passed`, `failed`,
  `cancelled` or `pending`) and a link where the host gives one, on both GitHub and Azure
  DevOps, instead of separate lists of failing and cancelled names. A check state the forge
  does not know counts as pending, never failed. The poller records each check's status
  (the most severe where several checks share a name); snapshots recorded before this are
  recorded afresh on the next poll without sending anything back.

- A running unit now reads `rebasing` (a conflict or moved base), `reworking` (review or check
  feedback) or `running` in `abk status`, the graph and the pull request's state label, and a
  pull request is made a draft whenever its unit goes back to planned, then published when the
  unit is in review again. Nothing new is stored: the names are derived.

- A review made in the web UI now reaches a unit like one made on the host: a new comment or
  reply sends it back for rework, Request changes counts as a changes-requested review, and
  Approve is recorded without merging, and a second Request changes in a later round sends it
  back again. The rework is given each comment with its file, line and id, and the summary of
  a Request changes. The agent's replies are written into the threads they answer, not posted
  to the host, and are not read back as new comments. Every review note, from the host or the
  UI, now carries the diff hunk for its line, and the rework prompt prints it under the
  comment with that line marked, with ten lines around it and once per line; a line the diff
  no longer holds prints none. A changes-requested review made on the host is never hidden by
  a UI approval, and a thread the reviewer resolved is not given to later reworks.

- `abk serve` now answers a unit's review diff, pinned to one commit and taken against the
  base the unit builds on (only its own work, for a stacked or restacked unit), and keeps a
  unit's review threads, replies, summary and decision in the state directory. A thread
  made at an earlier commit is marked outdated and moved to its line where the lines still
  match.

- `abk serve` unit pages have requeue, hold, release and approve buttons. They run the same code
  as `abk requeue` and the poller's hold and release under the unit store's lock, log the web
  UI as the actor, and are disabled, with the reason shown, when the unit cannot take them.
  Hold and release do not change the label on the host. Approve is always disabled: the CLI has
  no approve command.

- The web UI has a review tab at `/units/<change>/<n>/review`: the unit's diff with a file tree,
  its threads beside their lines (outdated ones marked) and the reviewer's findings. Selecting
  lines highlights them without making a comment, and the selection is kept in the address, so
  a line or range can be linked to; a finding in the verdict highlights its line, and a link to
  a line of an earlier commit opens at the nearest matching line or says the line is gone. A
  large diff draws each file as it scrolls into view. The tab is one of the unit page's tabs.
  A reviewer can comment on the selected line or range, reply to a thread, resolve or reopen
  it, write a summary and choose Request changes or Approve; a round that already has a
  decision shows the server's reason. The review answer now lists the latest review round's
  findings and the follow-ups it deferred, and `abk serve` locates a line of an earlier commit
  on the branch tip. Hovering a thread highlights its lines, and a thread that could not be
  moved to a line, or sits on a file no longer in the diff, is still shown, marked outdated.

- A reply to a reviewer that the host did not take now stays pending and is posted on a later
  pass, once, instead of being lost; a reply the host already holds counts as posted. The close
  of a satisfied unit's pull request is likewise repeated each pass until done, without posting
  its reason twice. `abk status` lists units with unposted replies or a pending close.

- An ACP agent's session is now continued with `session/resume`, and only when the agent
  advertises both resume and list and lists the session id for the worktree; otherwise the step
  starts a new session with its full prompt. `session/load` is no longer used. The usage ledger
  now counts a call under the node that made it, so a fix that continues the build session is
  the fix's spend, with the session id kept as an attribute of the record.
  A resumed ACP call records only the cost that session added during the call, not the
  session's running total, so continuing a session never counts earlier spend twice.

- A unit whose step cannot reach the code host is parked instead of failed. It goes back to
  `planned` with the cause `host_unavailable`, the step and the error text, and the pass
  readmits it after a wait that grows with each consecutive parking (1, 2, 5, 10, then 30
  minutes), logging how long remains. A unit already approved and pushed resumes straight
  at the pull request step, without running tier 2, review or rework again. Every failed
  unit now records its error text and step, visible in `abk status`.

- A unit no longer stays `running` after its run is gone. At the start of each pass, a running
  unit whose branch lock names a dead process is failed, so `abk requeue` can move it; one
  with a live holder, a thread to resume from, or no readable lock is left (the last is
  reported). Recording an outcome now
  retries once when the unit store cannot be read, and logs the unit as stranded if it still
  cannot.

- A units store written by a newer release no longer stops every tick of an older one. A field
  this release does not know is ignored when it is empty and dropped on the next write; one
  holding a value is still refused, now with a message naming the unit, the field and the value
  and saying a newer release wrote it. The rule belongs to the stored unit itself, so the web
  page reads such a store the same way instead of filtering fields on its own.

- Calls to a code host are now repeated by one layer, the same for GitHub and Azure DevOps,
  instead of by a loop in each. Every forge operation declares whether it is a read, an
  idempotent write, a create or advisory: reads and idempotent writes are repeated on a server
  error, a network failure or a rate limit; a create is repeated only after a read shows it did
  not land; an advisory call (a label add, a draft toggle) that cannot complete is logged and
  skipped, as is a status, comment, branch delete or PR edit that the pipeline never needed to
  succeed. A transient failure now reaches the layer from every operation, including the ones
  that used to log and carry on. Retries are logged and
  counted as `abk.forge.retries`, and a host that stays down raises `HostUnavailable`. New
  `ABK_FORGE_DEADLINE_SECONDS` (default 120) bounds the total time spent on one call.

- A unit's agent runs now leave a transcript: one JSON line per event (text, reasoning, tool
  calls and results, usage, stop) in the same shape for Claude Code and ACP, written as the
  agent streams. A reply or thought is one event, plans and permission requests are recorded
  too, and text the harness injects (such as a skill's expanded body) is not taken for the
  agent's. Tool results are cut at `limits.transcript_result_chars`, a unit keeps the
  transcripts of its last `limits.transcript_runs_kept` runs (all the calls of a run
  together), and archiving a change removes its transcripts.

- A repeated create is now safe on both hosts. Looking up a pull request by its branch raises
  when GitHub cannot be reached or answers something unreadable, instead of reporting that
  there is none, so an outage can no longer lead to a second pull request. A create refused
  because the pull request already exists returns that pull request. Each host can say whether
  a comment or reply with the pipeline's marker and a given body is already there, so a post
  whose answer was lost is not posted twice. On Azure DevOps a refused body update or commit
  status after a create is logged and skipped, as on GitHub, instead of failing the unit.

- A `Needs: ... merged` line added to a unit that has already started now gates it. A failed or
  held unit requeued before the dependency merges waits as `planned` with the cause `gated`,
  keeping its work, and `abk requeue` and `abk status` name the group it waits for; the tick
  resumes it in the mode it was requeued with once the dependency has merged. A unit sent back
  for rework waits the same way, and a running one is told once and left alone. A merge gate is
  never the unit's base, and an edit that only adds a `Needs:` line no longer re-plans the change.

- `ABK_GITHUB_API_URL` sets the address GitHub calls go to, for GitHub Enterprise or a
  stand-in host in a test. The forge and `abk doctor`'s credential check both use it, and
  a trailing slash is ignored. On an Enterprise host, set `GH_TOKEN`: the `gh auth token`
  lookup asks github.com. Unset, it is `https://api.github.com` as before.

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
  A unit's agent tab streams a running step and, once the step has ended, takes turns to
  the unit's session: the first turn takes a lease the tick respects (no step starts on the
  unit while it is held), and releasing it or closing the page (once its turn has ended)
  returns the unit; a lease left by a server that died holds nothing. One turn runs at a time
  on a session, on the model it recorded, and a session a running editor or `claude` process
  has open is read-only. A turn can
  carry a file, line range, diff hunk and selection from the diff, and a permission request
  waits in the browser (closing the page denies it). The sessions page lists sessions started
  in an editor or elsewhere, resumes an idle one in place, forks one a running process holds
  (never writing to the first), shows an ACP session its agent cannot resume read-only and
  continues it as a new seeded session, and starts new sessions (a "New session" form) in a
  unit's worktree or a repo on a chosen runtime and model. The sessions page counts as one
  open page: leaving it returns any unit its turns took and denies their open requests, and a
  "Release the unit" button gives the unit back sooner. `CLAUDE_CONFIG_DIR` (or `ABK_CLAUDE_HOME`) says where
  Claude Code keeps its sessions.

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
  the model the build began on in the unit's state; a unit saved by an earlier release
  loads with no sessions recorded. `abk.yaml` gains `session_reuse`, per agent role
  (`build` on, `review` off by default); a role it does not name is off, and `review: true`
  or an unknown role is refused. With `build` on, `implement`, `fix_checks`, an
  `adapt` and a rework (of a review round, failing checks or a pull-request comment) now
  continue the build session with a prompt of only what is new, on the model it began on,
  instead of starting over with the whole task; the first thing in it is the branch's old and new head when the
  branch moved. A session that cannot be continued (gone, over its context, a runtime that
  cannot resume, a head no longer in the worktree) gives a new session with the full prompt,
  and the run log says why. `review` never continues a build session or an earlier review round's session.
  `fix_checks` now starts a new session on the model the build began on, not the rework
  model, and a continued session runs on the model it recorded. The accounting rounds of
  `adapt` continue the session the port ran in, which stays the recorded build session.
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
