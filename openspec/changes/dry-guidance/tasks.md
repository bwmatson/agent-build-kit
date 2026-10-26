# Tasks

Priority: 4

## 1. [agent-build-kit] [unit-test] The builders are told how to look and what to do

Needs: session-reuse group 4 merged — the continuation prompts, so the part is attached to the full prompt form only (merged)

Done when every builder prompt carries a language-neutral reuse part and the prompts for tests and rework add
their extra lines.

- [x] 1.1 Test: the prompts for writing tests, implementing, fixing checks, reworking after review, reworking
      after feedback each contain the reuse part, filling them in leaves it unchanged, and the adapt prompt does
      not contain it and keeps its instruction not to re-implement what the predecessor provides.
- [x] 1.2 Test: with session reuse on, the continuation prompts for implementing, fixing checks and reworking do
      not contain the part while the full prompt for writing tests does; a node that starts a new session (entering
      past the tests, a fallback, reuse off) gets it in its full prompt; the lines about feedback stay in the
      feedback and rework prompts in both forms.
- [x] 1.3 Test: the part tells the agent to search before adding, write shared logic once, give calls that must
      change together one function, use the shared test support, delete what its change makes dead and stay
      within the change, and how to look: neighbours' imports, shared-code modules, the test runner's support
      places, the language's or common conventions, and search by behaviour as well as name.
- [x] 1.4 Test: the part names no installation, language-specific tool or path, and the pipeline reads no
      repository section for it.
- [x] 1.5 Test: the rework prompt, the only one without it, adds "look for the others of the kind" (the
      review-feedback and checks prompts already say it and keep their wording), and the tests prompt points to
      the shared fixtures.
- [x] 1.6 Add the packaged part and its loader, append it to the full form of each of the five prompts only, and add the extra lines to the rework and tests prompts.
- [x] 1.7 Document the part in `docs/architecture.md` and add a changelog entry.

## 2. [agent-build-kit] [unit-test] The reviewer looks for prior art and blocks on introduced duplicates

Needs: pr-description-says-why group 2 merged — both edit the review prompt, so the hunks must not collide

Done when the review prompt searches for prior art and treats a duplicate the change introduces as required,
and says nothing about pre-existing duplication.

- [x] 2.1 Test: the review prompt asks, for each new function, constant, pattern or test helper in the diff,
      for a search for an existing equivalent and a second copy in the diff, and for the existing one to be
      named by file and line.
- [x] 2.2 Test: the prompt says a duplicate the change introduces or makes worse is a required finding with the
      stated consequence and what done looks like, that parallel-call-site pairs and per-variant copies are the
      common cases, and that this satisfies the rule that a required finding names its consequence.
- [x] 2.3 Test: the prompt gives no instruction to report duplication the change neither adds to nor extends,
      and keeps the split between small local and design-level refactors.
- [x] 2.4 Add the step and the rule to the review prompt after the interfaces rule.
- [x] 2.5 Document the review rule in `docs/architecture.md` and add a changelog entry.

## 3. [agent-build-kit] [unit-test] Writing tests first does not pin a function that already exists

Done when the tests step decides, after searching, whether to reuse, generalize or create before it stubs a named
function; the implementing step may repoint a test whose stub duplicates existing code; the reviewer counts a
stub the tests commit added; and the authoring skill tells authors to describe behaviour and name only contracts.

- [x] 3.1 Test: the prompt for writing tests, beside its sentence allowing stubs, tells the agent that when a task
      names code to add, or the logic is needed in a second place, it first searches for an existing equivalent
      and decides which of three cases it is: (a) an existing function does the job, so it tests through it, adds
      no stub and reports "reused X instead of adding Y" in its summary; (b) an existing function nearly does it,
      so the tests target that function's missing behaviour and no new name is created; (c) no reusable helper
      exists and two places need the logic, so one stub at the shared place covers the helper's own interface, the
      tests cover each call site, and no second copy is stubbed per call site. It also tells the agent to prefer
      the nearest existing entry point to an internal helper's name, and that a name which is a contract is
      stubbed as named.
