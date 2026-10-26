# Design

## Why not allow the enum

Allowing the enum's module and name would silence the warning and keep the coupling: the checkpoint would hold a class
path, and a release that renames or moves the class could not read a checkpoint written by another. The enum is put there by `BuildPath.hold()` (`hold_state` in the update it returns, from the state it was given); the field is
already annotated as text and nothing reads it as an enum, so storing the text is both the smaller change and the one that survives versions.
The unit store takes the same direction, reading its own old and newer fields as plain data.

## The test

The existing test (`tests/graph/test_checkpoint_allowlist.py`) builds a state with every declared field filled, from the
annotations, and writes it through the real serializer. It does not run nodes, and an annotation of `str` is filled with
text, so an enum that a node returns for such a field is never seen. The new test drives the paths of `BuildPath.hold()` with a fake runner, collects
each update it returns, serialises it with the allowed list, and fails if any value is encoded as a type outside the
list. A second check serialises a populated state, so a value assigned later with a type its annotation does not
mention is also caught. The check inspects what is encoded, not only whether a warning was logged.

## Old checkpoints

A checkpoint that already holds the enum is read back as the text by the library, which the field accepts. Nothing is
rewritten and no migration is needed.
