# Design

## One part for every builder

A packaged part, a dozen lines, is appended to the prompts for writing tests, implementing, fixing checks,
reworking after review and reworking after feedback. The prompt for adapting to a changed predecessor is not
changed: it has a specific role, and its existing instruction not to re-implement what the predecessor provides is
enough. The part is appended as text, as
the output convention is, so no placeholder has to be threaded through the places the prompts are filled in. It
names no installation, language, tool or path.

It says:
1. Search before adding. Before writing a helper, constant, pattern, fixture or test helper, look for an
   existing one and use or extend it.
2. Write shared logic once. If the same logic is needed in two places, including two variants such as two hosts,
   backends or runtimes, put it in one function; derive a value from one source rather than computing or
   recording it twice.
3. Give calls that must change together one function.
4. Use the shared test support. A test helper needed in a second file moves to the shared place instead of being
   copied.
5. Follow the neighbouring idiom, delete what the change makes dead, and do not leave an old way beside a new
   one.
6. Stay in scope. Remove the duplication the change would introduce or touches; do not rewrite unrelated code;
   say in the summary when reuse needs a larger refactor so it can be recorded.

## Session reuse: the full prompt only

When a role's session is reused, a node that continues it is sent a continuation prompt with only what is new, and
the initial context is not repeated; a node that starts a session gets the full prompt. The reuse part is initial
context, so it belongs to the full prompt of each node and is not repeated in a continuation prompt. In a reused
build session it therefore appears once, in the prompt that writes the tests, which always starts the session, and
again only when a node starts a new session: a unit that enters past the tests, a fallback after a session could not
be continued, or reuse switched off, where every prompt is a full one. The lines that are about the feedback in
hand, to look for the others of the kind, are new each time and stay in the feedback and rework prompts in both
forms. The review prompt is always a full prompt, since a review never continues a session, so the reviewer's
prior-art step appears in every review.

## How to look, without configuration

