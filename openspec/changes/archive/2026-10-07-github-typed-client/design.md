# Design

## Client

`GitHub(auth, timeout=..., transport=..., auto_retry=..., http_cache=False)` built per
owner from `credential_for(github, owner)`; clients are cached per owner for the
process. Tests pass an `httpx` mock transport. A client is never shared across owners.

## Listing

One GraphQL query per repository for the first hundred pull requests with `state`,
`isDraft`, `mergedAt`, labels, issue comments, reviews (excluding pending), the status
check rollup and its contexts (with conclusions, to separate failing from cancelled),
`reviewDecision` and `mergeable`. The mapping into the frozen `PullRequest` is the one
that exists today; a parity test over recorded payloads proves the same output. Paging
follows the cursor.

## Writes and reads by REST

Typed REST for pull-request create and edit (base, body), review comments and replies
(returning both node ids the pipeline records as its own posts), issue comments,
labels, statuses, branch protection, branch deletion and the stacks endpoints
(`create`, `add`, `get`); `BaseMissing` and the stacks conflict are mapped from the
response status and message exactly as today. Draft toggling uses the GraphQL
mutation.

## Logs

Failed-job logs come from the run's jobs and the job-log endpoint, escape sequences
kept; the extraction (timestamp prefixes, the cut at the last error line, the length
cap) is unchanged domain code over the text.

## Credentials

Settings token, else the CLI's token for the owner read once. GitHub Apps are possible
through githubkit's installation auth and are not part of this change.

## `httpx`

githubkit depends on `httpx`, so the framework's transport uses it for now; the module
boundary keeps a later swap to `httpx2` to one change.

Follow-up, deliberately not a queued change: `httpx2` is the maintained successor of
`httpx` and the neighbouring projects already use it, but githubkit supports only
`httpx` today (its upstream issue and pull request for `httpx2` were still open on
2026-10-05). When a githubkit release supports `httpx2`, write the migration then: swap
the import in the transport module, bump githubkit, move the mock transports in the
tests, and drop `httpx` from the dependencies. A change written earlier would only
fail its first task and spend a build.

## Risks

One maintainer upstream: pin the version, keep the seam so a replacement touches the
adapter only. A generated model drift is caught by contract tests over recorded
payloads.

## Out of scope

Azure DevOps; the `httpx2` migration.
