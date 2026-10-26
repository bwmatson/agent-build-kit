# Proposal

## Why

Every GitHub operation is a `gh` subprocess with no timeout, parsed from CLI output,
and credentials are chosen by calling the CLI per owner. The CLI has to be installed
and logged in.

`githubkit` is a maintained typed client (pydantic models generated from GitHub's
OpenAPI description, REST and GraphQL, retry and backoff, timeout and transport
options, App and token auth). Its typed schema already includes the new stacked
pull-request endpoints. The alternatives were weighed: PyGithub is synchronous, built on
`requests`, REST-only and LGPL; `ghapi` returns untyped objects and has no GraphQL
support that was found; `github3.py` has not been released since 2023;
`gidgethub` is async-only with untyped results; and LangChain's GitHub toolkit is
archived and lacks most of what is needed.

## What Changes

- **GitHub operations run on `githubkit`** behind the existing forge seam: pull-request
  listing as one GraphQL query for state, draft, labels, comments, reviews, checks and
  mergeability; review notes, replies and comments; labels with the colour and
  description reconcile; commit statuses; run and job logs with the existing log
  extraction kept as domain code; rerun of failed jobs; draft through the GraphQL
  mutation; close; base edit; stacks; branch protection.
- **One client per owner,** built from the transport's credential for that owner, with
  explicit timeout and retry and HTTP caching off so runs are deterministic.
- **`gh` becomes a credential source only** and is no longer called for anything else;
  `Forge.client` becomes optional.
- **Tests use a mock transport** and recorded payloads; the exact-argument `gh`
  assertions are removed with the code they test.
- **`httpx` is the HTTP library for now,** because githubkit uses it; the migration to
  `httpx2` is a later change.
