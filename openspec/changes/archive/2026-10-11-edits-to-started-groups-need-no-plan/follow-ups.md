## From `edits-to-started-groups-need-no-plan/2`

- `parse_plan` still lets a non-PlannerError out of the unit-reading loop (for example a non-numeric `estimated_lines` raises ValueError from `int(...)`). Such a refusal goes to the generic except branch in `plan_all` and records no reason. This was there before the change. Wrapping that conversion in a PlannerError would give every bad reply a recorded reason.
