# Ops Center Layout Standard

Version: 1.2 | Last reviewed: 2026-11-01 | Status: current | Scope: local-ops (operator consoles)

How an ops center is organised and how it starts work: what a hub is, how its items are grouped, what
the Overview shows, where every count comes from, and what a Run button promises. The ops center
layout was approved by its owner on 2026-10-30 and is the standard for every ops center. This doc is
the source of truth. Where a reference implementation differs, the implementation is fixed, or the
consumer records an explicit exception (README, "Source of truth and explicit exceptions").

Related: [Local Ops App](local-ops-app.md) (the server, the problem list, the polling budget),
[Live Actions](live-actions.md) (what an action does to the object it acts on),
[Web Design System](web-ui.md) (tone, tabs, dialogs), [Automation Safety](automation-safety.md)
(dry run first, re-verify before acting).

---

## 1. Rules

1. **Group by what we run, never by data source.** One hub per domain, with a tab per thing operated. Related operational views are not split across pages by where their data comes from (builds on one page, infrastructure on another).
   - Prevents: an operator hunting across pages for one system's state.
   - Acceptance (review): every hub names a domain and each of its tabs is a thing operated in it; no two hubs show the same kind of item.
2. **Sections when a hub has more than about five items.** The top row is Overview plus titled sections; the second row is one tab per item in the open section. The route shape is `/<hub>/<section>/<item>`. The Overview groups its cards under the same section titles in the same order.
   - Prevents: a single row of fifteen tabs nobody can scan, and an Overview that orders things differently from the tabs.
   - Acceptance (review): a hub with more than five items has the two rows and the three-part route, and the Overview section titles and order equal the section tabs.
3. **The Overview is one card per item.** A card shows a tone pill (healthy, worth a look, needs me), a one-line headline that leads with the item's live facts (versions, runners online, spend against the projection, not a bare "Healthy"), at most four detail lines, and a link to its item.
   - Prevents: an Overview that is a second copy of every page.
   - Acceptance (test): a UI test renders the Overview for a fixture of items and asserts one card per item, a tone pill on each, no card with more than four detail lines and a link on each card.
4. **One source of truth for counts.** The rail badge, the section and item tab counts and the Overview all read one server-side problem list, counted one per problem line (two failing jobs and a stale heartbeat read 3). The client applies no thresholds of its own. Work in progress shows as a spinner, never red, on any item.
   - Prevents: a badge, a tab and a card that disagree, and a red mark for a job that is simply running.
   - Acceptance (repo check RC023): no client source decides a tone, badge or severity from a count compared with a number; a test asserts the badge, tab and Overview counts equal the server list, and that an item with three problem lines counts 3.
5. **Current state and history are different things.** A pipeline counts as failed only while its newest finished run on the default branch failed. Older runs fold under History, so a fixed failure never reads as current.
   - Prevents: a red mark that stays until the operator dismisses a failure that was fixed an hour ago.
   - Acceptance (test): with a fake code host whose newest finished run succeeded after an earlier failure, the problem list has no item for the pipeline and the page shows the failure only under History.
6. **Newest first everywhere.** Cards are ordered by latest activity with running items on top, runs by finish time, scheduled jobs by last run.
   - Prevents: the thing that just broke sitting under a list of things that did not.
   - Acceptance (test): a UI or server test with items out of order asserts the order.
7. **Every runnable thing has a start button in the UI.** Pipelines (Run workflow), scheduled jobs (Run now) and maintenance tasks (a backup, a restore drill) can be started from the item. The form opens with safe defaults (dry run on), says plainly when a run will publish, and the primary button then reads "Run for real". The contract in section 3 is the server side of the button.
   - Prevents: an operator opening a second tool to start what the console already shows, and a click that publishes by accident.
   - Acceptance (test): a UI test opens the form and asserts the dry run default and the changed button label; a server test covers each refusal of section 3.
8. **Name hubs for the work, not the vendor or the tool.** "Work tracking" instead of the tracker's name, "Pull requests" instead of "Reviews". The tool name stays in subtitles and links.
   - Prevents: a rail that has to be renamed when a tool is replaced.
   - Acceptance (review): no hub, section or tab title is a vendor or tool name.
9. **Old links never break.** Every renamed or moved route redirects to its new home and keeps its tab and query string. The app keeps a lock file listing every route it has ever served.
   - Prevents: a bookmark, a link in a ticket or a notification that lands on a blank page after a reorganisation.
   - Acceptance (repo check RC024): every route in the lock file is still routed (a redirect counts) and every routed path is in the lock file; a test follows each redirect and asserts the tab and query string survive.
