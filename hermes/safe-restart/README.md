# Safe Hermes restart

A restart you arm once and forget. Enable the job; it waits until Hermes is idle, restarts it one
time, verifies it came back, records the result, and disables itself.

## Install

The nightly sync (`hermes/apply_setup.py`) does it on macOS and keeps it in lockstep: it copies both
scripts, installs and loads the launchd agent, and creates the job paused. Nothing to do by hand.
`--check` reports a stale or missing piece. The sync never enables the job.

Optional: put the review-board user name in `~/.hermes/state/safe-restart.assignee` (default
`operator`). The job runs from any Hermes home the sync targets; the agent uses `~/.hermes`.

## Use

Enable the job in the scheduled jobs list. Dry run any time: `python3 ~/.hermes/scripts/safe_hermes_restart.py --dry-run`
lists what is still busy.

## How it works

- Idle means no live kanban worker on any board, no other cron run in progress (runs older than 3
  hours are treated as dead), no busy model slot, and no chat turn in flight (an unexpired turn
  lease in the session store held by a live process; the desktop backend and the gateway both take
  one per turn). Anything it cannot read counts as busy: an unreadable board or session store, a
  cron run list that fails, or a model slot endpoint that does not answer.
- Two idle ticks in a row are required. Then the job pauses itself first, so it can only fire once,
  and writes a trigger file.
- The launchd agent watches the trigger file and runs the helper outside the gateway, so the restart
  cannot kill itself. The helper ignores triggers older than 10 minutes, restarts the service,
  checks for a new stable process and a responding model server, and records a card on the review
  board (closed on success, blocked on failure).
- If busy for 12 hours the job opens one card naming what is still running. It stays armed.

## Why it is split

Hermes refuses to create a cron job whose script holds a gateway lifecycle command (it prevents
restart loops). The job script holds none; the helper does, outside Hermes. The guard also matches
prose: keep the exact phrase "hermes gateway restart" out of the job script, including docstrings.
Test the helper without a restart by writing `<epoch> noop` into the trigger file.

## Fenced mode (freeze, then backend before gateway)

Off by default: with the flag absent the helper does exactly what is described above (one gateway
kickstart). Turn it on with any one of: the file `~/.hermes/state/safe-restart.fence` (its first word,
if a number, is the freeze window in seconds), the environment variable `SAFE_RESTART_FENCE=1`, or the
token `fence` after the epoch in the trigger file (one run only: `echo "$(date +%s) fence" > trigger`).

When on, the helper does this, in this order:

1. Freeze: writes `~/.hermes/state/safe-restart.freeze` holding the epoch the freeze expires. The window
   is 30 seconds by default; `SAFE_RESTART_FREEZE_S` or the number in the flag file changes it.
2. Waits the window, then runs the full idle proof again. Work that started inside the window means
   nothing is restarted and the card says so.
3. Restarts the backend (the launchd label named in `~/.hermes/state/safe-restart.backend`; none
   configured means the step is skipped and logged), verifies a new process that stays up 30 seconds.
4. Only then restarts the gateway, verified the same way. A backend that did not come back stops the run
   before the gateway is touched.
5. Releases the freeze on every exit path (success, busy, a failed step, an exception). The marker
   also expires on its own, so a crashed helper cannot hold the freeze past the window.

A runtime that starts new work should refuse or defer it while the marker holds a future epoch.

## Gateway-only mode (no dashboard service)

A consumer that follows `standards/hermes-api-access.md` runs the gateway API server alone, so there
is no backend service label and no per-turn idle proof from a dashboard. The helper detects that
case from an empty or absent `~/.hermes/state/safe-restart.backend` and changes three things.

- Idle also means the gateway's own health read is quiet: `GET /health/detailed` on the API server
  (key from `API_SERVER_KEY` in the agent env file) reports it is not busy, can drain, and holds no
  API run, process completion or delegation. The tick skips the busy flag and the agent count, since
  a cron job inside the gateway may be counted by them, and the helper reads both after the tick has
  exited. An unreadable health counts as busy, never idle.
- A backend the desktop app spawned counts as interactive work. It is found through the app's spawn
  ledger (`~/.hermes/spawn-ledger.json`): only `dashboard` and `serve` entries on loopback that are
  not isolated, whose process is alive and whose start time matches the recorded create time (a
  reused pid is never taken for a backend). Its own `GET /api/health/idle` proof, read with the
  session token its loopback page embeds, must say idle. The helper never restarts, signals or kills
  such a backend, it only waits for it.
- The gateway has no admission fence, so the helper reads the gateway and the backends again right
  before the restart and refuses when either is busy, cannot drain or cannot be read. The restart
  goes through the gateway's draining command (running agents finish, then it restarts), never a
  hard kill, and the result is verified like any other restart. A refusal restarts nothing and
  blocks the card with the reasons. With the fence on, the same second read follows the freeze.

The counts carry no session ids and no fence exists, so this is a smaller guarantee than the
backend idle proof. It bounds the window to the time between the second read and the drain, and the
drain waits for the agents that started inside it.

One opt-in exception: the token `force` after the epoch in the trigger file
(`echo "$(date +%s) force" > trigger`, one run only) skips the wait and the drain and kickstarts the
gateway through launchd. The card records what the gateway was holding at that moment, so a forced
restart is always visible. With a backend label configured the behaviour is unchanged.
