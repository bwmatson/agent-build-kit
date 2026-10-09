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
naming the known ones. Three ship, all implemented: `github`, `azure_devops`
and `local`. One workspace may hold repos on several.

## The local forge

```yaml
repos:
  app:
    forge: local           # needs no slug and no host
```

A repo that sets `forge: local` keeps its pull requests in
`local-prs.json` in the state directory, so opening, finding, updating, closing
and listing them make no network call. The setting is the only way to select it:
no remote is ever taken for a local repo. Review comments, replies and the
review decision are read from the review store the web UI writes (see
`pipeline/ui_review.py`), so the poller treats a local pull request as any
other. Labels, drafts, statuses, check reruns and stacks are accepted and do
nothing, and `supports_stacks` is false, so units serialise per repo.

A person merges with git; nothing in the pipeline or the UI does. A pull request
is listed as merged when its branch tip is contained in the trunk or its change
is found there by patch identity (a squash or rebase), and approving in the UI
leaves it open.

A repo with no `origin` is built against its own trunk: the push, the per-unit
and per-pass fetch, `local_ref` and the dev-stack base use the local trunk and
local branches, and only the commit review approved is the branch tip pushed.
With an `origin`, behaviour is unchanged.

`abk pr view [number] [--repo NAME]` and `abk pr diff [number] [--repo NAME]`
print a local pull request and its diff, read-only; they are the forge's
`read_commands`, and it denies none. Without a number they use the open pull
request of the branch checked out in the working directory.

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
| `requires` | `config.load` | the abk.yaml keys this forge cannot name a repo without |
| `parse_remote(url)` | `abk init` | the repo an origin URL names, or None |
| `identity(repo)` | everything | a `RepoId` from the repo's abk.yaml entry |
| `config_entry(repo)` | `abk init` | the keys to write for it — the other side of `requires` |
| `web_url(repo, pr)` | `diagram` | where a human goes to look |
| `check_access(repo, run)` | `doctor`, `tracks` | "" when this machine can act here |
| `access_fix(repo)` | `doctor` | what an operator should run about it |
| `merge_guard(repo, branch, run)` | `doctor` | what stops a merge on the server, "" when nothing does |
| `list_prs(repo, head_prefix)` | the poller | every pull request, as `PullRequest` values |
| `find_pr(repo, head)` | the PR step | the number open for a branch; None only when the host answered that there is none, and a raise when it could not tell |
| `create_pr(repo, ...)` | the PR step | the new pull request's number, or the existing one when the host refuses a duplicate; raises `BaseMissing` when the base branch is not on the host |
| `comment_exists(repo, pr, marker, body, reply_to)` | the retry layer | the id of the comment (or reply to `reply_to`) carrying the marker and exactly that body, or None |
| `update_pr(repo, pr, base, body)` | the PR step, restack | retarget or re-describe |
| `pr_files(repo, pr)` | `abk verify` | the paths a change touched |
| `review_notes(repo, pr)` | rework | the reviewer's words, and whether each is still live |
| `post_reply(repo, pr, note_id, body)` | rework | the ids of what was posted |
| `post_comment(repo, pr, body)` | rework, restack | ditto, for a note about the PR itself |
| `post_status(repo, sha, ok, ..., head)` | the tier 2 gate | publish a result against the tested commit; a host that shows statuses on the pull request also gets it there, found from `head` |
| `failed_check_logs(repo, pull)` | rework | what the failing checks said |
| `rerun_checks(repo, pull)` | `events` | run the pull request's cancelled checks again: GitHub re-runs the workflow runs behind them, Azure DevOps requeues the build policy evaluations whose build was cancelled |
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
`forges.denies(tokens)` folds every registered forge's `denied_commands`.

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

`checks` is the pull request's list of `Check(name, status, url)`, `status` being
`passed`, `failed`, `cancelled` or `pending`; `url` is the host's link (on Azure DevOps
a status's target, or the build's results page for a build policy), `""` where it gives
none. The failing and cancelled names are read from it with `failing_names` and
`cancelled_names`, and `overall_result` is `failed` when any check failed, otherwise
`pending` when any is pending (a list of cancelled checks only reads as pending),
otherwise `passed`, and `none` for an empty list. A value a forge does not know maps to
`pending`, never `failed`, so it cannot send a unit back. Checks may share a name; the
poller's snapshot keeps the most severe status for a name.

