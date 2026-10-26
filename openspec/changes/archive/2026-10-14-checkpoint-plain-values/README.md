# checkpoint-plain-values

A unit's held state is stored in the graph's checkpoint as plain text, not as an enum, and a test fails if any value a
node returns would be stored as a type the checkpoint refuses.
