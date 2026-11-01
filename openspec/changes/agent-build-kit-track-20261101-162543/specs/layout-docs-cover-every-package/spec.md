## ADDED Requirements

### Requirement: The layout block names every source package

The layout block of `AGENTS.md` SHALL name each directory package under `src/agent_build_kit/`
and the `docs/designs/` folder.

#### Scenario: A package missing from the block
- **WHEN** a package directory exists under `src/agent_build_kit/` and the layout block does not name it
- **THEN** the documentation test fails naming the package