| Status | GitHub | Azure DevOps status | Azure DevOps build policy |
|---|---|---|---|
| passed | success, neutral, skipped | succeeded (not applicable is omitted) | approved (not applicable is omitted) |
| failed | failure, timed out | failed, error | rejected or broken, the build not cancelled |
| cancelled | cancelled | — | rejected with the build's result cancelled |
| pending | no conclusion, or unknown | pending, not set | queued, running |

Azure DevOps merges its two sources into one list: pull request statuses (the latest
posting per genre and name wins) and the build-validation policy's evaluations.

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

The pipeline's own Azure DevOps calls are REST requests, not `az` commands, so no
command shape needs an exception: `az repos pr update`, `az rest` and `az devops
invoke` are denied whole, and the same prefixes are refused by the runtime's deny
flags.

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
7. **State the description limit.** `description_limit` is the most characters
   the host takes in a pull request description. The pipeline shrinks the body
   to it first; the forge's `create_pr` and `update_pr` still cut what is over,
   through `fit_description` in `forges/base.py`, which cuts on a line, closes
   an open code fence and details block, and appends a note.
8. **Record real fixtures.** From a real pull request, keeping the fields your
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
  requests are asked for theirs (the policy evaluations of the pull request's artifact,
  every page of them); `rejected` and
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
  clean log. The transport treats a non-JSON body as an `AuthError` for this
  reason alone.
- Branch names arrive as `refs/heads/x`; `labels` is `null`, not `[]`;
  retargeting is a PATCH of `targetRefName`, made only when it differs, because the
  host answers a retarget to the branch a pull request already has with a 400; and
  the source branch survives a merge, so it is ours to delete.

The pull request body names the repo's `default_branch` where it says what a
unit assumes is already merged, and the CI that runs a tier 1 unit's checks is
the forge's `ci_name` ("GitHub Actions" on GitHub, "Azure Pipelines" here).

## The HTTP transport

`forges/transport.py` is the one way a forge makes an HTTP call. `credential_for(forge,
owner)` resolves the credential - the repo's setting (`GH_TOKEN`), else the host CLI's
logged-in token for that owner (`gh auth token --user <owner>`) - once per owner, cached
for the process, and never in an argument list. A `Transport(base_url, credentials)`
puts a timeout on every call and makes it once: a connection error, a timeout, a 429 or
a 5xx is raised as it happens, and the retry layer below decides whether to repeat it.

Answers that are not the expected one are errors: `AuthError` for 401/403, a missing
credential, or an HTML page where JSON was expected (quoting its first characters);
`NotFound` carrying the account the call was made as; `RateLimited` with the host's
hint; `HostError` for a 5xx or a network failure. A test passes an `httpx.MockTransport`
as `transport=` and never reaches a network. `abk doctor` resolves a credential for each
GitHub repo, calls `GET /user` and reports the account, or the source that failed.

## The retry layer

`forges/resilient.py` is the one place a forge call is repeated, for every host; the
registry returns each forge wrapped in a `ResilientForge`. `forges/operations.py`
declares a kind for every protocol method, and a test fails when one has no entry:

- `read` and `idempotent_write`: repeated on a transient failure (`HostError`,
  `RateLimited`) up to `forge_retries` times, with exponential backoff and jitter. A rate
  limit waits the larger of the backoff and the host's hint; a hint longer than the
  transport's ceiling fails the call at once with the hint on the error.
- `create`: repeated only after the read named in its `lands` shows it did not land
  (`find_pr` for a pull request, `stack_of` for the stack calls, `comment_exists` for a
  comment or reply). A hit returns that
  result without a second create; a failing read counts as an attempt; a create with no
  usable read is never repeated. A rate-limited create was refused before it did
  anything, so it is repeated without asking.
- `advisory`: retried like a write; if it still cannot complete it is logged, counted and
  returns `None`.

`forge_deadline_seconds` (`ABK_FORGE_DEADLINE_SECONDS`, default 120) bounds the time from
the first call to the last wait. When every attempt fails, the call raises
`HostUnavailable(operation, cause, attempts)`, a `TransportError`, so a caller can tell the
host being down from a refused call. Authentication, not-found and other client errors are
never retried. Each retry is logged (`forge <operation>: attempt n of m failed ...`) and
counted in `abk.forge.retries` by `operation` and `outcome` (`retried`, `landed`,
`exhausted`, `contained`).

## Authentication

GitHub selects a token per repo owner (`transport.credential_for`, with the
lookup order in `pipeline/shell.py`), because a call against another account's
private repo reports it as *nonexistent* — indistinguishable, from the caller's
side, from a repo with no pull requests. The token travels in a header; `gh` is
needed only as a credential source, and for the agent's own `gh pr view`.

