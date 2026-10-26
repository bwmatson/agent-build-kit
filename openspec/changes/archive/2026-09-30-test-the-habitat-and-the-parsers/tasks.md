# Tasks

Acceptance: none — these are tests and one promotion, with no behaviour change for a consumer to
drive; the tests are their own evidence.

## 1. [agent-build-kit] [tier1] Tests for the functions that read untrusted text

Needs: adapt-counts-the-units-own-tests group 1 — that change rewrites how a unit's tests are
derived, and testing the current reading would pin the behaviour it replaces.

Done when each function that interprets text the framework does not produce has tests over input of
the shape it meets, no test imports a private name, and the convention is written down.

- [x] 1.1 Test: the derivation of a unit's tests, over a diff whose context lines contain test
      definitions, counts only those the range defined, deleted or edited inside.
- [x] 1.2 Test: a successful run whose transcript contains the words of a usage refusal is not
      classified as refused; a real refusal is, with its reset time read where present.
- [x] 1.3 Test: a structured decision block missing one required entry is reported by that entry's
      name; a malformed block is reported rather than silently accepted.
- [x] 1.4 Promote the test-set derivation into its module's interface, named and documented with its
      contract — it answers which tests a commit range defined, deleted or edited inside — and have
      the adapt step call it by that name.
- [x] 1.5 Move any test that reaches a private name onto the public surface that uses it, or onto the
      promoted name.
- [x] 1.6 Record the convention beside the repository's other testing conventions in `CLAUDE.md`: a
      test reaches a public surface; behaviour worth pinning is either named or exercised through
      its caller.

## 2. [agent-build-kit] [tier1] One test of the environment a build runs in

Done when a commit made in a real worktree through the repository's own gate is covered by a test
that runs where integration tests run, and that fails with a useful name when a checker cannot see
the files.

- [x] 2.1 Test: in a real git worktree of a fixture repository, a trivially correct file is written,
      the repository's own gate is run, and the commit succeeds — with the test failing and naming
      the hook when a checker matches no files, and when the linter would reject what the formatter
      produces.
- [x] 2.2 Mark it to run where the framework's integration tests run, and exclude it from the default
      suite; confirm the default suite's runtime is unchanged.
- [x] 2.3 Say in `CLAUDE.md`, beside the test-tier conventions, that the habitat test exists and what
      it protects — the worktree, the real gate, and the workspace layout a build depends on.
