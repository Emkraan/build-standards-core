# Shell server rules

Applies to the API a multi-module shell owns ([web-shell-gateway.md](web-shell-gateway.md)) and to any server that
stores or relays on its behalf. These are the rules a shell server meets beyond the shared runtime
([web-api-runtime.md](web-api-runtime.md)), the token and rights model ([web-shell-auth.md](web-shell-auth.md)) and
the permission model ([rbac.md](rbac.md)). Each rule states what a server MUST do, why, and the proof a shell
carries. The proof is a test the shell owns unless the rule says review.

## 1. Rights

1. **A delegate cannot remove more than they hold.** A delegated admin MUST NOT delete a role assignment of a role that
   holds permissions they do not hold, and MUST NOT delete the Super Admin assignment. They can still delete inside
   their own access. The console hides Super Admin from a delegate's view-as picker. ([rbac.md](rbac.md) section 6 holds
   the grant side of the same ceiling.)
   - Prevents: a delegate stripping a more privileged admin of access, or the last Super Admin.
   - Proof (test): a delegate deleting the Super Admin assignment gets 403 and it stays; deleting an assignment of a role
     above their access gets 403; deleting one inside their access succeeds.
2. **A module opens on its own permission.** A hosted module MUST open for a caller who holds only that module's
   permission, and MUST NOT require a console permission.
   - Prevents: a module that is reachable only for people who also hold a console right they were never meant to have.
   - Proof (test): a caller holding one module permission and nothing in the console sees and opens that module.
3. **Every route is gated or says why not.** Every server route MUST carry a server-side permission gate or an
   explicit stated reason, proved by a test that enumerates the router. The layout, bundle and access-overview routes
   are gated on their own permissions.
   - Prevents: a new route shipping open because nobody had to decide.
   - Proof (test): the test walks the router, fails on a route with neither a gate nor a listed reason, and fails when
     a reason is listed for a route that no longer exists. `shell-packages/route-conformance` is that test's engine
     ([web-shell-packages.md](web-shell-packages.md) section 5.9).
4. **Group ids come from role assignments only.** A shell server MUST NOT read a directory group id from the
   environment and MUST resolve caller groups only through role assignments.
   - Prevents: a group id baked into one environment's settings that grants access the role table does not show.
   - Proof (repo check or test): no source file reads a group id setting, and the scoped group tests resolve through
     assignments.

## 2. Relays

1. **The target comes from a closed list.** A relay that forwards the caller's delegated token MUST pick its target
   from a closed enum, MUST NOT read a free-form origin from configuration, and an unset or unknown value MUST resolve
   to production. Only the literal value of the other member flips it.
   - Prevents: a configuration mistake sending a caller's token to an unintended host.
   - Proof (test): unset, empty, an unknown value and a near miss all resolve to production; only the literal value
     selects the other target; no setting accepts a URL.
2. **A relay forwards, it does not decide.** A shell relay MUST use the caller's own token, MUST pass the upstream status
   and body through unchanged (a 403 stays a 403), MUST reach only an explicit allowlist of paths, and MUST cap the path
   length and the parameters. A directory lookup needs its tab permission and takes only its own parameters.
   - Prevents: a relay widening what a caller can reach, or turning an upstream refusal into something else.
   - Proof (test): the upstream 403 reaches the caller unchanged; a path outside the list is refused before any call;
     an oversize path or an extra parameter is refused.

## 3. Stores

1. **A console-entered secret is stored sealed.** A secret entered in a console MUST be stored sealed (authenticated
   encryption with a key derived per purpose from a vault-held master) and MUST NOT be written to the plain settings
   store. The master is never used as a cipher key: a key derivation with a purpose string separates every use.
   - Prevents: a secret readable from a settings dump, a backup or a log of the settings table.
   - Proof (test): a sealed value round-trips, a tampered or wrong-purpose value fails to open, and the module refuses
     to save a secret through the plain store.
2. **The audit log is a keyed chain.** An audit log MUST chain each entry to the previous one with a keyed hash over a
   canonical form of the entry, MUST offer verify, and a write failure MUST NOT fail the audited action. With no key
   configured it MUST say so rather than claim a chain.
   - Prevents: an edited or removed row going unnoticed, and an audit outage taking a mutation down with it.
   - Proof (test): verify passes on an untouched chain and names the first broken entry after an edit, a deletion or a
     reordering; a failing write is logged and the action still succeeds.
