# Code forges

The pipeline opens **one pull request per unit** and then polls it until a
human merges it. Which host that pull request lives on is a **forge**
(`forges/`), and every call the pipeline makes about a pull request goes
through one. A repo names its forge in `abk.yaml`:

```yaml
repos:
  app:
    forge: github          # the default
    slug: example/app
```

`forges.get(name)` returns it; an unknown name fails when abk.yaml loads,
naming the known ones. Two ship, both implemented: `github` and
`azure_devops`. One workspace may hold repos on both.

The rule that shapes the package: **a forge returns typed values, not the
host's JSON.** Every `mergedAt` and `CHANGES_REQUESTED` the pipeline used to
read is an attribute on a `PullRequest` or a `ReviewNote`, so a second host is
a translation at one boundary rather than a second document shape running
through the poller, the rework loop and the runner.

## The protocol

`forges/base.py` defines `Forge` as a `Protocol`, for the reason
`ToolchainProfile` and `AgentRuntime` are: implementations own their own code,
a test double is a plain class (`tests/forges/stand_in.py`), and the shared
parts are free functions beside it rather than inherited behaviour.

| Member | Used by | What it answers |
|---|---|---|
| `name` | `abk.yaml`, the registry | the key a repo names |
| `implemented` | `cli/pipeline._build` | false holds a unit rather than failing it |
| `deletes_head_branch_on_merge` | `events` | whether the remote branch is ours to clean up |
| `denied_commands` | `command_policy`, the deny flags | command prefixes no agent may run, on any repo |
| `read_commands` | `wiring.allowed_tools`, the tracks' default allow-list | command prefixes an agent may run to read a PR; none may overlap any forge's `denied_commands` |
| `permitted_commands` | `forges.denies` | exact command shapes allowed although a denied prefix covers them |
| `requires` | `config.load` | the abk.yaml keys this forge cannot name a repo without |
| `parse_remote(url)` | `abk init` | the repo an origin URL names, or None |
| `identity(repo)` | everything | a `RepoId` from the repo's abk.yaml entry |
| `config_entry(repo)` | `abk init` | the keys to write for it — the other side of `requires` |
| `web_url(repo, pr)` | `diagram` | where a human goes to look |
| `check_access(repo, run)` | `doctor`, `tracks` | "" when this machine can act here |
| `access_fix(repo)` | `doctor` | what an operator should run about it |
| `merge_guard(repo, branch, run)` | `doctor` | what stops a merge on the server, "" when nothing does |
| `list_prs(repo, head_prefix)` | the poller | every pull request, as `PullRequest` values |
| `find_pr(repo, head)` | the PR step | the number open for a branch, or None |
| `create_pr(repo, ...)` | the PR step | the new pull request's number; raises `BaseMissing` when the base branch is not on the host |
| `update_pr(repo, pr, base, body)` | the PR step, restack | retarget or re-describe |
| `pr_files(repo, pr)` | `abk verify` | the paths a change touched |
| `review_notes(repo, pr)` | rework | the reviewer's words, and whether each is still live |
| `post_reply(repo, pr, note_id, body)` | rework | the ids of what was posted |
| `post_comment(repo, pr, body)` | rework, restack | ditto, for a note about the PR itself |
| `post_status(repo, sha, ok, ..., head)` | the tier 2 gate | publish a result against the tested commit; a host that shows statuses on the pull request also gets it there, found from `head` |
| `failed_check_logs(repo, pull)` | rework | what the failing checks said |
| `rerun_checks(repo, pull)` | `events` | run `pull.cancelled_checks` again: GitHub re-runs the workflow runs behind them, Azure DevOps requeues the build policy evaluations whose build was cancelled |
| `delete_remote_branch(repo, branch)` | `events` | remove a merged unit's branch |
| `close_pr(repo, pr)` | the satisfied outcome | close without merging, raising if the host refuses |
| `add_label(repo, pr, label)` | state labels | put the label on, creating it in the repo first if missing; raises if the host refuses |
| `set_exclusive_label(repo, pr, label, family)` | state labels | put the label on and take off the rest of `family` only |
| `remove_label(repo, pr, name)` | the poller | take `agent-rework` off once acted on |
| `set_draft(repo, pr, draft)` | state drafts | make the pull request a draft or publish it; reads the current state first and writes only when it differs; raises if the host refuses |

A host without labels raises `NotImplementedError` from all three label methods. That is said
once ("this host keeps no labels") rather than logged as a failure on every
call; any other error is logged as one.

**Drafts.** A pull request is a draft while its unit is `running` and published
when the unit is `in_review`; every other state, and the change that first records
the pull request, leaves it as it is, so a unit that fails mid-run stays a draft.
A new forge implements `set_draft`. A host with no drafts raises
`NotImplementedError`, said once ("this host keeps no drafts"); any other error
is logged. Drafts are cosmetic and never read back, and the poller does not treat
a pull request turning draft as an event.

Azure DevOps keeps labels (it calls them tags) but no colour or description, so
a state is told apart by its name there; the colour and description a caller
passes are accepted and ignored. Pull requests already open pick up their labels
at their next state change; there is no backfill.

