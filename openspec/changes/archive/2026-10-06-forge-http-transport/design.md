# Design

## Module

`forges/transport.py` (framework package, no installation names): `Credentials`
(frozen pydantic: scheme, token, source), `credential_for(forge, owner)`, and
`Transport` wrapping an `httpx.Client` / `httpx.AsyncClient` built from a base URL,
credentials, a timeout policy and a retry policy. `Transport.request(...)` returns a
small response model (status, headers, json or text) and raises typed errors:
`AuthError` (401/403 and sign-in pages), `NotFound(account)`, `RateLimited(retry_after)`,
`HostError`. The pydantic settings class gains the retry and timeout knobs
(`ABK_FORGE_TIMEOUT_SECONDS`, `ABK_FORGE_RETRIES`), with defaults.

## Retry

Exponential backoff with jitter, bounded count and total time, on connection errors,
timeouts, 429 and 5xx; `Retry-After` is honoured. A write is retried only when it is
idempotent by nature (PUT, DELETE, a PATCH to a fixed value) or the caller says so; a
POST that creates something is never retried blindly.

## Credentials

Order: the repo's explicit setting, then the host CLI's logged-in token for that owner
(`gh auth token --user <owner>`, `az account get-access-token --resource <ado>`), read
once per owner and cached for the process. The CLI is a source, not a client. A missing
credential is an `AuthError` naming the owner and the source tried.

## Silent failures

The expected media type is checked on every response. A non-JSON body where JSON is
expected raises `AuthError` with the first characters of the page. A not-found on a
repository endpoint raises `NotFound` carrying the account the call used.

## Tests

`Transport` takes an optional `httpx.BaseTransport`; the suite's fixtures pass a
`MockTransport` loaded from recorded payloads. Fixture owners only (`example`, `acme`).

## `abk doctor`

Replaces the binary check with a credential check per repo: resolves the credential
and calls the host's cheapest authenticated endpoint, reporting the account name or the
source that failed.

## Out of scope

The GitHub and Azure operations themselves (their own changes), and `httpx2`.
