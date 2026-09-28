# JavaScript / TypeScript: tooling recommendations (seed)

> **This is a seed, not a verdict.** It is the framework's starting position
> for a JavaScript or TypeScript repo. `abk init`'s research step hands it to
> a model with web access, which validates every item against current
> practice as of the day it runs, keeps, amends or drops it with sources,
> settles the items marked *to be decided by research*, and writes the
> result to the planning repo's `docs/recommendations/javascript.md`. That
> file is what the proposals are written from; this one is only where it
> starts.

Each item states the rule, the tool and its version floor, why, and how to
check that a repo follows it.

## Formatting

- **Rule:** one formatter, run by pre-commit and CI, no per-file exceptions.
  **Tool:** *to be decided by research* — candidates: prettier (≥ 3) and
  biome (≥ 1.x, which formats and lints in one tool). Criteria: agreement
  with the chosen linter, speed on a monorepo, editor support, whether one
  tool can replace two.
  **Why:** formatting is not a review topic.
  **Verify:** the formatter's `--check` mode exits 0 in CI.

## Linting

- **Rule:** lint with oxlint using the react, typescript and oxc plugins,
  configured in `.oxlintrc.json` at the repo root.
  **Tool:** oxlint ≥ 1.x.
  **Why:** fast enough to run on every commit across a workspace; the
  plugins cover the framework-shaped mistakes without an eslint config tree.
  **Verify:** `npx oxlint` exits 0; `.oxlintrc.json` names the plugins.

## Types

- **Rule:** TypeScript with `strict: true` in every package, and project
  references between packages that depend on each other.
  **Tool:** TypeScript ≥ 5.x.
  **Why:** strict mode is where the checker earns its keep; references let
  `tsc --build` check a workspace in dependency order and keep each
  package's config small.
  **Verify:** every `tsconfig.json` has `"strict": true`; `npx tsc --build
  --noEmit` (or `tsc --noEmit` per package) exits 0.

## Test layout & tiers

- **Rule:** one test runner across the workspace; tests live beside the code
  they test as `*.test.ts` or under `__tests__/`, and tests needing a real
  service are separated by a name or directory the runner can select on.
  **Tool:** *to be decided by research* — candidates: vitest (≥ 2) and
  `node:test` (built in). Criteria: TypeScript without a build step, watch
  mode, workspace-aware runs, coverage, mocking at module boundaries.
  **Why:** one runner means one way to read a failure.
  **Verify:** `npm test --workspaces` passes on a fresh checkout with no
  services.

- **Rule:** no test calls a live website; recording a fixture and replaying
  it is fine, and the test names the source of the recording.
  **Tool:** convention.
  **Why:** a live call is flaky and unreviewable.
  **Verify:** the suite passes with the network unavailable.

## Packaging & workspaces

- **Rule:** one npm workspace per repo; each package has its own
  `package.json`, scripts run per package with `--workspace`.
  **Tool:** npm ≥ 10 (`workspaces` in the root `package.json`).
  **Why:** one lockfile, one install, per-package scripts.
  **Verify:** `npm ci` succeeds from the root; `npm run <script>
  --workspace <pkg>` works for every package.

- **Rule:** frontends build with vite.
  **Tool:** vite ≥ 5.
  **Why:** a fast dev server and a build with no bespoke configuration.
  **Verify:** `npm run build --workspace <frontend>` produces `dist/`.

## Configuration & types conventions

- **Rule:** a wire type shared by two packages lives in one shared package
  both import, never copied.
  **Tool:** a workspace package for shared types, referenced via project
  references.
  **Why:** two copies drift; the checker only sees one.
  **Verify:** no duplicate type name across packages.

- **Rule:** runtime configuration is read in one module per package, with
  every variable named and validated there.
  **Tool:** convention (a schema library is optional).
  **Why:** one place to see what a package needs.
  **Verify:** `process.env` is referenced only in that module.

## Pre-commit

- **Rule:** the formatter check, oxlint and `tsc --noEmit` run before every
  commit and in CI, from one config.
  **Tool:** *to be decided by research* — a pre-commit framework (pre-commit
  ≥ 4 with local hooks, or husky + lint-staged). Criteria: whether the repo
  already runs Python's pre-commit, speed on staged files only.
  **Why:** one gate the developer and CI both run.
  **Verify:** the hook runs on a commit with a lint error and refuses it.

## CI

- **Rule:** tier 1 runs on GitHub Actions on every pull request and on
  pushes to the default branch: one job per package running lint, types
  and tests; `npm ci` guards the lockfile.
  **Tool:** GitHub Actions with `actions/setup-node` and npm's cache.
  **Why:** a per-package job reports which package broke; `npm ci` fails on
  a lockfile out of step with `package.json`.
  **Verify:** `.github/workflows/ci.yml` has the jobs; a PR with a type
  error goes red.
