# Explicit exceptions

A core rule is the default for every app in this overlay. Where one app cannot meet a rule yet,
record it here. An exception is a dated, owned, reviewable record, never a silent deviation.

Rules for this file (checked by `scripts/check-exceptions.py`):

- One row per exception. `ID` is `EXC-` plus three digits and is never reused.
- `Rule` names the core doc and its section, for example `web-ui.md 0.1` (section 0, rule 1) or
  `web-ui.md 25`. The doc must exist in `standards-core/`.
- `Scope` names the app or path the exception covers. Never `all`: an exception for everything is a
  core change, so open a pull request against the core instead.
- `Review by` is required and at most 180 days after `Approved`. CI fails once it has passed.
  Renew it with a new date and a fresh reason, or fix the app and delete the row.
- A line of code that deviates on purpose carries the marker `core-exception: EXC-NNN` in a
  comment. CI fails when a marker names an ID that is not in this table.

| ID | Rule | Scope | Deviation | Reason | Owner | Approved | Review by |
|---|---|---|---|---|---|---|---|
