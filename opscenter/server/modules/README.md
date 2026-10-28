# Server modules

One stdlib Python module per page or lane backend (opscenter/DESIGN.md section 12.3). State lives under
`OPSCENTER_STATE_DIR` (default `~/.opscenter/state`); a module never writes outside it.

| Module | What it does | Tests |
|---|---|---|
| `dark_launches.py` | Dark launches: acting automation ships with its switch (a code host variable) off. Run a dry run, Enable (typed variable name, newest dry run green, read live), Disable (always allowed). Registry `dashboard/dark-launches.json`, append only log `dashboard/dark-launches-log.jsonl`. A failed read is `unknown`, never `off` | `dark_launches_test.py` |
