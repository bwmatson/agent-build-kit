# Design

## What was checked, and what was not

Read-only, in the agent-build-kit checkout at `origin/main` (229be1d; the first design of this change was written at
4878297) and in the merged change `the-recommended-policy-ships-with-the-kit` (archived). No agent was started, no model
called, nothing built.

- **VERIFIED, the matcher.** `runtimes/recommended_policy.py` holds `DIALECT` (fnmatch globs, case-insensitive, matched against
  the whole command and each segment split at `&&`, `||`, `|`, `;` and a newline, whitespace collapsed, anchored) and
  `matches(pattern, command)`, the kit's own implementation, plus `UNCOVERED` (six classes: skipping the commit gate, a hard
  reset, discarding untracked work, force-deleting a branch, a recursive delete, a bare force push), `KNOWN_GAPS` and
  `KNOWN_FALSE_POSITIVES`. Its module docstring calls `matches` "a reference matcher, an approximation of an agent's own:
  the live policy check is the confirmation"; that sentence is changed here (group 1).
- **VERIFIED, the reader.** `runtimes/policy_apply.py`: `resolve_home(descriptor, env_file)` (the home variable through
  `settings.named_value`, process environment first then the installation's `.env`, else the default under the person's
  home) and `held(descriptor, home) -> Held | None` (read-only: `None` when there is no file, `ApplyRefused` when it does
  not parse or the deny path is not a list, else `Held.deny`). Callers already have the installation's `env_file`
  (`cli/policy_cmd.py` passes `installation.env_file`).
- **VERIFIED, the table.** `runtimes/known_agents.py`: `KnownAgent.apply` is `ApplyPolicy | None`; only the first row has
  one. `agent_for_command(command)` matches the program's basename; `known_agents` imports no protocol library.
- **VERIFIED, the command list.** `runtimes/acp.py` `PROBE_CLASSES`: `probe_rows()` spellings, then six plain commands, one
  for each class in `UNCOVERED`. The module imports the protocol library (`from acp import ...`) at its top, and
  `runtimes/__init__.py` registers it only when that library is present, so the static check reaches `PROBE_CLASSES`
  only through a runtime that exists. The number of commands (about 32) is UNVERIFIED here; the first design counted 32.
- **VERIFIED, what the live probe measures.** `_probe` (`acp.py`) drives the agent through `_Session` with the client's own
  rules on, and `_ProbeTracking` marks a command refused when the *client* refused it (`create_terminal` refusing it by
  the rules, or `request_permission` answered with a refusing option; `acp.py` `note_refused` call sites). So today's probe
  mostly measures abk's own client-side command rules, which the agent's configuration does not decide. The static check
  reads only the agent's configuration and says nothing about those rules; they are held to the recommendation by
  `tests/pipeline/test_recommended_policy_agrees_with_rules.py`. This is a change in what the check means, and the
  documents say it (group 5).
- **VERIFIED, the pass rule today.** `_probe` builds `unenforced` from every result not refused: the six `UNCOVERED` classes
  are counted, so a configuration that applies the recommendation completely fails the probe unless a client rule refuses
  them. **Changed here:** they never fail (requirement "Classes the recommendation leaves to the person never fail the
  check").
- **VERIFIED, the callers.** `cli/doctor.py` `_runtime` calls `policy_check.checked(runtime, inst.root, cache=...)` and
  fails with `describe` and `fix_for`; an entry marked `PolicyMarker.UNCHECKED` is a warning with no check. `cli/init.py`
  `_policy_step` asks "sends the agent a prompt and spends tokens; run it? [y/N]" when `runtime.policy_check_prompts_agent`
  and not `--yes`, and `_policy`, `_report_again`, `_apply_builtin` call `policy_check.checked`. `runtimes/claude_code.py`
  `check_policy` returns `PolicyReport(ok=True)` locally (`policy_check_prompts_agent = False`).
- **VERIFIED, the cache.** `runtimes/policy_check.py` is `checked` (a JSON file `policy-check.json` in the state directory,
  15 minutes, per runtime), `cache_path`, and the pure helpers `describe`, `unrefused`, `classes_of`, `fix_for`.
- **VERIFIED, the e2e-test limit.** A `local_stack` test is limited by `--e2e-test-time-limit` (thirty minutes by default;
  `docs/architecture.md`, `tests/time_limit.py`). Existing e2e-test tests find the agent through
  `<redacted>` and skip without it (`tests/integration/test_acp_build_unit.py`).
- **UNVERIFIED, for the builder to confirm and correct here:**
  - how the first known agent signals a refusal by its own deny list over the protocol when the client allows every request:
    as a failed or blocked tool call, as a refusal message with no terminal request, or in some other way. The acceptance test
    depends on telling "refused" from "reached the client's terminal"; group 4 reads this from a real run first and
    records it in `docs/agent-runtimes.md`;
  - that the agent's own approval step, when the client allows everything, refuses nothing beyond its deny list, so the six
    classes the recommendation does not cover are observed to run;
  - that the first known agent's matcher implements `DIALECT` for the patterns the recommendation ships, including its
    wrapper-prefix and segment handling: this is exactly what the acceptance test shows, once per change, and is not
    assumed by the check;
  - that a doctor run reaching `runtimes.candidates` never starts the first known agent (it runs `--help` only for a row with
    more than one start variant, `known_agents._candidate`, which the first row does not have); the "never started" tests
    judge the check itself.

## 1. A static check

`policy_check` keeps the pure helpers and gains one function, `check_policy(runtime, entry, installation)`, which every caller
uses:

- the runtime is the protocol runtime (`known_agents.RUNTIME_NAME`): `agent_for_command(entry.command)`; no row, or a row with
  no applier, is the "cannot check" report (section 3); otherwise `home = resolve_home(row.apply, installation.env_file)`,
  `held(row.apply, home)`, and one result per `PROBE_CLASSES` entry:
  `refused = any(matches(pattern, command) for pattern in held.deny)`, `by` the first pattern that matches in list order;
- any other runtime (the Claude Code one): its own `check_policy(cwd)`, unchanged, which answers locally and reads no
  configuration.

`PolicyReport` gains defaulted fields only: `source` (the label above, empty for a runtime's own answer), `cannot_check` (the
reason, empty otherwise); `SpellingResult` gains `by` (the refusing pattern, empty when none) and `by_design` (false by
default). `ok` is true only when `cannot_check` is empty and no result of a covered class is unrefused. The protocol
runtime's own `check_policy(cwd)` method stays only because the runtime protocol requires one; it starts nothing (a
requirement with a test), and it is not what doctor or init call, because `cwd` carries no installation and so no `.env` to
resolve the agent's home from (rejected: reading the process environment alone would ignore the installation's `.env`).

