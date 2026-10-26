## From `blocked-units-free-their-slot/1`

- docs/architecture.md: the reflowed units-in-progress paragraph now has one line much longer than the lines around it ('...changed state), which stays planned until the other units in progress are below the limit. A rework, resume, restack, review'). Rewrap it to match the paragraph's width.
- units.py `_parent_went_back` also returns True when a same-repo predecessor that was already in review is restacked or given a review round after the dependent paused, because that puts the predecessor through PLANNED/RUNNING. That agrees with `blocked()`, since the dependent's `waiting_on` covers that predecessor meanwhile. Pinning it with a test, or a sentence in the docstring, would stop a later reader from taking it for a false positive.