10. **A gate override is scoped, time-boxed and fails closed.** The expiry is stored with the entry and compared on every read, and a missing, unreadable, foreign-scope or expired store means no override. It lifts only its own gate, covers only the owner's own work, and has one writer and one log, confirmed first.
   - Prevents: an override that outlives its window, one that survives a broken file, or one that lifts more than the gate it was made for.
   - Acceptance (repo check RC025): no override reader returns a pass from an error handler, and no scheduled job clears an override; a test proves a missing, unreadable, foreign-scope and expired store each mean no override (`override_store.py`, `override_store_test.py`).
11. **A card never shows a stale reason after an action.** Until the next pass of whatever re-checks it, the card says what happens next (for example "freeze bypassed, the lane re-checks within 3 minutes"), never the reason the action just removed.
   - Prevents: a card that carries a new tag next to the old held line, so the owner cannot tell whether the action worked.
   - Acceptance (test): a UI test acts on a card that is held, and asserts the held reason is gone and the pending next step is shown until the next pass replaces it. `pending_line` in `override_store.py` is the server wording.
12. **Known transient failures heal themselves and never count as failures.** Each known transient failure has a defined automatic recovery (a stale saved plan is re-planned at once). Only a failure that was not recovered reaches the owner or a repeat counter; real failures keep the normal path.
   - Prevents: an alert and a red card for something the ops center could have fixed itself in a second.
   - Acceptance (test): a test makes the known failure happen and asserts the recovery ran, a clean result clears the card and closes the repeat alert, a result with changes asks for one review, the failure never counts toward the repeat alert, and a real failure still takes the normal path (`owner_roots_test.py`, `StaleSavedPlan`).

---

## 2. The sectioned hub

The hub header has two rows: the first row is Overview and the section titles, the second the item tabs of the open section. A section is declared once, as data (key, title, items), and the header, the routes, the Overview and the counts are all derived from that one list, so they cannot drift apart. The route is `/<hub>/<section>/<item>`; `/<hub>` and `/<hub>/<section>` open the Overview and the section's first item. A hub with five or fewer items may stay a single row.

## 3. The run contract

A Run button queues work; it never decides it. The server side is fixed and the same for a pipeline, a scheduled job and a maintenance task:

1. **A fixed input spec per item.** The server holds, for each runnable thing, the inputs it accepts: name, type (boolean, choice, text or number), default, allowed values and whether a value publishes or changes something. The dialog is drawn from the same spec. Defaults are the safe ones (dry run on).
2. **Unknown inputs are refused.** An input not in the spec, or a value outside its allowed values, is refused with a 400 that names it. Nothing is dispatched.
3. **Same origin, loopback only.** The write is refused unless the request is same origin and the server is on loopback (the server gate of [Local Ops App](local-ops-app.md) section 6).
4. **Double clicks are deduplicated.** The same item with the same inputs inside a short window returns the run that is already queued instead of starting a second.
5. **Refusals say why.** An item that is paused, or already running, is refused with a 409 and a reason the dialog shows.
6. **The button only queues.** An environment approval still gates any job that writes; a run for real asks for the same approval a push would.

## 4. The problem list

One server function builds the list: each item has an id, the hub, section and item it belongs to, a tone (healthy, worth a look, needs me), a one-line headline and up to four detail lines. The rail badge, the section and item tab counts and the Overview read it and nothing else, so a number can only be wrong in one place. A pipeline is an item only while its newest finished run on the default branch failed; a running pipeline is an item with a running state and no failure tone. The list is cached on the server's polling budget ([Local Ops App](local-ops-app.md) section 15) and a client never recomputes it.

The count of an item is its number of problem lines, never one per item, and the list carries the total (`lines`, the rail badge) so the badge, the section counts and the item counts always add up. The headline of an item is the live facts of what it runs; the provider of the list fills it. An item may be running whatever its area; the flag draws a spinner and never a tone. A consumer adds its own problem sources through the problems provider slot instead of changing the list: a source for what is waiting on the owner (a refused deploy that needs a click, a run waiting on an approval) and one for what is worth a look (spend headroom at 70 percent or more, an account that could not be read). A source whose item already exists adds its lines to it and can only raise its tone.

## 5. Checks

RC023 fails a client source that decides a tone, badge or severity from a count compared with a number. RC024 fails an app whose routes and its lock file (`routes.lock.json`, next to the file that declares the routes) disagree. Both run on a repo that has an ops center app and are silenced for a line by the exception marker of the other repo checks. RC025 fails an ops center source in which an override or bypass reader answers yes from an error handler, or a scheduled job clears, expires or revokes an override (rule 10). The remaining rules are proved by the tests named in their acceptance text and by review.