- [x] 3.2 Test: the prompt for writing tests says new tests go in test files whose every test fails before the
      implementation, so a failing test is not added to a file that holds passing ones, and that a test written
      for a conversion with no new behaviour observes the call site reaching the shared or existing function.
- [x] 3.3 Test: the prompt for implementing in its full form and the implementation continuation each carry one
      added line saying that a stub the tests added which duplicates existing code is deleted and the test
      repointed at the existing function with the same assertions, that this is not weakening a test, and that
      the summary says so; both keep their sentence "Do not weaken or delete a test to make it pass"; the
      continuation still fills in with its changelog placeholder and the line adds no braces; no other
      continuation prompt carries the line, and the reuse part is still not repeated in any continuation.
- [x] 3.4 Test: the review prompt, in the step group 2 adds, says a stub or helper added by the tests commit
      counts as added by the change, and that a test repointed at an existing function with unchanged assertions
      is not a finding.
- [x] 3.5 Test: the packaged text of the authoring skill says a task describes behaviour and names a new
      function, class or constant only when the name is a contract, shows a good and a bad example in no
      particular language, and names no installation.
- [x] 3.6 Add the paragraph to the tests prompt, the line to the implementing prompt and the implementation
      continuation, and the clause to the review prompt.
- [x] 3.7 Add the section to the authoring skill; document the three cases, the repointing line and the red-check
      handling in `docs/architecture.md`; add a changelog entry that says copies of the authoring skill in
      planning repositories stay as they were until `abk install-skills` is run.

## 4. [agent-build-kit] [e2e-test] [acceptance] A real agent reuses, generalizes and shares as the prompts ask, and the reviewer blocks a duplicate, on Claude Code


Needs: tier2-tests-are-tagged-by-runtime group 18 — parked until the live tests are tagged by runtime and the drift test guards them, so an ACP test that cannot run (the model backend is out of budget) is held instead of failing
Split: claude_code

Done when a green run shows, with a real agent and no judgement by a model in any assertion: (a) given a task that
names a helper an existing function already covers, the agent's branch holds no second definition of that logic
and the new code calls the existing function; (b) given a task for a variant of an existing function, the
existing function is extended and no new function carries its logic; (c) given logic needed at two call sites
with no helper, the branch adds exactly one definition of it and both call sites call it; (d) the prompts the
agent was sent held the reuse part and the three-way instruction (tests step), the repointing line (implementing
step) and the prior-art clause (review); (e) a review of a branch seeded with a duplicate returns a required finding
naming the existing function, and a review of a clean branch returns none naming it. A red run says which of
three things failed, as design.md sets out, and no assertion is loosened to turn it green. This group runs on
Claude Code. Cases (a), (b), (c) and (e) read the branch and the reviewer's findings, which do not depend on the
runtime, and live here only; (d) reads the wire the prompts travel on, so its Claude form is here and its ACP form
is group 5.

- [x] 4.1 Test: `tests/test_dry_checks.py` (unmarked) pins the assertion helper's own behaviour on hand-written
      sources, so a wrong helper fails here and not in a billed run: a copy with renamed locals and constants
      counts as a duplicate of the original; a function that only calls the original does not; a call is found
      by name whether written `f(x)` or `module.f(x)` and a mention in a string or a comment is not a call; the
      definitions a diff adds are those of two git trees that differ, and a definition whose body changed is
      reported as changed, not added; the occurrences of a key literal across a tree are counted; the Claude
      parser of 4.6 returns, from a hand-written recording of two runs (one starting a session, one with
      `--resume <id>`), each run's text in order with its resume id, and nothing for a run with no stdin. It fails
      before 4.6.
