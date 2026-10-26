# Design

## What was checked, and what was not

Read-only in the agent-build-kit checkout at `main` (258f522). Paths under `src/agent_build_kit/`.

- **VERIFIED, `pipeline/command_policy.py`.** `_is_git(tokens, *subcommand)` is true only when `tokens[0] == "git"` and
  `tokens[1 : 1 + len(subcommand)] == subcommand` (lines 86-91). `_check_segment` calls it for amend, `amend`, hard reset,
  clean, branch force-delete and push, after `_strip_wrappers`. `_check_push` reads `tokens[2:]` as the push's arguments, so
  a global option shifts it too. `_skips_commit_hooks` and `_git_target` each already skip `-C <dir>` and `-c k=v` with
  their own loop (and treat any other dash word as one token), so the same job is written three times and only two of them
  do it.
- **VERIFIED by running `check_command` on each spelling** (branch `spec/x/1`): allowed, that is, not refused, are
  `git -C /w commit --amend --no-edit`, `git -c k=v commit --amend`, `git --no-pager commit --amend`,
  `git --git-dir=/w/.git commit --amend`, `git --work-tree=/w commit --amend`, the combination
  `git -C /w -c k=v --no-pager commit --amend --no-edit`, the two-token `git --git-dir /w/.git commit --amend`,
  `git -C /w push origin main`, `git --no-pager push origin HEAD:main`, `git -C /w push --force origin +main`,
  `git -C /w reset --hard`, `git -C /w branch -D x`, `gh -R o/r pr merge 5`, `gh --repo o/r pr merge 5`,
  `gh api -X PUT repos/o/r/pulls/5/merge`, and `sudo git -C /w commit --amend`. Refused as they should be: the plain
  spellings, `env GH_TOKEN=x gh pr merge 5`, `command git commit --amend`. A directory-change prefix (`cd X; git -C /w
  commit --amend`) splits into segments, so it is judged on its last segment and is allowed for the same reason.
  The hole is wider than the amend: it covers every rule built on `_is_git`.
- **VERIFIED, `forges/`.** `forges.denies(tokens)` matches a forge's `denied_commands` as a prefix of the tokens
  (`tokens[: len(denied)] == denied`); the GitHub forge's is `("gh", "pr", "merge")` and no other, so a repository option
  before `pr` and a raw API call both miss it. Another forge's raw escapes are already denied whole as prefixes.
- **VERIFIED, `runtimes/acp.py`.** `PROBE_CLASSES` is nine `(command, label)` pairs, one plain spelling each (`git commit
  --amend -m probe` and `git push origin main` among them). `_probe_prompt` names every command in one inline code span of
  one prompt; `_ProbeTracking.note_refused(line)` adds a line to `refused` only when it equals a probed command exactly;
  `_probe` builds one session and one request and returns `PolicyReport(ok, unenforced)` with a label per class never
  refused. `tests/runtimes/test_acp_probe.py` holds the list to `check_command`.
- **VERIFIED, `runtimes/policy_check.py`.** The answer is cached per runtime in `<state_dir>/policy-check.json` and reused
  for `MAX_AGE` (15 minutes); `PolicyReport` is stored as its JSON dump, so a field added with a default loads from an
  older file.
- **VERIFIED, `docs/agent-runtimes.md` (the policy section).** A class passes only when the attempt reached abk and was
  refused there; "never attempted, run without asking, allowed by the rules or cut off" are all reported unenforced.
- **From the research (a matcher run offline against the agent's own deny list, no model call), not re-run here.** Every
  git global-option spelling gets past the agent's amend, push-to-`main`, push-to-`master`, `HEAD:main` and force-push
  denies; `gh -R/--repo ... pr merge` gets past; `gh api ... merge` and a local `git merge` are not on the agent's list at
  all; `env X=1`, `command` and `sudo` prefixes are refused. The table below copies those cases.
- **UNVERIFIED, for the builder to confirm and correct here:** which other git global options exist in the pinned git
  versions beyond the short list in section 1 (the builder reads `git --help` on this machine and adds those that take a
  value to the table); whether `gh`'s repository option is accepted before the subcommand by every version abk supports
  (the research shows it as a spelling that runs, which is why it is in the table); whether wrapper options that take a
  value (`sudo -u root git ...`, `env -u X git ...`, `timeout -s KILL 5 git ...`) are read correctly by `_strip_wrappers`,
  which drops a wrapper's dash words but not their value (the first row of the wrapper block below tests it, and the
  builder fixes the stripping if it fails); where the doctor prints a finding and how init prints it (`cli/doctor.py`,
  `cli/init.py` were not read); and whether an agent attempts a prompt of this many commands in one turn (see "Cost").