3. **An announcement is plain text.** An announcement MUST be plain text, MUST fold control characters, and its link
   MUST be a site path or https. State is scheduled, live or expired by its window.
   - Prevents: markup or a script link reaching every user's home.
   - Proof (test): markup is kept as text, control characters are folded, and a `javascript:` or protocol-relative link
     is refused.
4. **An external tool entry is validated and display only.** An external tool entry MUST be validated server side (an
   https target and constrained keys), MUST be display only for visibility (the tool keeps enforcing its own access),
   MUST show an External badge and open outside the shell, and its writes MUST be audited and need their own permission.
   - Prevents: the launcher implying access it does not grant, or an unaudited change to what users are sent to.
   - Proof (test): a non-https target or an unknown key is refused; a write without the permission is 403 and a write
     with it leaves an audit row.
5. **Per-user state belongs to its user.** Per-user shell state (pins and the like) MUST be keyed by the lowercased
   caller identity and readable only by that caller. Writes are idempotent.
   - Prevents: one user reading or overwriting another's state through a case difference or a shared key.
   - Proof (test): two callers differing only in case share one record; a caller cannot read another's.

## 4. Health and boot

1. **Health is never invented.** A health card MUST be unknown when there is no reading, MUST be down only when the
   single estate reading says so, and a failed refresh MUST keep the last good reading with its age. A cold process
   answers at once with nothing invented; a stale reading is served and refreshed in the background in one pass.
   - Prevents: a card that looks healthy because nothing was asked, or down because one read failed.
   - Proof (test): no reading gives every card unknown; a failed refresh keeps the last reading and its age; concurrent
     requests start one refresh.
2. **The shell paints from the persisted identity.** The shell MUST paint from the persisted identity before the identity
   request answers, and a directory read MUST NOT block or fail the identity answer. One directory read per object id is
   shared, and a failed read is cached as no profile.
   - Prevents: a blank boot screen on every load, and a directory outage locking people out of the shell.
   - Proof (test): the identity route answers while the directory read is pending or failing; the client paints from the
     stored identity on a warm load and shows the boot screen only on a cold one.

## 5. Data, configuration and actions

1. **Migrations are additive and idempotent.** Every SQL migration MUST be additive, idempotent and ASCII, rows MUST
   carry who and when last changed them (`updated_by`, `updated_at`), and a second run MUST apply nothing. A migration
   runs in one transaction and is recorded in a table.
   - Prevents: a redeploy re-running a change, or a rollback losing data a later release needs.
   - Proof (test): running the full set twice applies nothing the second time; a scan finds no destructive statement and
     no non-ASCII byte.
2. **An unset environment is production.** A server MUST treat an unset environment as production, MUST allow a dev bypass
   only in an explicit development or test environment with a dev user set, and MUST abort boot in production on a
   missing critical secret or an enabled bypass (in development it warns).
   - Prevents: a deploy that forgot one setting running open.
   - Proof (test): preflight with the environment unset behaves as production; the bypass is refused unless the
     environment is exactly development or test; a missing critical secret aborts a production start.
3. **Environment values are settings, secrets are vault references.** Environment-specific values MUST be app settings and
   MUST NOT be hardcoded, and secrets MUST be vault references and MUST NOT be literals, so a development deploy cannot
   reach production. A forbidden-pattern scan on every PR looks for secret-shaped strings and for references to retired
   repositories ([secrets-and-credentials.md](secrets-and-credentials.md) section 1).
   - Prevents: a literal that points a development build at a production resource.
   - Proof (CI): the scan runs on every PR and fails on a literal or a retired reference.
4. **A bulk action reports per item.** A bulk action MUST record a result per item, MUST NOT stop at the first failure,
   and a retry MUST re-run only the failed items ([live-actions.md](live-actions.md)).
   - Prevents: a half-applied change that nobody can see, and a retry that repeats what already worked.
   - Proof (test): a batch with one failing item completes the rest and reports each result; the retry sends only the
     failed items.
5. **Background jobs run in one process.** Background jobs of a scaled-out app MUST run in exactly one process at a time
   under a lock, and MUST stop when the lock connection fails.
   - Prevents: a scheduled job running once per instance, and a job continuing after the lock is lost.
   - Proof (test): of two processes only one runs the jobs; the other takes over when the first exits; a failed ping or
     a client error stops the jobs at once.