Two free functions sit beside the Protocol rather than on it: `forges.key(repo)`
is the canonical identity string (`owner/name`, or `org/project/repo`) that
`own-posts.json` and the poller's state files are keyed on, and
`forges.denies(tokens)` folds every registered forge's `denied_commands`, less
their `permitted_commands`.

`post_reply` and `post_comment` return ids because only the forge knows what an
id looks like, and what they return must be what the next poll's
`conversation` contains — otherwise the pipeline reads its own reply as new
review and reworks the unit in answer to itself. That identity is the single
most important thing a new forge has to get right.

## The values

`Label` is a name, a six-hex-digit colour without the `#`, and a description.

`PullRequest` is what the poller diffs. `state` uses the vocabulary in
`pipeline/units.py` (`merged`, `closed`, or `open`), so nothing downstream
learns a second set of words for the same three outcomes. `conversation` is
opaque comment ids, `comment_bodies` the words behind them, `labels` drives
`agent-hold` and `agent-rework`, and `review_decision` is `""` or
`"changes_requested"`.

`ReviewNote` carries `live`: whether the note is still worth replaying to a
rework. It is the generalisation of GitHub's outdated-comment convention —
`line: null` once the code a comment sat on has changed — and Azure DevOps
answers the same question with a resolved thread. Either way a rework must not
be handed feedback it has already addressed, or every round replays every
earlier round.

## The security rule

`command_policy` refuses **every registered forge's** merge commands, not the
current repo's: an agent in a GitHub checkout has no business completing an
Azure DevOps pull request either, and a union cannot be weakened by a wrong
`forge:` field. The same prefixes are passed as deny flags on every policed
run and on every track phase — two independent layers by design, so two things
have to fail before an agent can merge its own pull request.

A forge that adds a command here must add it to `denied_commands` only; both
layers read from there.

`permitted_commands` carves out the calls the pipeline itself makes under a
denied prefix. Azure DevOps permits `az repos pr update` only when every flag is
spelled in full and on its list, with a permitted value: `--id` (an integer),
`--status` (`abandoned` or `active`), `--draft` (`true` or `false`), `--org`,
`--organization` and `--detect` (any), and `--output json`, which `az.call`
appends. A match is of the whole shape, not a prefix: any other flag
(`--auto-complete`, `--bypass-policy`, `--title`, ...), an abbreviation, a
repeated flag, a missing value or a stray positional keeps the command denied.
`--flag=value` and `--flag value` are both read. `az rest` and `az devops
invoke` have no exception, and GitHub's list is empty (`gh pr close` is not
denied). Only the `denies` layer reads the list: the runtime's deny flags are
prefixes and stay whole, so an agent is still refused these commands there.

## Adding a forge

1. **Write the module.** `forges/<name>.py`, a plain class with the members
   above and a module-level `FORGE = <Name>Forge()`. Start with
   `implemented = False` and raise from the methods you have not written: a
   unit in such a repo is then *held*, not failed, which is the difference
   between "not yet" and "broken".
2. **Register it.** Add it to `_load_builtin` in `forges/__init__.py`, and to
   `_ORDER` — **order matters**: GitHub's origin pattern accepts any
   `alias:owner/name`, an ssh host alias carrying a deploy key, so it must be
   asked last or it claims every host's ssh remote.
3. **Say what a repo needs.** `requires` names the abk.yaml keys, and
   `config_entry` writes them. `abk init` then drafts a file that loads, and a
   repo missing a key fails at load rather than once every unit is held.
4. **Implement `set_draft`.** Read the pull request's draft state, write only
   when it differs, and raise when the host refuses.
5. **Deny every way of merging.** Not just the obvious command: a host may
   complete a pull request through an update, a vote, a policy change and a
   raw API escape, and all of them belong in `denied_commands`.
6. **Say how an agent reads its PR.** `read_commands` lists the command
   prefixes (`az repos pr show`, `gh pr view`); `wiring.allowed_tools` and the
   tracks' default allow-list are composed from them. A test fails if one
   overlaps any forge's `denied_commands`, so a read command can never be a
   write.
6. **Record real fixtures.** From a real pull request, keeping the fields your
   code does *not* read. That is what makes a host's traps catchable by a test
   rather than by an incident — see below.

## Stacked pull requests on Azure DevOps

Stacked PRs are unsupported on Azure DevOps (`supports_stacks = False`), so
units serialise per repo there: a unit waits for its parent to merge rather than
opening against the parent's branch.

## What each host makes easy to get wrong

These are the mistakes the two shipped forges were written against. A third
will have its own, and finding them is most of the work.