- [x] 4.2 Test: `tests/test_dry_scratch.py` (unmarked, integration-gated like `test_scratch_app_unit_test.py`: skipped
      without `uv`) asserts that the dry scratch app's own tests pass under the profile's tier-1 commands, that
      `git status --porcelain --untracked-files=all` is empty afterwards while `uv.lock` exists, that the seeded
      branches build (each holds the commits 4.6 describes and passes unit-test), and that the recording agent
      wrapper passes lines both ways unchanged and records only what the client sent, and that the Claude
      wrapper, set as `runtimes.claude_code.command` and run over a stub `claude` that echoes its arguments and
      standard input, records the standard input and the arguments of each run, passes both on to `claude`
      unchanged and leaves no process of its own once `claude` runs (it `exec`s). It fails before 4.6.
- [x] 4.3 Test: `tests/integration/test_dry_guidance_build.py`, marked `local_stack`, skipped without `npx` or
      `uv`, its runtime chosen by `CLAUDE_CODE_PARAMS` and `runtime_scratch("claude_code", ...)` as
      `tests/integration/test_graph_unit.py` does, so the module is tagged `runtime_claude_code`, carries no
      `runtime_acp` mark and never `RUNTIME_PARAMS` (a test may carry one runtime tag), and no longer reads
      `<redacted>`. One module-scoped fixture per case builds the case's scratch app and planning repo, ticks once with
      `max_review_rounds` 1 and a tick timeout under the tier-2 limit, and keeps the branch. Case (a), a test per
      claim: the branch diff against `main` adds no function whose normalised body matches the existing helper's
      and the key literal of its logic occurs once in `src/`; the function the task names calls the existing
      helper by name. Case (b): the existing function's source differs from `main`'s (a changed signature or a
      new branch); the key literal occurs once in `src/`; no added function matches its body; the new entry
      point the task names, if the branch has one, calls it; the old tests of the function still pass in the
      branch. Case (c): the added functions in `src/` are the two the task names and exactly one other; the
      logic's key literal occurs once in `src/`; both named functions call that one. Each failure message
      carries the diff, the added definitions the helper found and the tail of the agent's transcript.
- [x] 4.4 Test: in the same file, one test reads the prompts recorded from case (a)'s run, through the Claude
      wrapper and parser of 4.6, and asserts the
      prompt of the tests step contains the reuse part exactly as `reuse_guidance()` returns it and the stems of
      the three-way instruction group 3 pinned ((a), (b), (c), "reused", "instead of adding"), the prompt that
      carries "Do not weaken or delete a test to make it pass" contains the repointing line (a full prompt or the
      continuation, whichever the session reuse setting sent), and no continuation prompt contains the reuse
      part. It uses the run of 4.3 and starts no agent of its own. A run that continues the unit's session is a
      continuation prompt, and one that starts a session is a full one; the wrapper's recorded arguments tell
      them apart.
- [x] 4.5 Test: `tests/integration/test_dry_guidance_review.py`, marked as 4.3. A seeded duplicate: the scratch
      app gets a local branch `spec/<change>/1` holding a tests commit and an implementation commit that
      re-implements the existing helper under a new name, a tick enters the unit at its checks and review (it
      has commits and no approval), and the review's findings, read from the unit's thread, include a required
      finding whose text names the existing function or its file. A clean branch: the same shape with an
      implementation that calls the existing helper, and no required finding names the existing function or
      its file. The review prompt recorded in either run (through the Claude wrapper and parser) contains the prior-art
      clause group 2 pinned.
