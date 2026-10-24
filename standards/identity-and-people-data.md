# Identity and People Data

Version: 1.0 | Last reviewed: 2026-10-02 | Status: current | Scope: web (first-party)

How first-party apps hold data about people. The reference implementation is the hub Team Roster
(`server/src/core/lib/team-sync.ts`, `team-cleanup.ts`, `server/src/core/db/team-raci.ts`,
`server/src/tools/roster/router.ts`).

Related: [First-Party Build Standard](web-build.md) (auth and RBAC),
[Data Safety](data-safety-sqlite.md) (people data is why backups are encrypted).

---

## 1. Rules

1. **The identity provider directory is the source of truth for identity:** object id, display name,
   email and job title. The app stores a cached copy, never a competing one.
2. **One roster.** A single `team_members` table is the only list of people. On-call, RACI, OOF,
   schedules and audit rows link to it by `member_id`. No feature keeps its own private list of
   names.
3. **Directory-only adds.** New members are added only by picking a user from the directory
   (Graph). If Graph is unavailable, adding is refused with a clear message; there is no free-text
   fallback.
4. **Never fabricate people from name-only data.** A seed, import or migration that has only a
   name does not create a member. It links to an existing member by confirmed email, or it is left
   for someone to add from the directory.
5. **Nightly sync.** A scheduled sync (default 02:15 ET, `TEAM_SYNC_CRON`) refreshes members from
   Graph. Matching, first confident hit wins: identity provider object id, then exact email
   (mail/UPN/proxyAddresses, single result), then exact display name (single distinct user, only
   when safe). No match or an ambiguous match marks the member `unmatched` and changes nothing.
6. **Safe propagation.** A confident match overwrites `team_members` (empty Graph values never
   blank a field). Snapshots in linked rows (on-call roster, current and future schedule weeks) are
   fill-only: an existing non-empty value is never changed by the sync, and differences are logged
   for review. Past schedule rows, swap audit and OOF entries are never rewritten.
7. **Test data is synthetic.** Fixtures and seeds use made-up people on `example.test`, never real
   staff.

## 2. Applying this to a new tool

If a tool needs people, it reads or links `team_members` (or calls the shared Graph helpers). It
does not create its own people table, does not accept typed-in names as identities, and does not
copy identity fields it can resolve from the roster.
