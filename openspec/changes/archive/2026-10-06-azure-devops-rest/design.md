# Design

## Endpoints

Pull requests (list, get, create, update with `targetRefName` and description,
abandon, draft), `pullRequests/{id}/threads` (all threads and comments in one call),
`.../threads/{id}/comments` (reply), `.../labels` (get, post, delete by name),
`.../statuses`, `.../iterations` and `.../iterations/{id}/changes` (paged),
`policy/evaluations?artifactId=vstfs:///CodeReview/CodeReviewId/{projectId}/{prId}`
(one call per pull request, no cross-pull-request batch), `build/builds/{id}` and
`build/builds/{id}/logs[/{logId}]`, commit and pull-request statuses, `git/refs` for
branch deletion, repository and policy configuration for the doctor and merge-guard
checks. Policy evaluations are a preview API: the version string is pinned.

## Models

Frozen pydantic models per resource with only the read fields, `extra="ignore"` so
unknown fields cannot break parsing. Drafted with `datamodel-code-generator` over the
published Swagger files (read as UTF-8 with a BOM) for the git, policy and build
areas, then trimmed by hand; the generator is a drafting aid, not a build step. An
unparseable response is an error carrying the endpoint and the first characters.

## Listing

One `AsyncClient` per poll with a concurrency bound (the existing read pool size). Per
open pull request: threads, policy evaluations, statuses, and for a failing build
evaluation the build result to tell cancelled from failed. Results are folded into the
same `PullRequest` the forge returns today, so everything above the seam is unchanged.
Closed and merged pull requests cost the list call only.

## Auth

PAT as a basic credential; or an Entra token for the Azure DevOps resource from the
logged-in `az` (a source, via the transport), or `azure-identity` where installed (an
optional extra) for a service principal or managed identity. The non-JSON-is-an-error
rule comes from the transport.

## Removing the CLI path

`pipeline/az.py` and the `az`-wire test fakes go. The forge's `client` attribute stays
for the agent-shell policy lists, which still name `az` because agents shell out to it.

## Risks

A preview API can change: contract tests over recorded payloads fail first. A pull
request listing that returns different fields than before is caught by a parity test
against the old fakes' expectations before they are removed.

## Out of scope

GitHub; the `httpx2` migration.
