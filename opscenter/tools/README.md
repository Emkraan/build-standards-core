# Tools

Small command line tools a consumer's repository uses beside the ops center. Stdlib Python 3.9, configured by a JSON file named by an
environment variable, no default naming an estate.

| Tool | What it does | Config | Tests |
|---|---|---|---|
| `livepath.py` | Maps repo relative paths to the live paths the running install reads them from (the inverse of an export script); unmapped paths are skipped | `LIVEPATH_MAP` (`[[repo prefix, live prefix], ...]`) | `livepath_test.py` (2) |
| `changelog.py` | Generates and validates per pull request changelog entries (`## [#N] YYYY-MM-DD - Title`, `Downstream:`, `Areas:`, one section per area, append only history, an overlay sync needs no entry): `check`, `new`, `areas` | `CHANGELOG_TOOL_CONFIG` (`areas`, `area_rules`, `consumer_areas`, `sync_overlay`, `sync_paths`, `sync_workflows`, `skills_prefix`) | `changelog_test.py` (8, on scratch git repositories) |

The core's own changelog uses a different format (`checks/check-changelog.py`); this tool is for a consumer repository that keeps one
entry per pull request.
