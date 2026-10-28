# Engine

The cost gated analyzer's deterministic parts (opscenter/DESIGN.md section 2.6 and 12.4). None calls a model.

| Module | What it does | Tests |
|---|---|---|
| `contract.py` + `board.schema.json` | The item contract for the analysis job's one output file: required fields and types, priority set, unique keys, no reserved prefix (`oo-`, `file-`, `auto-`), and every must consider source id covered by an item or a drop reason. `settle(dash)` validates the file on every refresh; a bad file is rejected, the last good file is restored in its place, the streak is recorded for the wake gate's backoff | `contract_test.py` |
| `handled.py` | Deterministic match between board items and the owner's Resolve, Ignore and Snooze decisions: a dismissed item stays dismissed until there is new source evidence; ignored forever never returns; unknown evidence never hides a resolved item | `handled_test.py` |
| `first_seen.py` | The time an item first reached the board, from data the model cannot rewrite, inherited across re-keyed repeats | `first_seen_test.py` |
| `applied_log.py` | One answer to "is this docs proposal finished": only when a recorded outcome covers this content (body hash), so a corrected re-stage of a page shows again | (covered by the proposal gate tests) |
| `state_extract.py` | Read only parsers that mine the markdown and JSON state files for the analysis bundle | |

Not lifted yet: `routing` (needs the collector module), the bundle builder, `ref_status` (tied to named repositories) and
`publish_mode` (tied to one docs home layout).
