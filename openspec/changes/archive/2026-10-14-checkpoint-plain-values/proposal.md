# Proposal

## Why

Every time a unit is held, the tick log says a type is "not in the allowed modules" and was blocked from deserialisation.
The held node stores the state it holds as an enum member. The checkpoint encodes it with its class's module path, which
is not on the list of types a checkpoint may load, so on reading it back the library logs a warning and returns the
underlying text. Nothing is lost today, because the field is typed as text, it is only written, and routing uses
something else. But the stored value is tied to a class's path, so a newer release that adds or moves a member would be
read by an older one as a bare string or fail, and the warning will not stay harmless.

The tests of the allowed list missed it: they walk the types a state class declares, and never run the nodes that return
values for it.

## What Changes

- **The held state is stored as text:** the value of the enum, not the enum.
- **The checkpoint test covers what nodes return:** every update a node returns, and every field of the state with a
  populated value, is run through the real serializer with the allowed list, and the test fails if any value would be
  blocked.

## Impact

- agent-build-kit: one line in the held node and one test. Checkpoints that already hold the enum keep loading, as plain
  text.