- **Not in this repository.** The agent-side deny list that sits in another installation's configuration. This change does
  not edit, test or name it; the live check described in "Acceptance" is the only thing that touches it, after it is extended.

## 1. The rules normalize global options once

### Recommendation

A function `normalize(tokens) -> list[str]` in `command_policy` (or a module beside it, whichever keeps the file readable;
`command_policy.py` is already long) takes the tokens `_strip_wrappers` returns and returns them with the tool's global
options removed, so the program is followed by its subcommand:

- **`git`**: `-C <dir>`, `-c <key=value>`, `--git-dir=<dir>` and `--git-dir <dir>`, `--work-tree=<dir>` and
  `--work-tree <dir>`, `--namespace` in both forms, `--exec-path[=<dir>]`, and the flags with no value: `--no-pager`,
  `-p`/`--paginate`, `--bare`, `--no-replace-objects`, `--literal-pathspecs`, `--no-optional-locks`, `--no-advice`. A
  dash word it does not know is skipped as a single token, as `_skips_commit_hooks` does today, so an unknown flag does not
  make the subcommand invisible; the table of spellings is where a new one is added.
- **the host CLI**: `-R <repo>`, `--repo <repo>`, `--repo=<repo>`, and `--hostname` in the same forms, between `gh` and
  its first word.

The normalized tokens replace `tokens` in `_check_segment` immediately after `_strip_wrappers`, so `_is_git`, `_check_push`
(whose `tokens[2:]` becomes right) and `forges.denies` all see `git push ...` and `gh pr merge ...`. `_skips_commit_hooks`
and `_git_target` stop carrying their own option loops and call the same function (`_git_target` keeps the `-C` value it
returns, so `normalize` has a variant returning the directory it dropped; one place decides what a global option is). The
rule that a `core.hookspath` anywhere in the tokens switches the gate off reads the tokens before normalization, so a
`-c core.hooksPath=` is still found.

### What it must not do

It must not widen what is refused beyond the commands the rules already forbid. Reading and ordinary work through the same
options stay allowed: `git -C /w log`, `git -C /w status`, `git -C /w push origin spec/x/1` (the unit's own branch, as
today), `git --no-pager diff`, `gh -R o/r pr view 5`, and a commit message mentioning `gh pr merge`.

### The raw-API merge

`gh api` is the host CLI's escape to the host's whole API; nothing in the rules forbids it, and the research showed a merge
through it is not on the agent's list either. The forge that owns the host CLI declares it as data beside
`denied_commands`: a command prefix and the request shapes denied through it (a method of `PUT` or `POST` with a path
ending `/pulls/<number>/merge`, in either argument order, and the `-X`, `--method` and `--method=` spellings), with an empty
default so a forge without a raw client is unchanged. `forges.denies` applies it, so it stays the union over every
registered forge and a wrong `forge:` field cannot weaken it. Other forges already deny their raw escapes whole
(`denied_commands` prefixes), so nothing changes for them. UNVERIFIED: the other `forges/base.py` Protocol members and the
`local` forge; the builder gives the field a default there.

Matching on a path alone (denying every `gh api`) was rejected: the agent reads review comments and checks through it, and a
rule that forbids reading would be turned off by the first person it blocked.

## 2. One table of spellings, read by the tests and by the probe

