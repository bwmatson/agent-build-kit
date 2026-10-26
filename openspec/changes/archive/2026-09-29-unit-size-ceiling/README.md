# unit-size-ceiling

Cap how much work the planner may put in one unit: a configurable ceiling,
default 1000 estimated lines, respected where units are shaped.

`min_unit_lines` has always been a floor, so that a chain of small task groups
does not become a stack of trivial PRs. Nothing has ever been a ceiling, and a
reviewer's attention is the scarcest thing in this pipeline.

This is a planning cap and nothing else. Nothing is measured at push time and no
unit is stopped for being large — see the design for what that deliberately
leaves uncaught.
