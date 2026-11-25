# Tools

Small command line tools a consumer's repository uses beside the ops center. Stdlib Python 3.9, configured by a JSON file named by an
environment variable, no default naming an estate.

| Tool | What it does | Config | Tests |
|---|---|---|---|
| `livepath.py` | Maps repo relative paths to the live paths the running install reads them from (the inverse of an export script); unmapped paths are skipped | `LIVEPATH_MAP` (`[[repo prefix, live prefix], ...]`) | `livepath_test.py` (2) |
| `changelog.py` | Generates and validates per pull request changelog entries (`## [#N] YYYY-MM-DD - Title`, `Downstream:`, `Areas:`, one section per area, append only history, an overlay sync needs no entry): `check`, `new`, `areas` | `CHANGELOG_TOOL_CONFIG` (`areas`, `area_rules`, `consumer_areas`, `sync_overlay`, `sync_paths`, `sync_workflows`, `skills_prefix`) | `changelog_test.py` (8, on scratch git repositories) |
| `upgrade.py` | The consumer upgrade step: copies the built app and the server into a service location (tests, sources and node_modules left out), keeps the replaced copy as `opscenter.prev`, restarts the service and polls a smoke url, or with `--base-url` checks health, the route count and the page and its assets, and refuses a target inside a macOS protected folder (Documents, Desktop, Downloads) a launch agent cannot read. A failed restart or smoke check puts the old copy back and exits 1 | flags only: `--target`, `--source`, `--restart-cmd`, `--smoke-url`, `--base-url`, `--min-routes`, `--allow-protected`, `--timeout`, `--dry-run` | `upgrade_test.py` (13) |
| `settings_inventory.py` | Lists every environment variable the ops center code reads, with its default and where it is read, into `opscenter/SETTINGS.md` (`--write`), and fails when that file is stale (`--check`) | none, reads the source | `settings_inventory_test.py` (7) |
| `ci_tests.py` | Runs the unit tests of a tree for CI, one process per file, so a module level fixture never leaks into the next file; a live-state skip list printed on every run; listed proof tests that must exist | `ci-tests.json` in the root (`folders`, `patterns`, `live_state`, `proofs`, `timeout_s`) | `ci_tests_test.py` (6) |

The core's own changelog uses a different format (`checks/check-changelog.py`); this tool is for a consumer repository that keeps one
entry per pull request.
