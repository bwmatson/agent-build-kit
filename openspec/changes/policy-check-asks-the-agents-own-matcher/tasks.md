# Tasks

Acceptance: group 6 runs the real agent over the probe commands with a client that executes nothing, and asserts the agent's
behaviour agrees with the static verdict for each command.

Priority: 2

## 1. [agent-build-kit] [unit-test] The check reads the agent's configuration and judges every probe command with the kit's matcher

Done when one function reads a known agent's real configuration through the applier's reader and returns a `PolicyReport`
with a result per probe command naming the pattern that refused it, the classes not covered by design never fail, every case
that cannot be answered is a distinct non-passing report, the report carries the label, nothing of the agent is run, and the
answer is no longer kept. Nothing yet calls it from a command. Estimate: about 330 changed lines.

The function takes the resolved installation as an argument; it does not read the environment itself. `PROBE_CLASSES` stays in
`runtimes/acp.py` as the one list of commands.

- [x] 1.1 Test: `tests/runtimes/test_policy_check_static.py` asserts a temporary home whose configuration holds exactly the
  recommended patterns gives an ok report with a result per probe command in table order, each covered result refused with
  `by` set to the first matching pattern in list order, `source` set to the label "what the configuration says, in abk's
  dialect; not observed from the agent", and the six classes of `recommended_policy.UNCOVERED` marked `by_design`.
- [x] 1.2 Test: the same file asserts a configuration that lacks the amend patterns gives a report that is not ok, names the
  amend spellings as not refused and no other class, and that `fix_for` text is unchanged; and that an empty deny list reports
  every covered spelling unenforced.
- [x] 1.3 Test: the same file asserts a `by_design` class not refused does not enter `unenforced` or change `ok`, that one a
  pattern refuses is reported refused with its pattern and "not required", and that `describe` and `unrefused` leave out a
  class not covered by design.
- [x] 1.4 Test: the same file asserts an absent configuration file, a configuration that does not parse and a deny path that is
  not a list each give a report that is not ok with `cannot_check` naming the path and the reason, and no command reported
  refused or not refused.
- [x] 1.5 Test: the same file asserts a runtime command with no table entry, and a known agent whose row has no applier, each
  give `cannot_check` "cannot check: abk has no policy for this agent" and a report that is not ok, and that a runtime that
  answers on its own (the Claude Code one) keeps its own answer and reads no configuration.
- [x] 1.6 Test: `tests/runtimes/test_policy_check_runs_no_agent.py` asserts the function judges the policy with the runtime's
  command pointing at a program of the first known agent's name that records any start and exits non-zero, and that the
  recorded start never happens; and that the protocol runtime's own `check_policy` method starts nothing.
- [x] 1.7 Test: `tests/runtimes/test_policy_check_instant.py` asserts the function over a configuration of several hundred
  entries finishes in under one second and that two runs in a row read the file twice (no answer is kept).
- [x] 1.8 Test: `tests/runtimes/test_policy_report_fields.py` asserts the added defaulted fields (`source`, `cannot_check` on the
  report; `by`, `by_design` on a result) load from a report written without them and that `ok` is unchanged for such a report.
- [x] 1.9 Add the defaulted fields in `runtimes/base.py`, replace `checked` and the cache (`cache_path`, `CACHE_NAME`,
  `MAX_AGE`) in `runtimes/policy_check.py` with the checking function and keep `describe`, `unrefused`, `classes_of`,
  `fix_for`; delete or rewrite the tests of the cache (`tests/runtimes/test_policy_check.py`); and change the module
  docstring of `runtimes/recommended_policy.py` so `matches` is the check's matcher and not "a reference matcher".
- [x] 1.10 Confirm the UNVERIFIED item of design.md about doctor's runtime candidates never starting the first known agent, and
  correct design.md if it does.

## 2. [agent-build-kit] [unit-test] Doctor, init and `abk policy check` use it, and ask nothing

Done when `abk doctor`'s runtime-policy check and the init policy step call the one function, no runtime is asked a
token-spend question with or without `--yes`, `abk policy check` runs it on demand, a "cannot check" agent is non-zero in
`--policy-only` and a warning in doctor, and `abk policy apply` names `abk policy check` as the way to confirm. Estimate:
about 340 changed lines.

- [x] 2.1 Test: `tests/cli/test_doctor_policy_static.py` asserts doctor over a configuration holding the recommendation
  passes, says the answer is what the configuration says and not observed from the agent, starts no agent and keeps no answer;
  fails naming the unrefused class and spelling with the `fix_for` text; fails on an absent configuration naming the path; and
  warns "cannot check: abk has no policy for this agent" for an unrecognised command and never passes it.
