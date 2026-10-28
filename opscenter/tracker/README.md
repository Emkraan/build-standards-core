# Work tracker

The work tracker hub and the three jobs that sit on it (opscenter/DESIGN.md sections 12.3 item 18 and 12.15). One adapter
module, `work.py`, runs every call through a driver command; everything else reads the tracker through it.

| Module | What it does | Tests |
|---|---|---|
| `params.py` | The tracker parameters (site, browse URL, driver, project, team clause, field ids, change query, owner, intake epic, retro settings): one JSON file, `OPSCENTER_TRACKER_PARAMS`, every key optional | used by all |
| `work.py` | The adapter: the active sprint, the Sprint and Backlog views, the guarded writes (sprint move and remove, status transitions that never close, each confirmed on read-back and limited to the owner's own items), and the changes pending the owner's approval. A stale while revalidate cache; a failed read raises `TrackerError`, never an empty page | `work_test.py` (8) |
| `driver.py` | The reference driver (a minimal JSON-RPC client for a tracker MCP connector, token file and endpoint from the environment). A consumer with another tracker or sign-in supplies its own with the same command line | covered through `work_test.py`'s fake driver |
| `needs_me.py` | The Needs me tab: active-sprint tickets the nightly close-out could not settle; the owner's Close or Keep open decision is the only thing this module writes, the close-out applies it | `needs_me_test.py` (8) |
| `ticket_progress.py` | For each active project tracker: when the work ticket has had no comment for three working days and the tracker has newer entries, one Action Center card with a drafted progress comment (deterministic first, then an optional model command, every draft linted); Post re-reads right before the write, Dismiss records what it covered. Intake tickets are never commented | `ticket_progress_test.py` (45) |
| `retro_row.py` | Drafts the owner's row of the sprint retro page from the sprint facts and writes only that row after the owner's approval (version re-checked, read back, backup kept); autonomy (`auto_write`) is the owner's call | `retro_row_test.py` (9; the snapshot had none) |

The retro row wake gate is `../gates/retro_row_gate.py`. The contract of the driver and the parameters are DESIGN.md 12.15.
