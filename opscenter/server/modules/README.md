# Server modules

One stdlib Python module per page or lane backend (opscenter/DESIGN.md section 12.3). State lives under
`OPSCENTER_STATE_DIR` (default `~/.opscenter/state`); a module never writes outside it.

| Module | What it does | Tests |
|---|---|---|
| `dark_launches.py` | Dark launches: acting automation ships with its switch (a code host variable) off. Run a dry run, Enable (typed variable name, newest dry run green, read live), Disable (always allowed). Registry `dashboard/dark-launches.json`, append only log `dashboard/dark-launches-log.jsonl`. A failed read is `unknown`, never `off` | `dark_launches_test.py` |
| `own_lane.py` | Read only view of the own pull request lane per review lane: freshness, the lane's record for a head, held and covered rules, and what auto-fix is doing | `own_lane_test.py` |
| `decision_cards.py` | The one writer of the lane's direction and sign-off files: a click on a decision card option is a sign-off for that head only (fix, hold or override with the triage marker); head pinned, owner only, delete rules never signed off | `decision_cards_test.py` |
