# People slot

The optional people module (opscenter/DESIGN.md sections 12.3 item 19 and 12.14): the 1:1 board, the team away strip and
the yearly review store. It is off by default (`modules.json`), its data stays local and is deleted after
`people.retention_days`. Stdlib Python 3.9 except the yearly export, which imports python-docx lazily (the one declared
exception, DESIGN.md 12.6). No name, address, zone or tool of an estate is in the code: one parameters file
(`OPSCENTER_PEOPLE_PARAMS`, default `<state>/people-params.json`) holds the owner, the roster and the adapter commands.

| Module | What it does | Tests |
|---|---|---|
| `one_on_ones.py` | The 1:1 board: per-person topics harvested from the chat and mail feeds, the weekly assessment and the owner's agenda (a ledger keeps them past the feeds' rolling window), statuses, manual topics, the next 1:1 per person from the calendar, availability and scheduling through the meetings slot, the roster slot with a last good copy, and the board items for the Action Center | `one_on_ones_test.py` (11), `people_slots_test.py` (9), `identity_roster_test.py` (11) |
| `team_away.py` | Who on the team is out today and in the next two weeks (times only), from the meetings slot's `away` command; the last good result is kept with an error note when a read fails | `team_away_test.py` (4) |
| `yearly_reviews.py` | Year keyed review records per person: edits with versions and undo, steer text, reset snapshots, final lock, drafting jobs through the consumer's drafter command, the `.docx` export | `yearly_reviews_test.py` (9, the export is skipped without python-docx) |

The adapters (the four slots) are commands and files named in the parameters; each has a null default, so the board
renders from what is configured and says what is unavailable. The contracts are DESIGN.md 12.14.