Azure DevOps uses a PAT when one is set and the `az` sign-in session otherwise;
both have to work, so a headless box and a workstation are both usable.
`settings.ado_pat` reads `AZURE_DEVOPS_EXT_PAT` first — the extension's own
variable, so a machine already set up for `az repos` needs nothing new — then
`ABK_ADO_PAT`.

Both resolve through `transport.credential_for("azure_devops", org)`: a PAT is sent
as a Basic credential with an empty user, and without one the token of
`az account get-access-token` (read again, once, when the host rejects it as expired) is sent as a Bearer. Either
travels in a header, never in an argument list or a URL, so `ps` cannot show it for the
hours a build runs. `az` is therefore needed only as a credential source.

## Azure DevOps over REST

`forges/azure_devops.py` talks to `https://dev.azure.com/<org>/<project>/_apis/` through
the transport and starts no process. Every call carries `api-version=7.1`, except
policy evaluations, which are served only under `7.1-preview.1`. The documents it reads
are the models in `forges/azure_models.py`: only the fields the pipeline reads, an
unknown field ignored, snake_case attributes aliased to the host's camelCase. A body
that does not parse raises a `TransportError` naming the endpoint and quoting the start
of what came back.

Lists are read to the end: pull requests by `$top`/`$skip`, policy evaluations by
`$top`/`$skip` (read until an empty page), an iteration's changes
by `nextSkip`/`nextTop`. A poll reads a pull request's threads, statuses and evaluations
only while it is open, on a pool of `READ_POOL` threads, so the requests in flight stay
bounded; a build is read only behind a failing evaluation. A refused call raises what the
transport raises (`AuthError`, `NotFound`, `TransportError` quoting the host's message),
and `create_pr` turns the two refusals that mean the base branch is gone into
`BaseMissing`.

## GitHub over REST and GraphQL

`forges/github.py` talks to `https://api.github.com` through
`githubkit` and starts no process. `ABK_GITHUB_API_URL` names another address (a GitHub
Enterprise host, or a stand-in in a process test); the forge and `abk doctor`'s credential
check both call it, and a trailing slash is ignored. On an Enterprise host set `GH_TOKEN`, because the
`gh auth token` lookup asks github.com. A forge holds
one `githubkit.GitHub` client per repo owner, built with that owner's credential
(`TokenAuthStrategy`), so units for two owners run side by side and a client is never
shared across owners. HTTP caching is off, every call has `forge_timeout_seconds`, a
redirect is not followed (a job log's signed link is fetched by the forge, without the
credential), and githubkit's `auto_retry` is off: the forge makes each call once. A test
passes its `httpx.MockTransport` as `transport=`. The documents it reads
are the models in `forges/github_models.py`: only the fields the pipeline reads, an
unknown field ignored.

The dependency is pinned to one minor version (`githubkit>=0.16.1,<0.17`): it has one
maintainer, and everything it is used for sits behind this module, so a replacement
touches this file only. githubkit depends on `httpx`, which is why the framework's
transport still uses `httpx`; moving to its successor waits for a githubkit release that
supports it.

Listing is one GraphQL query per page of a hundred pull requests, read by cursor to the
end, carrying the labels, issue comments, submitted reviews (a pending one is left out),
the newest commit's check runs, the review decision and mergeability. Everything else is
REST: pull requests, review notes (two paged lists), replies (the reply and the review it
makes), issue comments, labels (the repo's copy is created, recoloured or re-described
before it is put on a pull request), statuses, branch protection, and the stack
endpoints, where a 409 is reported as concurrent. Drafting is the two GraphQL mutations,
after reading the pull request's state. The failed-job log is the run's jobs and each
failed job's log, which the host answers with a redirect to storage that is fetched
without the credential.

A refusal (githubkit's `RequestFailed`) raises a `TransportError` (a `RuntimeError`) that
carries the host's `status` and whole `body`; `create_pr` reads the body to tell a missing base branch
(`BaseMissing`) from a duplicate, which returns the existing pull request, and from any other 422.
`update_pr` and `post_status` are advisory on both hosts (Azure DevOps contains a refused body
update or status as GitHub does). `update_pr`, `delete_remote_branch`, `post_comment`,
`post_reply` and `post_status` keep their best-effort behaviour: a failure is logged, not
raised. `Forge.client` is optional: a forge reached over HTTP alone names no command.
