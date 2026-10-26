# Tasks

Priority: 4

## 1. [agent-build-kit] [unit-test] The probe, the known-agent table and the runtime hooks

Done when a runtime can report the candidates it finds on this machine without a model call, the protocol runtime
carries the table of known agents, a runtime can declare setup questions and list its models, and none of it touches
`abk init` yet.

The probe takes `which` and `run` injected, as `abk doctor`'s `Which` is, so every test below uses fakes. Test files
mirror the source folders (`tests/runtimes/`); the table's own test names the product names it needs and no other
test does.

- [x] 1.1 Test: with a known agent's program and the optional library present, `detect` returns a usable candidate
      carrying its start command, its `needs` and its `verified` note; with the program missing, or present and the
      library missing, it returns an unusable one whose reason names which.
- [x] 1.2 Test: for an agent whose flag varies, the candidate's command is the variant the faked `--help` output
      selects, and output showing neither makes it unusable; a faked help run that raises a timeout makes it unusable
      with that reason and does not stop the other candidates being probed.
- [x] 1.3 Test: with `which`, `run` and an agent that records every request all faked, the probe starts no session,
      sends no prompt and makes no network call, and the help run it makes carries a 5 second timeout.
- [x] 1.4 Test: every entry of the known-agent table names a program and at least one start command, carries a
      non-empty `verified` note and a source, and no framework file outside the table's module and its test names a
      product from it.
- [x] 1.5 Test: Claude Code's `detect` reports the executable found on the path as usable, and its absence as
      unusable with that reason, from its own module.
- [x] 1.6 Test: `setup_questions()` of each runtime returns questions that carry a prompt, a default, a validator and
      the key they write to; the validators accept a program on the path and reject one that is not, an empty argv,
      and an unknown name. A fake runtime registered with its own question list is returned as declared.
- [x] 1.7 Test: `list_models()` against a stand-in agent (a real subprocess on the same library that fails on any
      prompt) that advertises three models and a current one returns them with the current one marked, opens a
      session and sends no prompt; against one that advertises none it returns an empty list and says so.
- [x] 1.8 Test: Claude Code's `list_models()` returns the documented aliases and says they are documented, not
      queried; no agent is started.
- [x] 1.9 Add the optional `detect(which, run)`, `setup_questions()` and `list_models()` hooks to the runtime
      Protocol so a runtime without them stays valid and offers no candidates, questions or list, and the `Candidate`
      and `Question` models (frozen pydantic models, with the closed sets of values as `StrEnum`s).
- [x] 1.10 Add the known-agent table as data in the protocol runtime's module and implement `detect`,
       `setup_questions` and `list_models` on it and on Claude Code, confirming whether the `models` session state, as
       well as the config option the adapter already reads, can carry a list.
- [x] 1.11 Add the optional `policy` marker (`unchecked`) to a runtime's `abk.yaml` entry, schema-strict, so an
       existing file loads unchanged.

## 2. [agent-build-kit] [unit-test] `abk init` asks which runtime and records the choice

Done when `abk init` probes, shows the candidates, asks which, asks that runtime's own questions, records the choice
and its command in `abk.yaml` and hands the chosen runtime to research and propose — in that order and before any agent
step — through the interactive, `--yes`, `--runtime`, `--agent-command` and kept-file routes, with the written file
loading without warnings. The models question, the `--set`/`--runtime-config`/`--dry-run` routes and the confirmation
before the write follow in group 3; the guided policy step, `--policy-only` and `abk doctor`'s use of the probe in
group 4.

- [x] 2.1 Test: with the probe faked to find nothing usable, `abk init --yes` prints what each candidate needs,
      exits 2 and writes no file; with exactly one usable, Enter at the question records it; with the list, the
      second candidate picked is the one written, usable ones are shown first, each unusable one shows its reason and
      the last line is the person's own configuration.
- [x] 2.2 Test: choosing the last line and entering an argv records it; a program that is not on the path is
      refused and asked again; going back shows the list again and another runtime can be chosen; a wrapper
      executable given for the current runtime is recorded.
- [x] 2.3 Test: `--yes` with several usable exits 2, prints the list and writes nothing, and with `--runtime NAME`
      (and `--agent-command ARGV` for the protocol runtime) proceeds; a kept `abk.yaml` that names a runtime skips the
      question, and `--runtime` overrides only after confirmation or with `--force`.
- [x] 2.4 Test: research and propose receive the chosen runtime (a fake records which) and run only after the choice
      is made; with `--skip-research --skip-propose` no agent step runs.
- [x] 2.5 Test: the written `abk.yaml` loads without warnings; a fallback runtime accepted at its question is
      configured under `runtimes:` and `runtime:` still names the first; with no other usable candidate the question
      is not asked.
