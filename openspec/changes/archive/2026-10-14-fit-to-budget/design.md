# Design

## The cuts

`cut_head`, `cut_tail` and `cut_middle` take a text, a size and a boundary (character, line or paragraph) and a marker. Each
returns the text unchanged when it fits, never returns more than the size, and closes an open code fence and any collapsible
block it leaves open. The logic that the general description cut has for closing them moves here, and that cut becomes a thin
wrapper that keeps its tests.

## The fitter

A section has a key, a way to render itself at a given size, its natural size, its smallest honest form, a weight, an optional
ceiling, and whether it is required. Required sections are never shrunk below their smallest form and never dropped.

To fit a budget:
1. If every section fits at its natural size, capped by its ceiling, with its separators, render them all in full.
2. Otherwise give every section its smallest form. If these alone are over the budget, drop sections from the lowest weight
   up, never a required one; if the required ones alone do not fit, the final guard cuts.
3. Share the rest by weight. Each unsaturated section's target is its smallest form plus its weighted part of what is left. A
   section whose natural size is below its target is saturated at that size, and what it did not use goes back to the others.
   Repeat until no section is newly saturated.
4. Render each section at its allocation. A marker or a closing fence can add to what a section returns, so the total is
   checked; any overshoot is taken from the section with the most room and the sections are rendered again, up to three
   times.
5. The general cut at a line boundary stays as the final guard, so a host's limit always holds.

The result is deterministic: ties go to the earlier section.

## The limit, once

Each host already declares its description limit (`description_limit` on the forge protocol), and each host's create and
update already cut a description with `fit_description`; what is new is that the cut is made once, to the lowest limit,
and no host cuts. The base of the forge layer works out the effective limit as the lowest of those across the registered
hosts, so a host added later with a lower one lowers it, and exposes it. The description is fitted once, where the
pipeline hands it to a forge: the open-pull-request step that builds the body passes the effective limit to
`build_pr_body` in place of the one host's `description_limit` it passes today, and the per-host calls in each host's
create and update are removed.

A status description has no declared limit today: each host cuts the raw string to a number of its own. Each host
declares a `status_limit` alongside `description_limit`, set to what its cut allows now, and the cut inside the host's
status call is removed. Status descriptions are fitted to the lowest status limit across the hosts, where the pipeline
builds them, the same way.

## The description

The position, scope, assumptions, restack note, held points and footer are required. The test output has weight one; its
smallest form keeps the pass or fail line and says it was trimmed, and it renders by keeping the tail on a line boundary. The
follow-ups have weight two; their smallest form is the count of those left out, and they render as whole items followed by
"and N more". What was true before still is: a description that fits is unchanged, the tail of the output is kept and its head
dropped, items are whole and in order, and the verdict and the headings survive.

## The test output

The test output of a unit is made of one section per command. A failed command weighs more than a passing one. Within a
failed command the output keeps, for each failed test, its identifier and its error lines first, then the remainder, so the
saved failure names every test that failed and why even when the log is long. The profile that reads test output provides the
failed tests; one that does not keeps the tail as before.

## The other users

The earlier rounds shown to a reviewer become sections of findings, with open findings required as they are never dropped
today. Single-string cuts elsewhere call the shared cuts, keeping what they keep.
