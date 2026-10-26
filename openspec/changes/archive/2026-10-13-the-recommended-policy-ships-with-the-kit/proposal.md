# Proposal

## Why

The kit forbids a build agent to merge a pull request, amend a commit or push to a default branch, and proves an agent
refuses them (`check_policy`'s probe, over a table of spellings, and the command rules). It does not own the thing that
makes an agent refuse them. For the first known agent, that is a deny list of command globs in the agent's own repository
and a script there that merges the list into the agent's configuration. That list has just grown to 38 patterns covering
the global-option spellings of `git` and `gh` and the raw-API merge, and it is tested there against a local approximation
of the agent's matcher, with the cases written there.

That ownership is backwards for a kit. The recommendation is the kit's product: it is the answer to "what makes the check
pass". And the agent's repository will not always be present: a person who installs the kit on a machine with a different
agent, or without the agent's repository checked out, gets a failing check and a `policy_fix` key to fill in with nothing
to put there. The cases the list is tested against are the kit's own spellings table in another form, kept in step by hand.

## What Changes

- **The recommended policy is data in the kit.** One table in the runtimes package: per forbidden class, the command
  globs that refuse it across spellings, the sample commands that must match, the samples that must not, and the glob
  dialect. The spelling table the policy check already reads stays the source of the commands; the recommendation points at
  its rows instead of copying them. Tests hold every glob to the samples and the list to the check's probe rows.
- **`abk policy patterns`** prints the recommended globs (`glob`, `json`, `yaml-list`), per class if asked, for an agent the
  kit cannot patch: the person places them in the agent's own configuration. No installation and no model call needed.
- **`abk policy show`** lists the recommendation per class, the classes the recommendation does not cover, and, for a
  known agent, which patterns its configuration already has. Read-only.
- **Appliers, table-driven.** A known-agent table row may carry an apply descriptor: where the agent's configuration lives
  (a home variable and a default), its format, the key path of the deny list, and an optional build-run toolset. One engine
  merges the list: adds every missing pattern, keeps the operator's own, leaves every other byte of the file as it was (it splices lines into the original text and never re-dumps the document), is idempotent, backs the
  original up once, writes atomically, never removes. It refuses an unparseable file naming it, and does nothing when the
  agent is not installed. A new agent is a row, not code.
- **`abk policy apply [--runtime NAME] [--agent NAME] [--dry-run] [--yes] [--toolset]`** runs it: shows the diff, asks,
  writes. The build-run toolset narrowing changes what the agent can do, not only what it refuses, so it is a
  recommendation shown by `show` and applied only with `--toolset`.
- **`abk init`'s policy step gets a built-in fix.** When the installation configured no `policy_fix` and the agent has an
  applier, the step offers to apply the kit's recommended policy; the person's own `policy_fix` still wins.
- **`runtimes.<name>.policy_extra`**: an installation's own globs, merged after the kit's, so an installation never forks
  the list to add one pattern.

## Impact

- agent-build-kit: a new recommendation module and an apply engine in `runtimes/`, apply descriptors on the known-agent
  table's rows (`runtimes/acp.py`, from `init-asks-which-runtime`), `cli/policy_cmd.py`, `config.py` (`policy_extra`),
  `runtimes/policy_check.py` (`fix_for`), `cli/init.py`'s policy step, one new dependency, a YAML parser that reports
  where each node sits (read-only; the file is never re-dumped), `docs/cli.md`, `docs/agent-runtimes.md`, `docs/configuration.md`, the abk skills, the changelog.
- Specs: `agent-tool-policy` (a requirement modified, several added), `agent-runtime` (init's policy step).
- Other changes: builds after `init-asks-which-runtime` group 4. `an-internet-outage-is-not-a-failure` and
  `planned-dependencies-never-close-a-cycle` are unrelated.

## Not included

- Editing the agent's own repository: its list, script and tests. Once this lands, that repository may retire its copy and
  keep its extras under `policy_extra`; that is a follow-up in that repository.
- Appliers for agents whose configuration format or deny-list key is not verified: they get `abk policy patterns`.
- A rule for local merges, and classes the agent gates itself (hard reset, recursive delete); see design.md.
- Running the policy check automatically after applying: it spends tokens, so the person is asked, as init does.