- [x] 2.6 Test: a fake future runtime registered with its own questions is chosen and asked them, and its answers
      are written where it says, with no change to `cli/init.py` or `init/`; a secret is never asked for, and an
      agent's environment variable names, never values, reach the fragment.
- [x] 2.7 Move the runtime question into `cmd_init` between detection and the agent steps, using the hooks of group
      1 (the runtime's own questions asked through `setup_questions()`, so init holds no per-runtime code), and pass
      the chosen runtime to research and propose; handle `--yes`, a kept `abk.yaml` and the fallback question.
- [x] 2.8 Add the flags `--runtime` and `--agent-command`, validated by the same validators as the typed answers,
      and `--force` overriding a kept file's runtime.

## 3. [agent-build-kit] [unit-test] Setup questions and models, the other routes and the confirmation

Done when `abk init` also asks the runtime's models question and a table entry's needs question, accepts `--set` and
`--runtime-config`, shows the fragment and writes only on confirmation (`--dry-run` writes nothing), with its part of
the docs and the changelog written. The policy step, `abk doctor`'s use of the probe and `--policy-only` follow in
group 4.

- [x] 3.1 Test: a table entry that needs a running backend asks whether it is running and whether to continue
      anyway; Claude Code's models question offers the defaults, a choice per role and typed names, and each is
      written as given without any agent started; an agent advertising models shows them with its current one
      marked default and the choice lands under `models:`; one advertising none says so, leaves the roles empty and
      accepts a typed name; a stand-in agent that fails on any prompt shows that listing sent none.
- [x] 3.2 Test: typed answers, repeated `--set`, and `--runtime-config FILE` produce an identical fragment; an
      unknown key in either fails naming the key and writes nothing; declining at the confirmation writes and changes
      no file; `--dry-run` prints the fragment and writes nothing.
- [x] 3.3 Ask the table entry's needs question and the models question through the runtime's hooks (`list_models()`
      and the questions of group 1), put the choice under `models:`, and add the confirmation before the write: show
      the fragment and write only on a yes (`--yes` is the confirmation for a fully specified run).
- [x] 3.4 Add the repeatable `--set` and `--runtime-config`, and make `--dry-run` print the fragment; validate every
      route with the same validators and fail on an unknown key naming it.
- [x] 3.5 Document it: `docs/cli.md` (`--set`, `--runtime-config`, `--dry-run`, the order, the exit codes),
      `docs/agent-runtimes.md` ("adding an agent", the table's fields, the `verified` note, what the models question
      can and cannot know), `docs/init.md` where it describes init's order, and an entry under Unreleased in
      `CHANGELOG.md`.

## 4. [agent-build-kit] [unit-test] The policy step, `--policy-only` and `--policy-fix`; doctor shares the probe

Needs: acp-policy-covers-global-option-spellings group 1 merged — init prints what the richer policy check reports, so the check must exist first

Done when `abk init` runs the guided policy step, showing the fix and the unrefused classes before it runs and what is
refused afterwards per class and spelling; `abk init --policy-only` runs just that step on an existing installation
and exits 0, 1 or 2 as the design says; `--policy-fix` and `--run-policy-fix` supply or authorise the fix; and `abk
doctor` reports from the same probe — with the docs and the changelog updated.

Test fakes: a check that returns per-class, per-spelling results, a fix command that is a small real script (patches a
fake policy file, exits non-zero, or changes nothing) and a fake agent that records every prompt.

- [x] 4.1 Test: the policy step asks nothing when the check passes; for a check that prompts the agent it says so
      and asks first, and a refusal records the entry as unchecked; a known agent's fix is offered only when a class
      is unrefused, runs only on a yes and is followed by a second check; for an unknown agent the three choices are
      offered (rely on abk's protocol layer and say what it sees, supply a fix command validated as an existing
      executable, continue without) and none is guessed; a fix that leaves a class unrefused is reported as still
      unenforced, never as a pass.
- [x] 4.2 Test: with a faked check that refuses a class in its plain spelling and lets one spelling through, the policy
      step names that spelling before init finishes, and a known-agent table row says a spelling is covered only when
      its note records a live check that showed it (otherwise the note reads UNVERIFIED).
- [x] 4.3 Test: the fix command and the unrefused classes and spellings are printed before the fix runs; the fix's
      own output reaches the person (not captured); afterwards each class and spelling is printed as refused or not;
      a fix exiting non-zero is reported with its exit status and the check still runs again; a fix that exits 0 and
      leaves every spelling unrefused prints "the fix made no change; still not refused: <spellings>".
- [x] 4.4 Test: `abk init` on a kept `abk.yaml` with `runtime:` set asks no runtime question, reaches the policy step
      and applies the configured fix, with no write to the file.
- [x] 4.5 Test: `abk init --policy-only` detects no repo, runs no research or propose, makes no commit and changes the
      file only by a recorded fix or marker; it exits 0 when the check passes after the step, 1 when a class is
      still not refused or a token-spending check is declined, and 2 with no `abk.yaml`, an unknown runtime or an
      unusable flag, writing nothing.
- [x] 4.6 Test: `--policy-fix ARGV` is recorded as `policy_fix` after a confirmation (nothing written on a no), is
      refused with exit 2 when it is not an existing executable, and works with and without `--yes` and
      `--policy-only`; `--yes` with a configured fix and neither `--policy-fix` nor `--run-policy-fix` runs no fix,
      names the unrefused classes and exits 1, and with either flag runs it unasked; a token-spending check is asked
      about under `--policy-only` unless `--yes`.
- [x] 4.7 Test: `abk doctor` reports other usable runtimes as information from the probe, warns when the selected
      entry is documented only, and for an entry recorded as unchecked warns on every run and sends the agent no
      prompt.
- [x] 4.8 Move the policy check ahead of the write where the existing check can be pointed at the unwritten choice
      (else after it, recording a declined check as unchecked), add the guided step with the printing described in
      the design, the unchecked marker's effect on `abk doctor`, and the doctor lines from the shared probe.
- [x] 4.9 Add `--policy-only`, `--policy-fix ARGV` and `--run-policy-fix`, with the exit codes and the confirmation
      before a recorded value is written; share the step with the end of `cmd_init` so both reach one code path.
- [x] 4.10 Document it: `docs/cli.md` (`abk init --policy-only`, `--policy-fix`, `--run-policy-fix`, the exit codes,
      what `--yes` does and does not run), `docs/agent-runtimes.md` (an "applying a policy fix" paragraph: run
      `abk init --policy-only` on an existing installation, what the report shows, and that a fix applies only what its
      policy file lists, so a fix that changes nothing means the policy content is missing), the abk-pipeline and
      abk-config skills where they list init's flags, and an entry under Unreleased in `CHANGELOG.md`.

## 5. [agent-build-kit] [e2e-test] [acceptance] The real `abk init` against a stand-in agent


Needs: tier2-tests-are-tagged-by-runtime group 18 — parked until the live tests are tagged by runtime and the drift test guards them, so an ACP test that cannot run (the model backend is out of budget) is held instead of failing

Done when the real command, run as a subprocess against a scratch planning repo, has been seen to list candidates,
take a choice, show or withhold a model list, write a configuration that loads and passes `abk doctor`'s runtime
check, write nothing unconfirmed and refuse where it should, and apply a policy fix with `--policy-only` — with no
prompt reaching an agent but the policy check's own.

The stand-in is a small real subprocess speaking the protocol, placed first on the path under a known-agent program
name, that fails the test if it receives a prompt other than the policy check's in the `--policy-only` runs: nothing here makes
a model call or spends tokens. The run passes
`--skip-research --skip-propose` (those steps are model calls by design; group 2 proves they receive the chosen
runtime) and declines the policy check (a prompt for this runtime) in every run but the `--policy-only` ones. Needs node for the OpenSpec CLI, as the existing
end-to-end init test does. Tests live under `tests/integration/` with the repository's tier-2 marker, and the file
name carries the `_live_stack` suffix.

- [x] 5.1 Test: with the stand-in on the path and other known programs absent, the list shows the stand-in as
      usable and absent ones as unusable, each with its reason, usable first; picking the stand-in writes
      `runtime:` and its command; the written `abk.yaml` loads and `abk doctor`'s runtime check passes; the
      stand-in's record holds no prompt.
- [x] 5.2 Test: a stand-in that advertises models shows them with its current one as the default, and the choice
      lands under `models:`; a stand-in that advertises none says so and leaves the roles empty.
- [x] 5.3 Test: nothing is written before the confirmation (the scratch repo is unchanged when the run is answered
      no); `--yes` with several usable stand-ins exits 2 and writes nothing; with nothing installed it exits 2 and
      writes nothing.
- [x] 5.4 Test: against a stand-in that lets one spelling through, `abk init --policy-only` with a fix command that
      patches it shows the spelling not refused before and refused after and exits 0; with a fix that exits 0 and
      changes nothing it prints "the fix made no change; still not refused: <spelling>" and exits 1. The check's
      prompt is the one prompt the stand-in accepts in these runs.
- [x] 5.5 Test, skipped when no agent is installed on the host: listing against the installed agent sends no prompt,
      and reports a model list only if the agent advertises one.
- [x] 5.6 Write the stand-in and the scripted answers, reusing the existing protocol test agent where it can fail on
      a prompt and advertise or withhold models, and document how to run the acceptance run beside the existing
      tier-2 runs.