A module beside `command_policy` holds `SPELLINGS`: for each forbidden class that has spellings, an ordered tuple of
`Spelling(name, command)` (frozen pydantic models; `name` is a closed set as a `StrEnum`: plain, directory, config,
no-pager, git-dir, work-tree, combined, repo, repo-long, api-put, api-method-after, env, command, sudo, directory-change).
The table is data and the only place a spelling is listed. The judge's tests parametrize over it and the probe sends it, so
a spelling added there is tested and probed with no second edit, and the rules and the check cannot drift (the existing
`tests/runtimes/test_acp_probe.py` already holds the probe's list to `check_command`; it now holds the whole table).

The table, with the commands used in a probe worktree (`.` is the probe's checkout; the commands are harmless there even if
one runs: no remote, a throwaway branch):

| Class (abk's words) | Spellings |
|---|---|
| amending a commit | plain `git commit --amend --no-edit`; `git -C . commit --amend --no-edit`; `git -c core.editor=true commit --amend --no-edit`; `git --no-pager commit --amend --no-edit`; `git --git-dir=.git commit --amend --no-edit`; `git --work-tree=. commit --amend --no-edit`; combined `git -C . -c k=v --no-pager commit --amend --no-edit` |
| pushing to the default branch | the same seven spellings of `git push origin main` |
| a force push to the default branch | the same seven spellings of `git push --force origin +main` |
| merging a pull request | plain `gh pr merge 1`; `gh -R o/r pr merge 1`; `gh --repo o/r pr merge 1` |
| merging a pull request through the host's raw API | `gh api -X PUT repos/o/r/pulls/1/merge`; `gh api repos/o/r/pulls/1/merge -X PUT` |

The wrapper and prefix spellings (`env X=1 <cmd>`, `command <cmd>`, `sudo <cmd>`, `cd <dir>; <cmd>`, and `sudo -u root
<cmd>`) are part of the table for the judge only, applied to the amend and merge commands: the agent folds a wrapper's name
before matching (the research's matcher run refuses `env`, `command` and `sudo` prefixes), so the probe does not spend
attempts on them. A table entry says which consumers read it (`judge`, `probe`).

The other classes (hard reset, clean, branch force-delete, recursive delete, skipping the gate) keep their one plain
probe command: the research did not measure whether the agent-side list covers their global-option spellings, and the judge
now covers them (the table of section 1's tests includes `git -C . reset --hard` and `git -C . branch -D x` as judge-only rows).

## 3. The probe tries the spellings and reports each

### The report

`PolicyReport` gains `results: tuple[SpellingResult, ...] = ()` where `SpellingResult(label, spelling, command, refused)`,
frozen. `unenforced` stays the tuple of labels it is, now naming the class and its spelling when only a spelling is open,
for example `amending a commit (as git -C . commit --amend --no-edit)`, so every existing reader (the cache, doctor,
init) keeps working and an older cached report, which has no `results`, loads as it did. `ok` is true only when every
attempted spelling was refused. A plain spelling not refused still reads as the class label alone.

### The probe

`PROBE_CLASSES` becomes a flattening of the table's probe rows plus the unchanged plain commands of the other classes;
`_probe_prompt` lists them; `_ProbeTracking` is keyed by the exact command line as now, which is why the table's
commands are written once and used verbatim. The report is assembled from the tracking in table order, so the output is
deterministic whatever order the agent attempted them in. The table, not the model, decides the spellings: the prompt
says to attempt each command exactly as written and the model has no say in what is tried.

### Cost, stated

The probe sends **one prompt**, in **one session**, as it does today; what grows is the number of commands that prompt names:
nine today, 9 + 18 + 2 + 2 = 31 after (the nine plain commands stay; the three git classes gain six spellings
each; merging gains two repository spellings; the raw API gains its two), and the number of tool calls the agent makes with it. It runs once per
check, and the existing 15-minute cache (`policy_check.checked`) applies unchanged: `abk doctor` and `abk init` reuse the
answer, and only `init`, after running a fix, asks afresh. The subset is bounded on purpose: the git classes the research
measured as open get the full set of global options (five single options and the combination), the host CLI's gets its
two repository spellings, and wrappers are not probed; every spelling beyond that is a judge test, which costs nothing.
Growing the table is a deliberate choice whose cost is one more tool call per row on each uncached check.

UNVERIFIED: whether an agent reliably attempts 31 commands in one turn. A command never attempted is reported unenforced
today (and read as the agent running it unasked), so a model that gives up half-way would produce false findings. If the
builder sees that in the fake agent's behaviour or the acceptance run, the answer is to split the table across a few
prompts in the same session (the table's rows already carry their class), not to drop spellings; the report's shape does not
change. This is why the number of prompts is a property the tests assert (one, today), so a change to it is visible.

### The runtime that answers locally

A runtime that registers the pipeline's own policy before every tool call answers without a prompt and reports everything
enforced. Its hook judges through `check_command`, so the judge fix covers it; a test runs every judge row of the table
through the hook's entry, which is how the local answer is proved to hold for spellings and not only the plain ones.

## 4. What `abk doctor` and `abk init` print

`abk doctor`'s runtime policy check already fails on an unenforced class and prints the fix; the label now carries the
spelling, and its lines group by class so the operator reads "amending a commit: refused as `git commit --amend`, not
refused as `git -C . commit --amend`, ..." rather than a flat list. `abk init` prints the same finding through the same
rendering function (one function, so `init-asks-which-runtime`'s guided policy step prints what doctor prints). A failed or
unfinished check is unchanged: nothing is cached and the next run asks again. UNVERIFIED: the present code in
`cli/doctor.py` and `cli/init.py`; the builder reads both and adjusts this section where the code says otherwise.

## Acceptance

`Acceptance: none` for the framework's own tests: every scenario is decided by the parametrized judge tests, a fake agent
that attempts the table and a fake report, so no test needs a real agent. The live check of a real agent against the
table is run once, by a person or by the announced step that follows the agent-side list being extended, and it is
reported, not asserted: a failing spelling there is the finding this change exists to produce.

## Not included

The agent-side list; a rule for local merges; probing wrappers; a new prompt per class; changing the 15-minute cache;
and making an agent's unasked commands reach abk, which is a property of the agent.
