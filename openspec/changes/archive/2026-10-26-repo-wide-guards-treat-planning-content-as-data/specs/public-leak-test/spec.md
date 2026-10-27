## MODIFIED Requirements

### Requirement: The structural leak test also reads planning content

The framework's term-free leak test SHALL also scan `openspec/`, the committed `abk.yaml` and the tracked unit store file (when present)
with its home-path, slug, anecdote and product-directory checks, and SHALL report each hit as a path, a line number and a clipped line.
It SHALL read the specification folder through the shared guard helper.
It SHALL NOT scan ignored state (`runs/` apart from the unit store, logs, ledgers).
In the specification folder a tilde-relative path (`~/` followed by anything) SHALL NOT be a home path, because it names no user; an absolute
home path (`/home/<name>`, `/Users/<name>`) SHALL still fail there, and every other scanned file keeps the full rule.

#### Scenario: A home path in a spec

- **GIVEN** a file under `openspec/` containing a home-directory path
- **WHEN** the test runs
- **THEN** it fails naming the file and line

#### Scenario: A tilde example in a spec

- **GIVEN** a file under `openspec/` containing `repos.app.path: ~/work/app` as an example value
- **WHEN** the test runs
- **THEN** it does not fail for it, and the same text in `docs/` does

#### Scenario: A foreign slug in the config

- **GIVEN** an `abk.yaml` containing a code-host URL of an owner that is not a fixture
- **WHEN** the test runs
- **THEN** it fails naming the file and line

#### Scenario: Ignored state is not read

- **GIVEN** a home path in a run log under the state directory
- **WHEN** the test runs
- **THEN** it does not fail for it

#### Scenario: No planning content

- **GIVEN** a checkout with no `openspec/`, no `abk.yaml` and no store file
- **WHEN** the test runs
- **THEN** it passes and does not fail for the missing paths
