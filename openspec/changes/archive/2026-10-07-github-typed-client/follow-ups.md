## From `github-typed-client/1`

- Record in the change's design (planning repo) that GitHub responses are parsed through the tolerant `forges/github_models.py` documents, not githubkit's generated response models, because the generated models reject bodies with missing fields. The drift protection the Risks section describes now applies only to request bodies.
- `_repeatable` (forges/github.py) should check `isinstance(error.exc, httpx.HTTPError)` before reading `.request`. A `RequestError` around a non-httpx exception otherwise raises AttributeError out of the retry policy instead of becoming a `HostError`.
- `list_prs` reads every page of every pull request, and `find_pr`-style single-branch lookups could use GraphQL `headRefName:` or a `states`/age bound. This scaling decision was deferred from round 1.
- src/agent_build_kit/forges/github.py:747 — `_repeatable` reads `error.exc.request` and catches only RuntimeError. githubkit's `RequestError` can wrap any exception (`core.py` re-raises a bare `except Exception` as `RequestError(e)`), and a non-httpx exception such as one raised inside an auth flow has no `.request`, so this raises AttributeError from inside `auto_retry`.
- src/agent_build_kit/forges/github.py:7 — Answers are read through the hand-written `github_models` documents via `.json()`, not githubkit's generated response models. The builder disclosed this.