- [x] 2.2 Test: `tests/cli/test_init_policy_static.py` asserts `abk init --policy-only` and the init policy step ask no "spends
  tokens" question with or without `--yes`, print each class with its refusing pattern, exit 0 or 1 by the rule (1 for a
  failed or "cannot check" answer, 2 for a usage problem), and that `--run-policy-fix` and the built-in fix check again
  through the same function reading the file again.
- [x] 2.3 Test: `tests/cli/test_policy_cmd_check.py` asserts `abk policy check` prints every class and spelling with its
  pattern or "not refused", marks the classes not covered by design, prints the label, changes nothing, starts no agent,
  exits 0, 1 and 2 by the rule, and that `--agent NAME` with an unknown name exits 2 naming the known agents.
- [x] 2.4 Test: `tests/cli/test_policy_cmd_apply.py` asserts the closing line of `abk policy apply` names `abk policy check`
  and says it reads the configuration and spends no tokens, and that apply starts no agent.
- [x] 2.5 Test: `tests/cli/test_policy_one_chooser.py` asserts doctor, init and `abk policy check` each call the same
  function (by patching it), and that doctor with a command that is a program recording any start and failing never starts it.
- [x] 2.6 Test: `tests/cli/test_doctor_policy_unchecked.py` asserts a runtime recorded as unchecked is still a warning with no
  check, and that init no longer records that marker.
- [x] 2.7 Change `cli/doctor.py` and `cli/init.py` to call the function and drop the token question and
  `policy_check_prompts_agent` from `runtimes/base.py`, `runtimes/acp.py`, `runtimes/claude_code.py`; add `abk policy check`
  to `cli/policy_cmd.py` and the apply line; update the shared test fakes (`tests/cli/policy_step_fakes.py`) and the init and
  doctor policy tests that faked the probe or the cache.

## 3. [agent-build-kit] [unit-test] The live probe and its remains are removed from the product

Done when the protocol runtime holds no probe, `_ProbeTracking` and the probe prompt are gone, no setting, flag or prompt for a
probe or an oracle remains, and `PROBE_CLASSES` is still held to the command rules. Estimate: about 300 changed lines.

- [x] 3.1 Test: `tests/test_no_live_policy_probe.py` asserts the protocol runtime module has no probe or probe-tracking
  attribute, `limits` has no `policy_probe_seconds` or `policy_oracle_seconds`, the `abk policy check` parser has no `--live`,
  no source file asks "spends tokens; run it", and `KnownAgent` has no `oracle` field.
- [x] 3.2 Test: `tests/runtimes/test_acp_probe_classes.py` keeps what `tests/runtimes/test_acp_probe.py`,
  `test_acp_probe_row.py` and `test_acp_probe_spellings.py` assert about the list itself (every command is one the command
  rules forbid whichever branch or worktree, every spelling of the table is present, each class has a plain command), and
  nothing about driving an agent.
- [x] 3.3 Remove `AcpRuntime._probe`, `_ProbeTracking`, `_probe_prompt`, `_probe_worktree`, the probe hook of `_Session` and the
  protocol runtime's use of them, keeping a `check_policy` method that starts nothing; rewrite the comment of
  `PROBE_CLASSES`; delete the tests of the removed code (the driving parts of the three `test_acp_probe*` files and the
  fakes only they used).
- [x] 3.4 Search the source, tests and fakes for the removed names and for the cache file, and remove what is left; confirm the
  UNVERIFIED count of probe commands in design.md.

## 4. [agent-build-kit] [unit-test] A test harness drives an agent over the probe commands, bounded and cleaned up

Needs: fix-flaky-tests-runtimes-test-policy-agent-harness-py-test-an-ebfce51e group 1 — flaky test tests/runtimes/test_policy_agent_harness.py::test_an_agent_that_never_answers_ends_at_the_deadline_with_nothing_left

Done when test support can start an agent, drive it over `PROBE_CLASSES` with a client that allows every request and runs
nothing, report per command whether it reached the client's terminal, and stop on a deadline, an interrupt or a termination
signal with the agent's whole process group killed and every temporary directory removed, all proven with fake agents. The
real agent's way of signalling a refusal is read from one real run and recorded. Estimate: about 330 changed lines.

The harness is test support under `tests/`, not product code; this is where the old probe's logic goes.

