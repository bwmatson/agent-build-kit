# Category: Module design (deep vs. shallow interfaces)

Weekly-cadence category (run via `recommend.md`). Distinct from
`technical-debt.md`: that category asks "does this need cleanup"; this one
asks a narrower, sharper question — is a module's *interface* pulling its
weight relative to what it hides? (See Ousterhout, *A Philosophy of Software
Design*, ch. 4: a deep module has a simple interface over a lot of hidden
complexity; a shallow one has an interface about as complex as what it does.)

- **Interface-mirrors-implementation classes**: a class whose public methods
  are mostly one-line getters/setters, one per internal field, with little
  real behavior behind any of them.
- **Thin pass-through wrappers**: a function whose body is a near-direct call
  to something else, adding no real abstraction — only worth flagging when it
  has enough call sites that the wrapper's *cost* (one more thing to learn)
  isn't already justified by hiding something real (an external CLI's argv
  shape, a test seam).
- **Information leakage across a module boundary**: callers reaching into a
  module's internal/nested shape directly (a config's nested fields, an
  internal enum's exact string values duplicated as a literal instead of
  imported) instead of going through something that module exposes on
  purpose.
- **Repeated read-modify-write or setter boilerplate**: several methods on
  the same class that differ only in which field they touch, each
  re-implementing the same surrounding mechanics.

Be conservative, same bar as `technical-debt.md`: only report something
concrete enough that a specific person would immediately see what to change
and roughly how big it is. Calibrate bounded vs. not the way `implement.md`
expects: a fix is bounded when it changes a module's own internals without
changing its callers' signatures (collapsing duplicated logic behind one new
private method, replacing a hardcoded literal with an existing constant,
adding one accessor a caller that already holds the right object can start
using). It is **not** bounded — recommend it, don't propose it as a
candidate — when "fixing" it would mean threading a new parameter through a
module that's deliberately pure or built from injected callables (check
whether its own docstring says so), since that reshapes an interface other
code already depends on and is a design decision, not a mechanical fix.