The part tells the agent how to find where a repository keeps what is reusable, so it needs nothing from the
repository: read what the neighbouring code imports; look for the directories and modules named for shared code
(`utils`, `common`, `shared`, `lib`, `helpers`, `core`, `internal`, a package's exported names) and for the test
runner's usual places for fixtures and test support; use the language's own conventions, and where the language is
unfamiliar fall back on common ones: a shared module beside the callers and test support in one place. Search by
the behaviour of what is about to be written, such as its key literal, pattern or call, as well as by name,
because an existing helper rarely has the name the agent would give it. Where the repository itself documents
where things live, follow it; nothing in the pipeline looks for, injects or drafts such a document.

## Extra lines

The prompt for acting on review feedback and the one for fixing checks already tell the agent to look for others of
the same kind, and keep their wording. Only the prompt for reworking lacks it, so it adds that when feedback names
one duplicate the agent looks for the others of the kind. The prompt for writing tests points to the shared
fixtures before new ones are written.

## The reviewer

After the rule about shallow interfaces, the review prompt asks, for each new function, constant, pattern or test
helper in the diff, for a search for an existing equivalent and for a second copy within the diff, and for the
existing one to be named by file and line. Only duplication the change introduces or makes worse is in scope: a
new copy of something that exists, a third copy, a fixture copied from another test file, or extending a
duplicated block when the change touches it anyway.

Such a duplicate is a required finding. The rule that a required finding must name a consequence is satisfied
by a stated one: two copies that must change together, so the next change updates one. The prompt says so. What
done looks like is to use or extend the existing one, or to extract one shared function.

A duplicate that was already there, which the change neither adds to nor extends, is not reported at all, not
even as an optional follow-up. It is for a cleanup specification, not for this pull request. The rule about shallow
interfaces keeps its split between required fixes that are small and local and optional ones that are design
decisions.

## Not here

The recommendation documents that `abk init` writes are about tools, and do not reach the agents that build and
review, so they do not change. A mechanical check for duplicated code in unit-test is a possible later item for those
documents, for every language they cover. Cleaning up the duplication that exists is `dry-cleanup`.

## Tests first must not pin a duplicate

Group 1 tells a builder to search before adding a helper it chooses to add. It does not cover a function the task
text names and tells the agent to stub and test, and many task lists do. The prompt for writing tests allows exactly
that: "You may add stubs for code that does not exist yet — a signature whose body is only `raise NotImplementedError`,
or a model field — so the tests fail when they run instead of failing to import." A stub added there fixes a new name
before anyone has looked for an existing equivalent. The implementing prompt and its continuation then say "Do not
weaken or delete a test to make it pass", so the step that finds the duplicate cannot swap the tested name for the
existing function without breaking that rule. The reviewer of group 2 sees the duplicate only after tests and code
are built around it.

### A three-way decision before anything is stubbed

When a task names code to add, or the same logic is needed in a second place, the agent searches for an existing
equivalent (by the rules of group 1) and decides which case it is before it writes tests:

- **(a) An existing function already does the job.** The tests go through it, no stub is added, and the summary says
  "reused X instead of adding Y".
- **(b) An existing function nearly does it and needs generalizing** for a new case, parameter or backend. The tests
  target the existing function's missing behaviour. They fail for the right reason, so the red step holds, and no
  new name exists. The implementing step extends the function; the existing tests of its old behaviour are the
  safety net and are not edited.
- **(c) No reusable helper exists and two places need the logic.** Creating one is correct. The tests cover the
  helper at its own interface, where a stub is allowed because the helper does not exist, and each call site's
  behaviour. The helper goes where the repository already keeps shared code, found by the rules of "How to look,
  without configuration". The stub is the single definition, and both call sites are converted to it with their
  existing tests as the safety net. No second copy is stubbed per call site.

The agent prefers asserting behaviour at the nearest existing entry point to asserting on a new internal helper's
name. A name that is a contract is tested as named: public API, a command, a wire shape, or a name the specification
requires.

This is added to the prompt for writing tests next to its stub sentence. That prompt always starts a session and has
no continuation form, so it is a full prompt, like every place the reuse part sits. Rewriting the task lists that
already name functions is out of scope: their text still names them, and the new paragraph makes the agent search
first. New specifications follow the authoring note below.

### Implementing may repoint a test

When the tests step could not know, or decided wrongly, a stub may duplicate existing code. The implementing step
then deletes the stub and repoints the test at the existing function. This is not weakening a test when it keeps the
same assertions, covers the same behaviour and changes only the target, and the summary says it was done. Changing an
assertion, loosening it, deleting the test or covering less still is weakening, and "Do not weaken or delete a test to
make it pass" stays as it is.

The line is one sentence without braces, added after that sentence in `IMPLEMENTATION_PROMPT` and in
`IMPLEMENTATION_CONTINUATION`, before the read-only note and the changelog placeholder, which the continuation fills in
with `format`. It is the stated exception to "the reuse part is not repeated in a continuation": the reuse part is
initial context a session already holds, while this line is about the tests commit the step is now looking at, which
is new information, like the lines about feedback in hand. The implementing step enters with a full prompt when
session reuse is off, when it enters past the tests or after a fallback, so the full prompt carries the line too; the
other continuation prompts, which do not contain the "do not weaken" sentence, do not.

### Red check: what the code settles

`red_check.py` and the gate decide the following, read from the code:

- A tests commit must add or change at least one test file (`check_structure`: a first commit without tests is
  rejected, and a branch of only code has no tests commit). The red run then executes whole files, only the test
  files that commit touched (`red_command(files)`, `_test_files_in`).
- Every collected test in those files must fail. In `red_check` and in the console fallback `interpret_red` alike, any
  passing test is a problem ("a test that passes before its implementation exists is not testing that
  implementation"), and so is a run where nothing failed or nothing was collected. A failure counts only if it is an
  assertion, `NotImplementedError`, or a missing module or attribute raised in a test body or at setup; a syntax
  error or a collection failure is not red.
- There is no waiver. Nothing in the task syntax, the pipeline or the profile marks a group as characterization or
  skips the red run, and this change adds none.

What follows for the three cases:

- Case (b), and the helper-interface tests of (c), fail naturally. For (c) the stub raises `NotImplementedError`, so
  the stub rule still holds: a stub contains no logic.
- Existing tests that already pass are untouched and not run red, because only files the tests commit touched run.
  The agent therefore puts new tests in a new test file, or a file in which every test fails, and does not add a
  failing test to a file that holds passing ones: the whole file runs and its passing tests reject the commit. The
  prompt says so.
- A conversion that adds no behaviour, case (a) at a second call site or a pure refactor of (c), has no honest failing
  behaviour test. The test written then observes the route: with the shared or existing function replaced by a probe,
  the call site is shown to reach it, which fails before the conversion. For (c) the helper's interface test fails
  anyway. If no such test can be written, the code settles that the tests commit is rejected and that nothing marks
  the group as exempt; the tests step reports it in its summary and the group is authored as a refactor with a
  behaviour test, not as a bare conversion.
- UNVERIFIED: what the pipeline does after the gate rejects a tests commit (retry of the tests step, hold, or human)
  was not read for this change, and the node profile has no red command yet (`interpret_red` is a placeholder), so
  this section describes the Python profile only.

### The reviewer

Group 2's step asks, for each new function, constant, pattern or test helper in the diff, for a search for an existing
equivalent. This group adds one clause: a stub or helper added by the tests commit is part of the diff and counts, and
the reviewer names the existing function if there is one. A test repointed at an existing function with unchanged
assertions is the intended outcome, not a finding, and not a weakened test.

### Authoring guidance

A task describes behaviour. It names a new function, class or constant only when the name is a contract: public
API, a command, a wire shape, or a name another change or repository depends on. Otherwise "add a helper that does
X" is replaced by what must be true, so the tests step is not handed a name to pin. The authoring skill that ships
with the framework gains a short section, with a good and a bad example in no particular language. Copies of the
skill in a planning repository are written by `abk install-skills`, so they stay as they were until it is run again:
the changelog entry says so, and no copy is edited by this change.

## Proving the guidance with a real agent

Groups 1 to 3 are proven by tests of the prompt text: which prompts carry which words. That a prompt says "search
first" does not show an agent that reads it searches first. Group 4 is the acceptance group: a real agent, the one
`<redacted>` names (supplied through `verify.env` in the planning repo's `abk.yaml`, as for the
existing acceptance tests), builds and reviews small units in a scratch app that tempts duplication, and the
tests look at what it wrote. It follows groups 1 to 3 in the build order, so it is written against the prompts as
they merged. It depends on two merged changes, checked in the framework's history: `scratch-app-ignores-its-lock`
group 1 (commit "The scratch app's worktree stays clean under its own tier-1 commands", #189), without which the
unit's worktree holds an untracked lock after its first tier-1 run and the second step is held; and
`tier2-tests-have-their-own-time-limit` (#178), which gives a `local_stack` test thirty minutes instead of sixty
seconds. The first carries a `Needs:` line; the second needs none because it is merged and nothing in flight
reshapes it.

### The scratch app

A dedicated app, `dry_app`, built on the shared `scratch_app` and not an extension of it: the shared fixture is used
by other tests, and a helper with a distinctive body and its tests would change their diffs. `dry_app` calls
`scratch_app`, so it inherits the ignore rules that keep the worktree clean, then commits one helper on `main`:
`slugify` in `src/app/text.py`, a regex that squeezes every run of non-alphanumeric characters into one hyphen,
with its tests. The body is distinct and checkable: its key literal (the character class) appears once in the
tree, and any second copy of the logic contains it or a normalised match of the body. Each case gets its own
planning repo and its own copy of the app, so no case sees another's work, and each is a single group with an
`Acceptance: none` line, as `test_graph_acp_unit.py` does. The tasks the cases hand the agent are written the way
group 3's authoring note says not to write them (they name an internal helper) because that is the temptation
under test.

| Case | The task asks for | The guidance should lead to |
|---|---|---|
| (a) reuse | `page_path(title)`, built with a new `title_slug(title)` helper that squeezes the title into a slug | the tests go through `slugify`; `page_path` calls it; no second definition of the squeeze |
| (b) generalize | `file_stem(title)`: the same slug with underscores | `slugify` extended (a parameter or a branch); no new function carrying the squeeze |
| (c) shared helper | `invoice_label(prefix, number)` in one module and `receipt_label(prefix, number)` in another, both upper-casing the prefix and zero-padding the number to four digits, no such helper existing | exactly one new definition of that formatting; both functions call it |

### What is asserted, and how

Every assertion is structural and decided by code, never by a model's reading. The helper, `tests/dry_checks.py`,
is test code in the fixture and not framework code, so it may be specific to the scratch app's language, Python:

- It parses the sources of two git trees (`main` and the branch, read from the bare remote) with `ast` and lists the
  definitions each holds. A definition the branch adds is one absent from `main`; one whose normalised source
  differs is changed, not added.
- A body is normalised by replacing names, constants and docstrings by their kind, and two bodies are a duplicate
  when the ratio of their token sequences passes a threshold. The threshold is fixed by two hand-written controls
  in a tier-1 test (4.1) before any agent runs: a copy with renamed locals is a duplicate, and a function that
  only calls the original is not. The key literal check is a second, independent signal: the count of its
  occurrences across `src/`.
- A call is resolved by name, syntactically: a call node whose callee is the name, or an attribute with that name.
  A mention in a string or comment is not a call. It does not follow imports or aliases; that suffices for a
  scratch app of a few modules, and an assertion that an alias defeats is a reason to change the fixture.
- Case (a) asserts the branch adds no function matching `slugify`'s body, the literal occurs once in `src/`, and
  `page_path` calls `slugify`. Case (b) asserts `slugify`'s source changed, the literal occurs once, no added
  function matches its body, and its old tests still pass. Case (c) asserts the added `src/` definitions are the
  two named functions and exactly one other, the formatting literal occurs once, and both named functions call that
  one. A wrapper that only delegates is not a copy of logic, so `title_slug = slugify`-style indirection passes (a).

### Prompt delivery, deterministic and cheap

The transcripts and run logs record what the agent said and did, not the prompt it was sent: a build step's
transcript has no user event. The tests therefore record the prompts themselves. The fixture wraps the agent
command in a small script (`tests/acp_recorder.py`) that starts the real agent, forwards both directions unchanged,
and appends each line the client sends to a file. The prompt of each step is the text of its `session/prompt`
request. Case (a)'s run is the one examined, so this costs no run of its own (4.4): the tests step's prompt contains
the reuse part exactly as `reuse_guidance()` returns it and the stems of group 3's three-way instruction; the
prompt that carries "Do not weaken or delete a test to make it pass" contains the repointing line, whether the
session reuse setting made it a full prompt or the continuation; and no continuation contains the reuse part.
Stems, not whole sentences, are matched for the wording that groups 2 and 3 fix in prose, and the builder of this
group reads the merged text to choose them; if the wording later changes, the stems change in the same change.
The shape of the request (UNVERIFIED offline: the prompt is assumed to be text blocks in the request's `prompt`
parameter) is settled by the first recorded run, and the extractor fixed to match; that is a fix to test code.
The review prompt recorded in the review runs is checked for group 2's prior-art clause the same way.

### The reviewer, with a seeded duplicate

Two ways to get a duplicate in front of the reviewer, one deterministic and one not. A task that insists on a copy
puts the builder, which the prompts now tell not to, in a contest with its instructions, so whether a duplicate
arrives is the builder's choice and the test would measure the builder. A prepared branch fixes the diff: the
scratch app gets a local branch named for the unit (`spec/<change>/1`) holding a tests commit and an
implementation commit that re-implements `slugify` under a new name. A worktree is prepared on an existing local
branch of that name, and a unit with commits and no approval enters at its checks and then the review, so the
build agent never runs and the only agent call that matters is the reviewer's. This was read from the code of the
worktree step and of the path after preparing; the first run confirms it. `max_review_rounds` is set to 1 in the
scratch `abk.yaml`: the last round's review is then the verdict, no rework is asked for, and a review costs one
call. The test reads the review's findings from the unit's thread (`last_findings`, kept after the review) and
asserts that one is required and its file or summary names `slugify` or `text.py`. The clean branch holds the
same shape with an implementation that calls `slugify`; the test asserts no required finding names `slugify` or
`text.py`. It does not assert that the reviewer raised nothing at all: an unrelated required finding about the
scratch code would be a flake for reasons that have nothing to do with duplication, and is reported by the
failure message instead.

### Flake risk, and telling a failure apart

Every assertion that depends on a real agent can fail without the guidance being broken, because the agent is
not deterministic. The risk, case by case:

- (a) moderate. The agent may write a thin wrapper, which passes, or a differently shaped copy that evades the
  threshold but not the literal check; it may also ignore the guidance and copy, which is the failure the test
  is for.
- (b) moderate to high. Generalizing can be done by a parameter, a branch or a second function that calls the
  first; the first two are asserted and the last is a pass only if the logic is not copied. An agent that adds
  the variant by wrapping the output (`slugify(...).replace("-", "_")`) copies no logic and passes the literal
  check, and the "slugify's source changed" assertion then fails although nothing is duplicated; this is the
  likeliest assertion to be too strict, and the first run decides whether it stays as written or becomes "the
  squeeze is defined once and the variant reaches it", which is still structural.
- (c) moderate. The agent may make one of the two functions the helper and have the other call it, which
  duplicates nothing and fails the "exactly one other definition" assertion. The guidance asks for a shared
  helper, so the assertion is as written; if the first runs show this shape, the decision about whether it is a
  pass is made once, in the open, and not by loosening a single run.
- (d) low. The text sent is fixed by the framework; the only variance is in the recorder and in what step
  receives what, which the framework decides, not the agent.
- (e) moderate for the seeded duplicate (the reviewer may find it and still not call it required, or name the
  function in a form the check does not see) and moderate for the clean branch (the reviewer may raise a
  required finding naming `slugify` for a reason other than duplication).

A red run is one of three things, and the failure message and the artefacts tell them apart in this order.
First, **the prompt was not delivered**: the (d) assertions fail, the recorded prompt lacks the part or the line.
That is a framework or fixture fault and the builder's run is not evidence about the guidance. Second, **the
agent ignored it**: (d) passes, the prompt held the guidance, and the structural assertion fails with the diff
showing a copy (or a wrongly placed helper). That is the finding the group exists to produce; it is reported with
the transcript and the guidance is what changes. Third, **the assertion was too strict**: (d) passes, the diff
shows no duplicated logic, and the check still failed. That is a fault in the helper or the case, fixed in the
test code with a control case added to 4.1, and the fix says why. The failure message carries the diff, the
definitions the helper counted as added, and the tail of the agent's transcript so the three can be told apart
without rerunning.

### Cost, and what the group must not do

A real agent bills per token and a case takes minutes. Three build cases, the prompts check which shares case
(a)'s run, and two reviews are five agent runs; each is run once, with no retry loop in the test and no
parametrization that multiplies them. A tick has its own timeout (twenty-five minutes) below the tier-2 limit of
thirty minutes per test phase, so a stuck agent fails the tick with the unit's log and not as a bare limit; the
module-scoped fixture that ticks a case runs in the setup of its first test and so is held to the same limit. The
existing acceptance tests give their ticks an hour, which exceeds the limit and means the plugin fires first;
these do not repeat that.

The group must not weaken an assertion to make a run pass. A red run is reported with its cause; a fix is made to
the fixture, the helper or a case, with a control added, or to the guidance in a change of its own. Asserting less
about the same output, widening a threshold until the failing diff passes, or skipping a case after it failed is
refused.