**A missing base.** A parent merging deletes its branch, so a pull request
opened against it is refused. Each forge recognises its own message (GitHub's
"Base ref must be a branch", Azure DevOps's TF401028 and TF401398) and raises
`BaseMissing`. The runner then asks for the base afresh: a parent whose pull
request the forge reports merged is recorded, and the unit resumes at its
restack on the branch it merged into. A base that is still the parent's, with
nothing merged, leaves the unit planned to resume there; any other refusal is a
failure.

**GitHub.** `state: MERGED` is not the same question as `mergedAt`; a PENDING
review is a draft the reviewer has not submitted, and counting it sends the
unit back for rework with nothing to act on; a reply creates a bodyless review
of its own, whose id must be recorded or the poller reads it as feedback.

**Azure DevOps.**

- **`status == "completed"` is the only proof of a merge.** An open pull
  request carries `mergeStatus: succeeded` *and* a populated `lastMergeCommit`,
  exactly as a merged one does — verified against six real pull requests,
  three of each. Reading either as proof marks every open PR merged, which
  restacks its children and deletes their branches.
- **`mergeStatus` is the conflict signal, and only two of its values are
  definite.** `succeeded` is mergeable and `conflicts` is not; `queued` and
  `notSet` are the host working it out, and `rejectedByPolicy` and `failure`
  say nothing about conflicts, so all four leave `mergeable` undetermined and
  the poller keeps its last definite answer. `status` still alone says merged.
- **A branch policy's build is a policy evaluation, not a status.** Open pull
  requests are asked for theirs (`az repos pr policy list`); `rejected` and
  `broken` are failing checks, while `running`, `queued`, `approved` and
  `notApplicable` are not. A completed or abandoned pull request makes no
  policy call.
- **Tier 2's result is posted twice.** The commit status stays the record of
  the commit measured; the open pull request for the unit's branch also gets
  the same status, because Azure shows only a pull request's own. A completed
  or abandoned pull request takes none, and a refusal is a logged warning, not
  a failed unit. The newest status of a context replaces the last, so a rework
  that passes clears the failing `local/tier2`.
- **The server comments on its own.** "The reference refs/heads/… was updated"
  is written on the thread list on *every push*, and the pipeline pushes on
  every rework and every restack. Counted as a comment, each push reworks the
  unit that just pushed, and it never stops. The filter is
  `commentType == "system"`, not `commentType == "text"` — real comments come
  back with a null type, and the inverted rule drops a reviewer's words.
- **Comment ids restart at 1 in every thread**, so a note's id carries its
  thread's, or two different comments read as one.
- **A vote is a scale, not a flag.** 10 approved, 5 approved *with
  suggestions*, 0 no vote, −5 waiting for the author, −10 rejected. Only a
  negative vote asks for changes; reading 5 as rework sends an approved unit
  round the loop on every poll. A group's vote (`isContainer`) is nobody's.
- **An unauthenticated request is answered with a sign-in page and a 2xx.**
  Parsed leniently that is `{}`, which reads as "no pull requests": the
  poller's failure counter never trips and the pipeline goes quiet with a
  clean log. `pipeline/az.py` treats a non-JSON body as an error for this
  reason alone.
- Branch names arrive as `refs/heads/x`; `labels` is `null`, not `[]`;
  `az repos pr update` has no `--target-branch`, so retargeting is a REST
  PATCH; and the source branch survives a merge, so it is ours to delete.

The pull request body names the repo's `default_branch` where it says what a
unit assumes is already merged, and the CI that runs a tier 1 unit's checks is
the forge's `ci_name` ("GitHub Actions" on GitHub, "Azure Pipelines" here).

## The HTTP transport

`forges/transport.py` is the one way a forge makes an HTTP call. `credential_for(forge,
owner)` resolves the credential - the repo's setting (`GH_TOKEN`), else the host CLI's
logged-in token for that owner (`gh auth token --user <owner>`) - once per owner, cached
for the process, and never in an argument list. A `Transport(base_url, credentials)`
puts a timeout on every call and retries connection errors, timeouts, 429 and 5xx with
backoff, honouring `Retry-After`, up to a bound. A write is repeated only when it is
idempotent by nature (PUT, DELETE) or the caller passes `idempotent=True`; a create-style
POST is never retried blindly.

Answers that are not the expected one are errors: `AuthError` for 401/403, a missing
credential, or an HTML page where JSON was expected (quoting its first characters);
`NotFound` carrying the account the call was made as; `RateLimited` with the host's
hint; `HostError` once the retry bound is spent. A test passes an `httpx.MockTransport`
as `transport=` and never reaches a network. `abk doctor` resolves a credential for each
GitHub repo, calls `GET /user` and reports the account, or the source that failed.

## Authentication

GitHub selects a token per repo owner (`pipeline/shell.py`), because `gh` has
one active account at a time and a call against another account's private repo
reports it as *nonexistent* — indistinguishable, from the caller's side, from
a repo with no pull requests.

Azure DevOps uses a PAT when one is set and the `az` sign-in session otherwise;
both have to work, so a headless box and a workstation are both usable.
`settings.ado_pat` reads `AZURE_DEVOPS_EXT_PAT` first — the extension's own
variable, so a machine already set up for `az repos` needs nothing new — then
`ABK_ADO_PAT`.

Every `az` call goes through `pipeline/az.py`, which is to `az` what
`pipeline/shell.py` is to `gh`: there is no second way to make one, so a new
call site cannot forget what this one remembers. It names the organisation on
every call rather than relying on `az devops configure --defaults` — global
CLI state, and units run concurrently — and passes the token through the
environment rather than argv, where `ps` would show it for the hours a build
runs.
