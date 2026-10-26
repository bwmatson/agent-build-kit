# build-prompts-name-the-profiles-test-and-lint-commands

A headless build agent cannot ask for approval, and the build prompts never say which test and lint commands the allow-list
permits, so an agent in a repo with no instruction file picks refused ones (`python -m pytest`, bare `ruff`), cannot verify its
work and loses the tests-first order. A toolchain profile now names its agent commands, a repo can replace them with
`repos.<name>.agent_commands`, each must match the build allow-list (refused at load, reported by `abk doctor`), and the six full
build prompts carry a section under 600 characters filled from them. Priority 0.
