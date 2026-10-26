# Proposal

## Why

An agent driven over the protocol runtime ran `git -C <worktree> commit --amend --no-edit` as a terminal command in a full
tier 2 run and nothing refused it. The research behind this change found three things, each checked against the code:

- **abk's own rules have the same hole.** `command_policy._is_git` needs the program and the subcommand side by side, so
  any git global option between them (`-C <dir>`, `-c k=v`, `--no-pager`, `--git-dir`, `--work-tree`) makes the amend
  rule, the default-branch push rule and the force-push rule judge nothing. The same holds for the host CLI's own
  repository option (`gh -R owner/repo pr merge`), and the raw-API spelling of a merge is not forbidden at all.
- **The check cannot see it.** `check_policy`'s probe attempts one plain spelling per forbidden class, so a pass says
  nothing about a spelling an agent would naturally write (an agent working in a worktree writes `git -C <worktree>`).
  The agent's own deny list has the same gap, for every global-option spelling and for amend, push to the default branch
  and force-push alike; that list lives elsewhere and is not part of this change.
- **The call never reaches abk.** The agent runs its terminal itself and asks abk only about the commands it flags, so
  abk's rules cannot refuse what the agent never asks about. What abk can do is make its own rules agree with reality and
  make the check report which spelling an agent runs without asking, so the operator knows what the agent-side list must
  cover.

## What Changes

- **The command rules normalize tool-global options first.** One function reads a segment's tokens and drops the global
  options of the code host's tools the rules already name (`git`'s `-C`, `-c`, `--no-pager`, `--git-dir`, `--work-tree`
  and the rest of its short list, in both the `=` and the two-token forms; the host CLI's repository option), so the amend,
  push, force-push, hard-reset, clean, branch-delete and pull-request-merge rules all judge the command the tool would run.
  The wrapper and directory-change prefixes (`env X=1`, `command`, `sudo`, `cd X;`) are covered by the same table of
  spellings so a regression shows.
- **A raw-API merge is a forbidden class.** The forge that owns the host CLI names the raw-API request that merges a pull
  request, so the union of forges denies it as it denies the plain merge command.
- **The policy check tries a table of spellings per class.** One table, in the framework, gives each forbidden class its
  spellings; the judge's tests and the probe both read it, so the rules and the check cannot drift. The probe attempts a
  bounded subset in one prompt and returns, per class and per spelling, whether it was refused. `abk doctor` fails
  naming the spelling an agent lets through.

## Impact

- agent-build-kit: `pipeline/command_policy.py` (the normalization and the judges that use it), `forges/` (the raw-API
  merge), a new spelling table module beside `command_policy`, `runtimes/acp.py` (`PROBE_CLASSES`, `_probe_prompt`,
  `_ProbeTracking`, `_probe`), `runtimes/base.py` (`PolicyReport`), `runtimes/policy_check.py` (an older cached report
  still loads), `cli/doctor.py` and `cli/init.py` (the finding's wording), `docs/agent-runtimes.md`, `docs/cli.md`, the
  changelog.
- Specs: `agent-tool-policy`.
- Other changes: `init-asks-which-runtime` group 2 prints what this check reports and gains a `Needs:` line for group 1
  here.

## Not included

- **The agent-side deny list.** It is another repository's configuration; this change makes the check name what it must
  still cover and does not edit it. The live check against a real agent is run once, and announced, after that list is
  extended; it is not a unit test.
- Calls abk never sees. An agent that runs a command without asking stays only as constrained as its own list; the check
  reports it, and branch protection and the pipeline's approved-commit gate remain the layers that hold whatever spelling
  is used.
- A rule for local `git merge`: merging into a branch of the unit's own worktree is not something abk forbids, so it is not
  a class of this table.