**What remains of `policy_check.py`.** The check is instant (a file read and a few hundred glob matches), so the 15-minute
cache goes with `checked`, `cache_path`, `CACHE_NAME`, `MAX_AGE`: a kept answer of a configuration someone has just edited
would mislead, and nothing is saved. An old `policy-check.json` in a state directory is never read and may be deleted. What
stays: `describe`, `unrefused` (now leaving out results of a class not covered by design), `classes_of`, `fix_for`, and the
new function.

## 2. No external code in the check

doctor, init and `abk policy check` read a file and run the kit's own function. They never start the agent, never import
from or call into its installation, never run another program's script. The requirement has a test: the runtime's command
points at a program of the known-agent table's name that records any start and exits non-zero, and the check runs through
the chooser, doctor's runtime-policy check and `abk init --policy-only`; the program was never started, and the verdict is
still given. Removed with this: `KnownAgent.oracle`, the interpreter lookup, the subprocess runner,
`limits.policy_oracle_seconds`, the private-function risk (the earlier design called a function the agent does not promise
to keep), the production probe (`AcpRuntime._probe`, `_ProbeTracking`, `_probe_prompt`, `_Session`'s probe hook, and
`check_policy`'s use of them), `abk policy check --live`, `limits.policy_probe_seconds`, the heartbeat, the process-group
kill in production, the token-spend question (and `policy_check_prompts_agent`, which only existed to drive it), and the
cache. `PROBE_CLASSES` stays in `acp.py` as the one list of commands the check judges; its comment, which names the probe,
is rewritten.

## 3. When the check cannot be made

- **No table entry, or an entry with no applier** (nothing says where its deny list is): "cannot check: abk has no policy for
  this agent". `abk policy check` and `abk init --policy-only` exit 1 (the check could not be made; 2 stays for usage),
  doctor warns, nothing is reported refused or not refused, and it is never a pass. Treating an entry without an applier
  like no entry is a decision made here, because the table is the only place a deny list's location is recorded; a row gains
  an applier by being verified, as the first one was.
- **A missing configuration file** is a failure (doctor fails, exit 1) saying no configuration was found at the path and which
  variable would point elsewhere: an absent file holds no rules, and "nothing refused" would be a fact about nothing.
- **A configuration that does not parse, or whose deny path is not a list**: a failure naming the path and the reason (the
  applier's own `ApplyRefused` text).
- The installation's own `policy_fix` and `fix_for` are unchanged. An installation that recorded `policy: unchecked` is still
  warned about and not checked; init no longer writes that marker because it no longer asks.

## 4. Classes the recommendation leaves to the person

A result whose label is in `recommended_policy.UNCOVERED` is `by_design=True`: reported "not covered by design: <class>" when
no pattern refuses it, "refused by `<pattern>` (not required)" when one does, and left out of the unenforced list and the
verdict. **Today's probe fails these classes (verified above); this change reverses it.** A class not in `UNCOVERED` is
covered, so nothing is exempted by being hard to refuse. A person who wants the six refused adds
`runtimes.<name>.policy_extra` patterns, as before; they then show as "refused, not required".

## 5. Callers and the on-demand command

- `abk doctor`: ok text says every covered class is refused and carries the label; a failure lists the unrefused classes and
  spellings as today with the same `fix_for`; "cannot check" is a warning; a missing or unreadable configuration is a
  failure.
- `abk init`: `_policy_step` loses the token question for every runtime; `--yes` changes nothing about the check; the fix
  offer, `--run-policy-fix`, the built-in fix and the re-check after it call the same function, and each re-check reads the
  file again.
- `abk policy check [--runtime NAME] [--agent NAME]`: prints each class and spelling with its pattern or "not refused", the
  not-covered rows, and the label; exit 0, 1, 2. `abk policy show`'s sentence "the policy check is not run here; `abk doctor`
  runs it" now points at `abk policy check` as well. `abk policy apply`'s closing line names `abk policy check` instead of a
  token-spending live check.

## 6. The acceptance test: the matcher agrees with the agent

One `local_stack` test (e2e-test, last group, the only place the kit runs the agent for this) drives the real agent, named by
`<redacted>` as the sibling e2e-test tests do, over every `PROBE_CLASSES` command and asserts, per command,
that the agent's observed behaviour equals the static verdict over the configuration the agent runs with.

- **No command is executed.** The harness is the old probe's logic moved into test support and cut down: a client built on the
  connection helper the runtime uses (`connect_to_agent`), which allows every permission request and answers a terminal
  request by recording the command and returning an empty result, never running it. A command the agent refuses by its own
  deny list never reaches the client's terminal (UNVERIFIED how it signals this, above); one it runs does.
  Because the client allows everything and abk's own command rules are off in this client, the only source of a refusal is the
  agent's configuration, which is what the verdict is about.
- **Bounded.** An overall deadline held in the harness (ten minutes, far under the e2e-test limit of thirty), a progress line
  to standard error as each command is judged, and a heartbeat every 30 seconds while none is. The agent is started in a
  session of its own; on the deadline, SIGINT and SIGTERM (handlers installed for the harness and restored after) the whole
  process group is killed, waited for, and every temporary directory removed in a `finally`. A did-not-finish result fails
  the test with how many commands were judged, never passes it, and is neither a refusal nor an agreement.
- **Tested without a real agent.** The harness itself is unit-test (group 4): a fake agent that never answers, a fake that
  judges three commands then stalls, and a signal during a run, so the deadline, the progress and the cleanup are proven
  before the real agent is involved.
- **Non-vacuous.** The test fails, saying so, when the verdict refuses no command at all (a configuration with no policy
  shows nothing), and compares every command, the six not covered by design included: for them the verdict is whether a
  pattern matches, and the agent's observation must agree.
- The first known agent's own repository may keep a test of its own if it needs one; this change has no task for it.

## The change's name

The first design asked the agent's own matcher, which the name says; this one reads the configuration. The better name is
`policy-check-reads-the-agents-config`. **The directory is kept as it is.** Verified in `agent-build-kit` at 229be1d
(`cli/pipeline.py` `plan_all`, `cmd_replan`; `pipeline/unit_store.py` `upsert`; `pipeline/units.py` `ready_units`): units are
stored by id `<change>/<n>` with their change name; `plan_all` visits only changes that have a `tasks.md` on disk;
`UnitStore.upsert(units, change=...)` demotes to `unplanned` only stored `planned` units whose `change` equals the one being
planned, so units of a change whose directory is gone are neither dropped nor demoted; `ready_units` picks every `planned`
unit and checks nothing on disk; and `abk replan <name>` for a name that is no directory prints "is not a change". A rename
would therefore leave `<old>/1` to `<old>/3` stored as `planned` and startable with no `tasks.md` to read, while the renamed
change planned three more units beside them. Keeping the name lets `abk replan` reshape the same three unit ids in place. A
rename becomes safe once the old units are removed from the store by hand, which is outside this change.

## Left in place, deliberately

- The `policy_probe` overhead node name stays in the vocabulary and in the usage-accounting specification, unused by the
  product after this change; removing it is a change to another capability and to recorded history.
- `PolicyMarker.UNCHECKED` stays honoured by doctor.
- The recommended-policy requirements that say "by the reference matcher" stay: it is now the matcher, and the acceptance test
  is what shows it agrees with an agent's.

## Alternatives rejected

- **Ask the agent's own private matcher** (the first design): runs another program's internal code from a diagnostic and
  breaks on a rename; the kit must be self-contained.
- **Keep the live probe for agents with no table entry:** it spends tokens and was the cause of the hangs; such an agent is
  "cannot check", and a person can run the acceptance harness's logic by hand.
- **Keep a cache:** the check is instant; a kept answer only misleads after an edit.
- **Fail the six uncovered classes:** teaches a person to ignore the check.
- **Run the agent in the product as a periodic confirmation:** reality is checked once per change by e2e-test, not at every run.
