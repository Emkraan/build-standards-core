# Ops Center Layout Standard

Version: 1.0 | Last reviewed: 2026-10-30 | Status: current | Scope: local-ops (operator consoles)

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
3. **The Overview is one card per item.** A card shows a tone pill (healthy, worth a look, needs me), a one-line headline, at most four detail lines, and a link to its item.
   - Prevents: an Overview that is a second copy of every page.
   - Acceptance (test): a UI test renders the Overview for a fixture of items and asserts one card per item, a tone pill on each, no card with more than four detail lines and a link on each card.
4. **One source of truth for counts.** The rail badge, the section and item tab counts and the Overview all read one server-side problem list. The client applies no thresholds of its own. Work in progress shows as a spinner, never red.
   - Prevents: a badge, a tab and a card that disagree, and a red mark for a job that is simply running.
   - Acceptance (test): a test asserts the badge, tab and Overview counts equal the server problem list, and no client source decides a tone, badge or severity from a count compared with a number.
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
9. **Old links never break.** Every renamed or moved route redirects to its new home and keeps its tab and query string. The app keeps a lock file (`routes.lock.json`) listing every route it has ever served.
   - Prevents: a bookmark, a link in a ticket or a notification that lands on a blank page after a reorganisation.
   - Acceptance (test): a test follows every redirect and asserts the tab and query string survive; every route the app has served is still routed or redirected.

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

## 5. Checks

Rules 4 and 9 are checkable from the source and get a repo check each (a client count threshold, a route missing from the app's lock file); the remaining rules are proved by the tests named in their acceptance text and by review.