- [x] 4.1 Test: `tests/runtimes/test_policy_agent_harness.py` asserts a fake agent that never answers and a one-second deadline
  give a did-not-finish result within a few seconds, with the agent's process group gone and no temporary directory of the
  harness left.
- [x] 4.2 Test: the same file asserts a fake agent that judges three commands and then stalls produces three progress lines
  naming them as they are judged and a heartbeat while it stalls, on standard error.
- [x] 4.3 Test: the same file asserts SIGINT and SIGTERM during a run give the same cleanup and result and that the signal
  handlers are restored afterwards.
- [x] 4.4 Test: the same file asserts a fake agent that asks to run a command gets it allowed, that the client records the
  command and runs nothing (a marker the command would have written does not appear), that a command the fake refuses without
  a terminal request is observed as refused, and that one it runs is observed as reached.
- [x] 4.5 Test: the same file asserts a harness that cannot start the agent keeps the error and does not report a pass.
- [x] 4.6 Add the harness as test support, built on the connection helper the protocol runtime uses, with its deadline,
  progress, heartbeat, signal handlers, process-group kill and `finally` removal, and the fake agents it is tested with.
- [x] 4.7 Run the real first known agent once over the harness on a machine that has it, read how it signals a refusal by its own
  deny list and whether its approval step refuses anything beyond the list when the client allows everything, and record the
  finding in `docs/agent-runtimes.md`; where it cannot be run, say so there and leave design.md's UNVERIFIED items standing.

## 5. [agent-build-kit] [unit-test] The documents say what the check reads

Done when the documents and skills describe a check that reads the configuration and has no probe, and the changelog says the
live probe is gone. Estimate: about 200 changed lines.

- [x] 5.1 Test: `tests/test_policy_check_documented.py` asserts `abk policy check` and the label appear in `docs/cli.md`,
  `docs/init.md` and `docs/agent-runtimes.md` and in the abk-pipeline and abk-config skills, that no document describes a
  probe that sends the agent a prompt, a token question for the check, `--live`, `policy_probe_seconds` or a 15-minute
  cache, and that `CHANGELOG.md`'s Unreleased section names the check and says the live probe is gone.
- [x] 5.2 Document it: `docs/cli.md` (`abk policy check`, exit codes), `docs/init.md` and `docs/agent-runtimes.md` (what the
  check reads, what it does not observe, the client-side rules it does not measure, not covered by design, "cannot check",
  the acceptance test and its harness, the finding of task 4.7), the abk-pipeline and abk-config skills where doctor's
  runtime-policy check is described, and an `## Unreleased` bullet in `CHANGELOG.md` that says the live probe, its token
  question and its cache are removed.

## 6. [agent-build-kit] [e2e-test] [acceptance] The kit's matcher agrees with the real agent

Split: acp

Needs: tier2-tests-are-tagged-by-runtime group 18 — parked until the live tests are tagged by runtime and the drift test guards them, so an ACP test that cannot run (the model backend is out of budget) is held instead of failing

Done when an e2e-test test drives the real agent over every probe command and each command's observed behaviour equals the
static verdict, under its own deadline. Estimate: about 180 changed lines.

This group is ACP-only on purpose: Claude's policy is local, so there is no agent-side matcher for the kit's to agree with,
and the test keeps its `ACP_ONLY_REASONS` entry (scenario name to the reason: only the protocol agent holds its own matcher)
and carries no Claude variant. Its ACP run did not finish within 600 s, so a person runs the step 6.4 asks for by hand on a
machine that has the first known agent; the tests 6.1 to 6.3 are written and held with the ACP split until then.

- [ ] 6.1 Test (`local_stack`): `tests/integration/runtimes/test_policy_check_agrees_with_agent_live_stack.py` skips without
  `<redacted>`, runs the group 4 harness over `PROBE_CLASSES` with the agent's own configuration, computes the
  verdict with the group 1 function, and asserts for each command that the observed refusal equals the verdict, failing by name
  with the command, the verdict and the pattern or its absence.
- [ ] 6.2 Test (`local_stack`): the same file asserts the test is non-vacuous: it fails saying the configuration holds no
  policy when the verdict refuses no command, and a did-not-finish result fails it with how many commands were judged.
- [ ] 6.3 Test (`local_stack`): the same file asserts its deadline is under the e2e-test time limit and that after it ends, pass
  or fail, no agent process of its group and no temporary directory of the harness remain.
- [ ] 6.4 Run it once on a machine that has the first known agent; where a command disagrees, correct the kit's dialect or the
  recommendation, or record the difference as a known gap, in the same change.
