# Design

## What moves

Only the defaults of the Claude Code runtime change. Resolution is as it was: an override from the environment, then the
runtime's own block, then the roles the flat block names, then the runtime's defaults. A flat block that names some roles
leaves the others to the runtime's defaults, which are now the new ones. A runtime that declares no names is not touched.

## The reason for two reviewers stays true

A rework has its own reviewer so that the model that made an edit does not judge it. With the new defaults the author is
`sonnet` for builds and for reworks, and the judge is `opus` for both, so the rule holds without a third model. The
documents say that the two reviews default to the same model, and that a configuration that sets the author to `opus`
should set the reviewer of its reworks to a different model.

## Documents

The `ModelsConfig` docstring and the comment on its `rework_review` field, the architecture document's list of design
decisions ("a rework is reviewed by a different model", near line 1030), the reference's models block and its comments, the runtimes document's example and the sentence that names the declared
names, the example in the configuration skill and the table row that lists the aliases are updated. The tests that pin the old defaults are updated with them, and the stub runtimes in the test support that declare
`ModelsConfig()` as their names take the new defaults without being edited. The overview example
already shows `sonnet` and `opus` and is left alone. The changelog says that the defaults changed and what an installation
that relied on them should do to keep its earlier models: name them.