- [x] 4.6 Add the fixtures and the helper. `tests/dry_scratch.py`: `dry_app(path)`, built on `scratch_app`, adds
      one helper with a distinctive body and its tests (`slugify` in `src/app/text.py`, a regex that squeezes
      every run of non-alphanumerics into one hyphen), commits them on `main` and keeps `uv.lock` ignored;
      `CASES`, the task text of each case; `dry_planning`, the planning repo with `max_review_rounds: 1` and
      the agent command wrapped by the recorder of the runtime under test, written under that runtime's
      `runtimes.<name>.command` (`ticked_case` takes the runtime as a parameter, so group 5 passes `"acp"`);
      and the two seeded branches. `tests/claude_recorder.py`: a shell wrapper, set as
      `runtimes.claude_code.command`, that appends a header line with its arguments to a file, tees its standard
      input to the same file, and `exec`s `claude "$@"`, so it records the prompt of a `-p` run and of a
      `--resume <id>` run and leaves no process of its own (the process arguments are Claude's, with the session
      id, so `claude_holders` in `serve/chat.py` is not confused). `tests/acp_recorder.py` and the ACP parser
      stay as they are, for group 5: a script that starts the real agent command, forwards both directions
      unchanged and appends each line the client sends to a file. `tests/dry_checks.py`: the structural helper (test code, not framework code, so it may
      be Python-specific): parses sources with `ast`, lists the definitions of a tree and of a diff, normalises
      a body (names, constants and docstrings replaced by their kind, then a sequence ratio against a
      threshold fixed by the two controls of 4.1), resolves calls by name, counts a key literal, and extracts
      the prompts from a recorded session: the existing ACP `session_prompts`, and `claude_session_prompts`,
      which splits a Claude recording into runs at the header lines and returns each run's text with its
      resume id. UNVERIFIED offline: the shape of the standard input of a `-p` run (plain text is assumed); the
      first recorded run settles it and the parser is fixed to match, a fix to test code.
- [x] 4.7 Run each new test once with the configured agent (`uv run pytest -m local_stack
      tests/integration/test_dry_guidance_build.py tests/integration/test_dry_guidance_review.py`), report per
      case what the run showed and, for a red one, which of the three causes in design.md it was. Do not weaken
      an assertion to pass; a change to the fixture or the helper is a fix to test code and says why.
- [x] 4.8 Update the test markers paragraph in `docs/agent-runtimes.md`: these tests are `local_stack`, tagged
      `runtime_claude_code` (the ACP form is group 5), need a Claude Code account, bill per token, take minutes each, run once per case, and are held to the
      tier-2 time limit; and add a changelog entry.

## 5. [agent-build-kit] [e2e-test] [acceptance] The prompts reach a real ACP agent, as the Claude Code group's do


Needs: dry-guidance group 4 — the scratch app, the case fixtures, the structural helper and the recorders are group 4's, and this group runs the prompt checks again with the ACP runtime
Split: acp

Done when, with a real ACP agent, the prompts the agent was sent held the reuse part and the three-way
instruction (tests step), the repointing line (implementing step) and the prior-art clause (review), as group 4
shows for Claude Code; the ACP split stays held until the backend has budget, and nothing in group 4 changes.

- [ ] 5.1 Test: `tests/integration/test_dry_guidance_prompts_acp.py`, marked `local_stack` and `runtime_acp`
      (through the ACP parameter of `RUNTIME_PARAMS`, no Claude Code mark), skipped without `npx` or `uv` and
      failing (not skipping) when `<redacted>` names no agent, as `test_graph_acp_unit.py` does.
      One module-scoped fixture ticks case (a) once with `ticked_case("acp", ...)` under the line-forwarding ACP
      recorder, and three tests read `session_prompts` of that run with the assertions of 4.4: the tests step's
      prompt holds the reuse part exactly as `reuse_guidance()` returns it and the stems of the three-way
      instruction, the prompt carrying "Do not weaken or delete a test to make it pass" holds the repointing
      line, and no continuation prompt holds the reuse part. The structural assertions of (a) are not repeated.
- [ ] 5.2 Test: in the same file, the seeded duplicate of 4.5 is ticked once under the ACP recorder and the review
      prompt recorded holds the prior-art clause group 2 pinned. The findings are not asserted again.
- [ ] 5.3 Run each test once with the configured agent (`uv run pytest -m local_stack
      tests/integration/test_dry_guidance_prompts_acp.py`), report what the run showed and, for a red one, which
      of the first two causes in design.md it was (the prompt was not delivered, or the recording's shape was
      not what `session_prompts` reads); do not weaken an assertion to pass. Two agent runs in all: a build and a
      review.
- [ ] 5.4 Update the test markers paragraph in `docs/agent-runtimes.md` (this module is in the held `acp`
      split, needs `<redacted>`, runs one build and one review) and add a changelog entry.
