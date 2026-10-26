# Design

## Grammar

`INDEPENDENT_LINE` is `Independent: <reason>` on a line inside a group, parsed
beside `Separate:` and `Needs:` in `work_graph`. The reason is the text after the
colon and must be non-empty. The group record gains an `independent` flag.

## Planning

`units.py` builds units by walking groups, flushing a unit at a repo change or a
size limit and linking each flushed unit to `units[-1]`. With the flag:

- an independent group always flushes the unit in progress first and becomes a
  unit of its own that is flushed immediately, so nothing is joined to or from
  it;
- its `depends_on` is empty;
- the next unit's `depends_on` is the last unit that was not independent, found
  by keeping a separate `chain_tail`;
- a `[narrow]` or `[acceptance]` unit depends on every unit of the change that
  precedes it, which is already the intent of those flags and is what the
  independent group must not weaken.

A change with no `Independent:` line plans exactly as before.

## Cross-change effects

`link_needs`, `merge_before` and base selection look at `depends_on` only, so an
independent unit stacks on nothing and starts on the trunk. A later `Needs:` from
another change onto an independent group resolves to its unit like any other.

## Validation

`abk tags` reports: a missing reason; the line on group 1; the line with a
contract, narrow or acceptance flag. An independent group that also carries
`Needs:` is fine: it still waits for what it names.

## Out of scope

Expressing a partial order beyond independent-or-chained (group 4 needs only
group 2, say) is left to `Needs:` between changes; this keeps one flag, not a
dependency language.
