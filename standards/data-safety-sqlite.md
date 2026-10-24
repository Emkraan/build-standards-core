# Data Safety - SQLite on the app platform

Version: 1.0 | Last reviewed: 2026-10-02 | Status: current | Scope: web (first-party)

Rules for any first-party app that keeps a SQLite database on the app platform. Section 7 adds the rules for an app on a server database and for an audit log. They come from
the hub DB corruption incident and are implemented in the hub in `server/src/core/db/lock.ts`,
`safety.ts` and `lifecycle.ts`, with runbooks in `docs/DEPLOYMENT.md`.

Related: [CI/CD and Release Standard](ci-cd-release.md) (serialized deploys,
pre-deploy backup, health gate, off-site backup), [First-Party Build Standard](web-build.md#5-data-and-migrations)
(migrations).

---

## 1. The incident (2026-10-01)

Back-to-back deploys overlapped. For a short window two App Service containers had the same
`hub.db` open on the `/home` share, which is network file shares over SMB, while the DB ran in WAL mode.
WAL keeps its index in a shared-memory `-shm` file that every process must mmap, and SQLite
documents that this does not work on a network filesystem. The DB was corrupted twice. Everything
below exists so that this cannot happen again, and so that a bad file is caught and preserved
instead of being written over.

## 2. Rules

1. **One writer, enforced by a lock file.** Before opening the DB the server creates
   `hub.db.lock` with an exclusive create (`O_EXCL`), which the SMB server enforces across hosts
   (flock/fcntl are not reliable across network file shares clients). The lock holds JSON (token, pid,
   hostname, startedAt, heartbeatAt) and is heartbeated every 5 s (`DB_LOCK_HEARTBEAT_SEC`).
2. **Stale takeover only.** A waiting container polls and takes over only when the heartbeat is
   older than `DB_LOCK_STALE_SEC` (30 s) or the holder pid is dead on the same host. Takeover
   renames the stale file aside atomically. A holder that finds its token replaced has lost the
   lock and stops.
3. **Listen before you lock.** The HTTP server listens first and answers 503 `starting` until the
   DB is open. Otherwise the platform warm-up never succeeds, the old container never gets SIGTERM,
   and both deadlock until the start time limit.
4. **Journal mode for network storage.** On the cloud platform (`WEBSITE_INSTANCE_ID` set) use
   `journal_mode=DELETE` with `synchronous=FULL`. WAL is allowed only on local disk (dev). The
   switch runs `wal_checkpoint(TRUNCATE)` first. Override only with `DB_JOURNAL_MODE`.
5. **Graceful shutdown.** On SIGTERM/SIGINT: stop HTTP, stop cron, checkpoint, close the DB,
   release the lock, exit (forced after `SHUTDOWN_TIMEOUT_MS`, default 8000).
6. **Integrity gate on open.** Run `PRAGMA quick_check`. On failure, copy the file (and any
   `-wal`/`-shm`/`-journal`) to `hub.db.corrupt-<UTC stamp>`, leave it untouched, and **refuse to
   open it**. The app stays up returning 503 with restore instructions (no crash loop that buries
   the cause).
7. **No silent auto-restore.** Auto-restore from the newest verified backup happens only with
   `DB_AUTO_RESTORE=1`, because restoring discards every write since that backup and a person
   should choose between the app backup and a platform backup.
8. **Verified app-level backups.** Online backup API (`db.backup()`) to
   `/home/data/backups/hub-YYYYMMDD-HHMMSS-<kind>.db`, each verified with `quick_check`: on startup,
   nightly (`DB_BACKUP_CRON`, default 02:15 America/New_York), on demand
   (`POST /api/admin/db/backup`), pre-deploy (`POST /api/ops/predeploy-backup`) and off-site.
   Retention per kind is configurable (`DB_BACKUP_KEEP_*`).
9. **Never open the DB outside `initDb`.** No script, tool, route, Kudu console or SSH session
   opens the live file. A second process touching it over SMB is the failure mode itself. Ad hoc
   inspection uses a backup copy.
10. **Deploys are serialized** (one concurrency group for deploy and rollback) and health-gated on
    the new commit SHA; see the [CI/CD standard](ci-cd-release.md#6-deploy).
11. **Deploying over pre-lock code needs a stop first.** Code older than the lock does not know to
    wait for it. When the running build predates the lock (or its version is unknown), stop the
    app before deploying, then start it.
12. **Migrations are forward-only and additive**, checked in CI by `migration-safety`.

## 3. Health and state

`/health` reports `status`, `version` and `build` (`<sha>@...`). The DB lifecycle state is one of
`starting`, `ready`, `corrupt`, `failed`, `stopping`; anything but `ready` returns 503. The deploy
health gate and the `/api/ops/smoke` check read these.

## 4. Configuration reference

| Setting | Default | Purpose |
|---|---|---|
| `DB_JOURNAL_MODE` | `delete` on the cloud host, `wal` locally | journal mode override |
| `DB_LOCK_HEARTBEAT_SEC` | 5 | lock heartbeat interval |
| `DB_LOCK_STALE_SEC` | 30 | heartbeat age before takeover |
| `SHUTDOWN_TIMEOUT_MS` | 8000 | forced exit after SIGTERM |
| `DB_AUTO_RESTORE` | unset | `1` allows restore from the newest verified backup on corruption |
| `DB_BACKUP_CRON` | `15 2 * * *` (ET) | nightly backup schedule |
| `DB_BACKUP_DIR` | `<db dir>/backups` | backup folder |
| `DB_BACKUP_KEEP_STARTUP` / `NIGHTLY` / `MANUAL` / `PREDEPLOY` | 10 / 14 / 10 / 10 | retention per kind |

## 5. What not to do

- Do not switch the cloud-hosted DB back to WAL.
- Do not open, copy or `sqlite3` the live `hub.db` from Kudu or SSH while the app runs.
- Do not run two deploys, or a deploy and a rollback, at the same time.
- Do not "fix" a corrupt DB in place. Repair always happens on a copy.
- Do not attach or upload an unencrypted DB anywhere; it holds staff names and emails.

## 6. Recovery runbook

Production actions here (stop, start, restore) need the owner's go-ahead.

### 6a. The app reports `corrupt` (503)

1. Leave the app running in its degraded state; the corrupt file is already preserved as
   `hub.db.corrupt-<stamp>`. Read the log line, which names the newest verified backup.
2. Choose the source: the newest app backup (`/home/data/backups/`), the newest off-site backup
   (section 6c), or an App Service platform backup. Prefer the newest verified one and note how many
   hours of writes it loses.
3. Restore (section 6b).
4. Investigate the corrupt copy offline (section 6d) to learn whether any newer rows can be
   recovered.

### 6b. Manual restore (app backup)

1. **Stop the app** (Portal or `az webapp stop`). Never restore under a running app.
2. Delete `hub.db-wal`, `hub.db-shm` and `hub.db-journal` if present.
3. Copy the chosen backup over `/home/data/hub.db`.
4. Start the app. Confirm `/health` is `ok` and run the smoke check.

Alternative for a known-good recent backup: set `DB_AUTO_RESTORE=1`, restart, then unset it.

### 6c. Restore from an off-site backup

```bash
gh run download <run-id> -R the reference app repo -n hub-<stamp>.db.enc
sha256sum -c hub-<stamp>.db.enc.sha256
read -rs BACKUP_ENCRYPTION_KEY && export BACKUP_ENCRYPTION_KEY
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in hub-<stamp>.db.enc -out hub.db -pass env:BACKUP_ENCRYPTION_KEY
sqlite3 hub.db 'PRAGMA quick_check;'   # must print ok
```

Then follow 6b with the app stopped (upload `hub.db` via Kudu file upload only while stopped), and
delete the local plaintext copy afterwards.

### 6d. Platform backup restore

Restore an App Service platform backup only with the app stopped, then run 6b steps 2 and 4.

### 6e. Repairing a damaged file (offline, on a copy)

```bash
cp hub.db.corrupt-<stamp> work.db
sqlite3 work.db 'PRAGMA integrity_check;'
sqlite3 work.db 'REINDEX;'          # fixes index-only damage
sqlite3 work.db 'VACUUM;'           # rebuilds the file
sqlite3 work.db 'PRAGMA quick_check;'
# Still bad: sqlite3 work.db '.recover' | sqlite3 recovered.db
```

Use a repaired copy only after comparing row counts against the newest backup. The original
corrupt file is never modified.

## 7. Server databases and audit logs

These rules apply to an app that keeps its data in a managed server database instead of, or beside,
SQLite, and to any app with a tamper-evident log.

1. **Apps sign in to the database with a managed identity.** People and apps use directory tokens or
   a workload identity. Where the database supports nothing else, an app keeps one password login
   for its own database (no superuser), and that secret has an owner, an expiry and a place in the
   secret store ([Secrets rule 1](secrets-and-credentials.md#1-rules)).
   - Prevents: a shared password that nobody owns and nobody rotates.
   - Acceptance (review): each database login is listed with its owner and expiry.
2. **Backups are kept long enough and restored on a schedule.** Keep platform backups for at least
   the period the owner sets (not the 7 day default), geo-redundant where the data cannot be rebuilt,
   and run a restore drill on a schedule into a scratch database with the result recorded. A
   restore runbook lives in the repo.
   - Prevents: a backup that nobody has ever restored.
   - Acceptance (review): the last drill date and result are in the runbook and are not older than the schedule.
3. **A migration screen runs in CI.** A check fails a migration file that drops, truncates, deletes,
   renames or changes a column type unless it is marked as an approved exception with its reason.
   - Prevents: a destructive migration reaching production because the deploy only checks that migrations ran.
   - Acceptance (test): the screen fails on a fixture for each destructive form and passes on an additive one.
4. **An audit log is a serialised, keyed chain.** Each entry is appended under one lock (an advisory
   lock or a single writer), reads the chain tip by sequence number and never by timestamp, and
   stores a keyed hash of the previous hash plus its own content. One shared module writes it, and a
   verify walk checks the chain in sequence order.
   - Prevents: two instances forking the chain, and equal timestamps breaking the verify walk.
   - Acceptance (test): two concurrent appends produce one chain that verifies, and an edited or removed row fails the walk.
