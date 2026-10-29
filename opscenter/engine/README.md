# Engine

The cost gated analyzer's deterministic parts (opscenter/DESIGN.md section 2.6 and 12.4). None calls a model.

| Module | What it does | Tests |
|---|---|---|
| `contract.py` + `board.schema.json` | The item contract for the analysis job's one output file: required fields and types, priority set, unique keys, no reserved prefix (`oo-`, `file-`, `auto-`), and every must consider source id covered by an item or a drop reason. `settle(dash)` validates the file on every refresh; a bad file is rejected, the last good file is restored in its place, the streak is recorded for the wake gate's backoff | `contract_test.py` |
| `handled.py` | Deterministic match between board items and the owner's Resolve, Ignore and Snooze decisions: a dismissed item stays dismissed until there is new source evidence; ignored forever never returns; unknown evidence never hides a resolved item | `handled_test.py` |
| `first_seen.py` | The time an item first reached the board, from data the model cannot rewrite, inherited across re-keyed repeats | `first_seen_test.py` |
| `applied_log.py` | One answer to "is this docs proposal finished": only when a recorded outcome covers this content (body hash), so a corrected re-stage of a page shows again | (covered by the proposal gate tests) |
| `publish_mode.py` | Per class publish mode for docs proposals (`staged` by default, `auto` set only by the owner): the append only check against the live page, classification, version and history links, the daily digest | `publish_mode_test.py` |
| `state_extract.py` | Read only parsers that mine the markdown and JSON state files for the analysis bundle | |

| `routing.py` + `fixtures/routing-seed.json` | The routing engine: where each candidate or board item belongs (`action_center`, `analysis`, `elsewhere`, `nowhere`) from rules that are data (`ac-routing.json`), first match wins, click rules insert at the top, a person who addressed the owner directly is considered by default (fail open), a broken file raises so a caller keeps every item | `routing_test.py` (22) |
| `collect.py` | The collector: one candidate shape for every source (mail feed, chat feeds, tracker snapshot, state files, documentation gaps), routed by `routing.py`, with the routing report and the unregistered source ratchet. Every path and name is a parameter (`OPSCENTER_COLLECT_CONFIG`); the roster, extra board items and the ref check are plug-ins | `collect_test.py` (12) |
| `analysis_bundle.py` | The analysis job's input: must consider candidates, context (capped per source), routed away, items already on the board, people, handled decisions, the previous synthesis and the optional live ref status. A broken routing file fails the build, so the gate fails open | `collect_test.py` |
| `board_build.py` | The board composer and the bundle step: the contract check, items the ops center adds itself, the routing filter, handled aliasing, first seen stamps, fingerprints, freeze status, monitors, the team away strip. Writes the app's data files | `board_build_test.py` (8) |

| `ref_status.py` | The live ref check plug-in (`OPSCENTER_REF_STATUS`): the state of the pull requests and tracker tickets a text names (`resolve`), the finished ones (`done_lines`), and which automation cards have no cause left (`finished`), including the approve the apply check. Read only through `gh` and a tracker driver; repositories, key pattern and driver are parameters (DESIGN.md 12.18) | `ref_status_test.py` (20) |
| `doc_audit.py` | The daily documentation audit (rules R1 to R12, the gap store, the surface slice), configured by `DOC_AUDIT_CONFIG` and reading the docs home through `DOCS_HOME_CMD` (DESIGN.md 12.26) | `doc_audit_test.py` (17) |

Plug-ins are files named by environment variables (`OPSCENTER_PEOPLE`, `OPSCENTER_BOARD_SOURCES`, `OPSCENTER_REF_STATUS`,
`OPSCENTER_TEAM_AWAY`), each optional; DESIGN.md 12.13 lists their contracts.
