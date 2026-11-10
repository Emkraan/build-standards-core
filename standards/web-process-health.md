# Web Process Health Standard

Version: 1.0 | Last reviewed: 2026-11-09 | Status: current | Scope: web (Node servers on small app
hosting plans, with a database or files on network-backed storage)

How a first-party web process stays responsive, and what happens when it does not: no long
synchronous work on the main thread, a watchdog that ends a frozen process, one registry for every
background timer, and a startup that never makes a replacement process wait on a full check. Every
rule here came from one production hardening week of a product app whose server did all of it on one
event loop. This doc is the source of truth. Where a reference implementation differs, the
implementation is fixed, or the consumer records an explicit exception (README, "Source of truth and
explicit exceptions").

Related: [Web API Runtime](web-api-runtime.md) (the request path of the same server),
[Shell server rules](web-shell-server.md) section 5 rule 5 (background jobs run in one process
under a lock; this doc does not repeat it) and [Shell packages](web-shell-packages.md) section 5.4
(the `jobs` package and the job leader that implement it), [Data Safety](data-safety-sqlite.md)
(the database lock a takeover waits on, section 2 rules 1 to 3).

Each rule names the failure it prevents, the evidence and its acceptance line. Evidence is a
measured number from the app the rule came from.

---

## 1. Rules

1. **A long read runs in a one-shot worker, never on the main thread.** Any read that can take more
   than about a second against network-backed storage (a startup integrity check, a smoke check, a
   whole-file hash, a table scan for a report) runs in a worker thread or child process that does
   that one job and exits. The main thread keeps serving requests, answers a not-ready state
   (503 `starting`) for anything that needs the result, and receives the answer as a message.
   - Prevents: a synchronous check on the event loop freezing every request, every heartbeat and
     every health probe for as long as the storage takes to answer.
   - Evidence: a startup integrity check and a smoke check ran synchronously on the main thread
     against network-backed storage. Takeover after a restart waited 729,682 ms for the full check
     before it served; after the check moved off the main thread and was deferred it took 633 ms.
   - Acceptance (test): a test starts the check against a fake storage that answers after a delay
     and asserts that a health request is answered during the delay, that the worker has exited
     afterwards, and that no code path of the check runs on the main thread.
2. **An event-loop watchdog ends a frozen process after about 90 seconds.** A watchdog that does
   not run on the main event loop (a worker thread, or a supervisor process) reads a heartbeat the
   main loop writes every few seconds. When the heartbeat is older than the limit (default 90 s,
   one setting), the watchdog logs the age and the last known activity, then ends the process with
   a non-zero exit so the platform starts a fresh one. A watchdog timer on the main loop is not a
   watchdog: it freezes with the loop.
   - Prevents: a process that is up and holds the lock and the port but answers nothing, and that
     nobody restarts because it never exited.
   - Evidence: a frozen process stayed up for 10 minutes, past every platform probe, until a
     watchdog that ends it after 90 s was added.
   - Acceptance (test): a test blocks the main loop of a child server past the limit and asserts
     that the child exits non-zero within the limit plus a small margin, with the heartbeat age in
     its last log line; a second test asserts a busy but ticking loop is never ended.
3. **Every background timer is created through one job registry, and CI rejects any other.** A
   recurring or delayed task (an interval, a self-rescheduling timeout, a cron library callback)
   is registered by name with the one registry module, which starts it, tracks it and can stop all
   of them at once. On a lost lock, a handoff to a new process or SIGTERM the registry stops every
   job and waits for the ones running to finish. A CI check fails a change that calls a timer
   function (`setInterval`, `setTimeout` used to reschedule, a cron scheduler) anywhere outside the
   registry module and a short exemption list that only shrinks. The registry is the in-process
   half of [Shell server rules](web-shell-server.md) section 5 rule 5; an app on the multi-module
   shell uses the `jobs` package and the job leader ([Shell packages](web-shell-packages.md)
   section 5.4) as that registry rather than writing a second one.
   - Prevents: a timer nobody can find keeping an old process answering and writing after a newer
     one has replaced it.
   - Evidence: background timers created outside a registry could not be stopped on handoff, so an
     old process kept answering after it was replaced. A CI check now rejects them.
   - Acceptance (CI): a check scans the server source, fails on a fixture that creates a timer
     outside the registry, passes on the registry module itself, and fails when an exemption entry
     names a file that no longer needs it. A test stops the registry and asserts that no timer
     remains and that a job running at the time finishes first.
4. **Startup is staggered, and a lock takeover never waits on a full check.** The server listens
   first (503 `starting`), then takes the database lock as soon as it is free
   ([Data Safety](data-safety-sqlite.md) section 2), and only then starts its heavy work: the full
   integrity check, the smoke check and each job start at different offsets (a few seconds apart,
   the check last), never all at once and never before the lock is held. The takeover path itself
   runs no full check, hash or scan; the check runs after the process is serving, in a one-shot
   worker (rule 1), and its failure puts the process in the `corrupt` state rather than blocking a
   takeover that already happened.
   - Prevents: a replacement process spending minutes on a full check before it takes the lock,
     so every restart is an outage as long as the check.
   - Evidence: takeover after a restart waited on a full check for 729,682 ms; with the check
     deferred and staggered it took 633 ms.
   - Acceptance (test): a test starts two processes over one fake lock with a check that takes a
     long time, ends the first, and asserts the second holds the lock and serves within a bounded
     time that does not include the check, and that the check, the smoke check and the jobs start
     in the declared order at distinct offsets.

## 2. Checklist

- [ ] No read over about a second on the main thread: a one-shot worker, a 503 `starting` while it runs.
- [ ] A watchdog off the main loop ends a process whose loop has not ticked for about 90 s.
- [ ] Every background timer goes through the one job registry; CI fails a timer outside it.
- [ ] The registry stops all jobs on a lost lock, a handoff and SIGTERM.
- [ ] Listen first, take the lock, then start the check, the smoke check and the jobs at staggered offsets.
- [ ] A lock takeover runs no full check.
