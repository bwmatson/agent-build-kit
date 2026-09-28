# Category: Convention adherence

Weekly-cadence category (run via `improve.md`) — a repo-wide grep sweep
that doesn't need to be daily. A project's `CLAUDE.md` usually has a
"Conventions" section listing the rules its codebase is supposed to
follow everywhere — read *this run's project's* list and grep for
violations of each. The kinds of rule to expect (check the wording in
its own `CLAUDE.md` — the details differ from project to project):

- **Env config**: every service centralizes env vars in one settings
  module (e.g. `pydantic-settings`, with a named reference `settings.py`).
  Grep for raw `os.environ`/`os.getenv` usage outside that module —
  that's a violation.
- **Wire models**: cross-service request/response shapes belong in the
  owning side's models package (the `CLAUDE.md` says where, and whether
  another repo in the workspace owns some of them). Look for hand-rolled
  models on the *calling* side that duplicate a shape already defined
  there — a sign a client-side model was written instead of importing
  the shared one.
- **Internal auth**: internal HTTP APIs gate on a single shared API key
  per service through one helper (a constant-time comparison). Look for
  internal routes missing this check — but note the project's documented
  exceptions (e.g. message-broker consumers and a connector's ingress
  relying on network segmentation instead).

Plus whatever else this project's own list adds (e.g. LLM calls only
through a gateway by model alias, a tracing-content flag every caller
must set). Report concrete findings: file/line, which convention, what's
actually there instead. Don't propose a fix — `improve.md` decides what
to act on after seeing every category.
