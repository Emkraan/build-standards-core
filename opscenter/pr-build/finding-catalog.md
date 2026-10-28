# Finding catalog

The learning loop behind the pull request build procedure (`PROCEDURE.md`). Each rule below is a requirement for a build: it
names a class of defect that drew a high or blocking review finding after a push, and that a builder can check before the push.
The rules are infrastructure and application neutral; a consumer's own catalog adds its rules under "Appended by the learning
loop" and never weakens one of these.

A rule is a line `- [<letter>] <rule>.`; the letter is the section. An auto-fix session that fixes a real finding this catalog
would not have caught emits `CATALOG ADD: [<letter>] <rule>` in its result file, and the auto-fix starter appends it (deduped).
A new rule never weakens a check.

## A. Infrastructure state semantics

- [A] Every import id is checked against the live object (the provider's documented id, or a read of the object) before the push.
  An id never carries an API version query string.
- [A] Every import is followed by a plan from the branch that shows import only: no in-place update of an immutable attribute and
  no replace. A mismatch in scope casing, principal type, expiry or description turns an import into destroy and recreate.
- [A] Removing a resource, a map entry, a for_each key or a manifest entry is a destroy of the live object. Say so in the PR body
  and land it through the release path. Check for anything else that references the removed key.
- [A] Moving a resource between files or roots needs a `moved` block or an explicit state move in the PR, with a plan that proves
  zero destroys.
- [A] Removing an entry from a known gaps or exclusions list needs proof the object is gone or now managed (a coverage run or a
  plan line). Before adding an exclusion for a platform owned object, check whether state already carries its id, and never widen
  an exclusion to a wildcard scope.
- [A] A full body PUT through a generic resource replaces live settings the plan cannot show. Prefer the update only resource or the
  typed provider resource, or read the live body and include every live property.
- [A] A parent delete cascades (dashboard folders, log tables, key vaults). Prove the children are empty or protect them with
  `prevent_destroy` in a separate earlier PR. A resource that holds user data carries `prevent_destroy` from the first PR.
- [A] Grants or roles another root needs exist before the root that needs them is registered or planned: land grants first,
  register the root second.
- [A] Pin the runner and provider versions the workflow uses. Imported schemas (table columns, policy bodies) match live exactly.
- [A] A scheduled script that manages the same objects as the infrastructure code fights it. Stop or retire it in the same PR.
- [A] A new table and a data collection rule that writes to it in the same apply race: make the rule depend on the table.
- [A] A custom role whose assignable scope is a group created in the same root references the group resource id, never a string
  built from its name, so the group exists before the scope is validated.
- [A] A time boxed value set in a PR (a registration window, an expiry, a grant end) leaves room for the merge to wait, because a
  past value fails the apply and needs another PR.
- [A] A role assignment whose forcing attribute changes on live grants (a role swap) sets `create_before_destroy`, so a refused
  create keeps the old grant.
- [A] A regex or file parse of another root's variables strips comments first, anchors to the map it reads, and parses items
  strictly, so stray text fails the plan instead of becoming a grant.

## B. Identity and access scope

- [B] Every new role or directory grant names the narrowest scope (resource, container, app) and the reason in a comment.
  Subscription, account or tenant scope needs the risk owner and goes to the owner as a decision, never buried.
- [B] The plan identity of a pull request never gets write level roles: plan reads, apply writes.
- [B] Removing a grant needs the list of every reader of it (workflows, runbooks, apps) and the replacement grant in the same PR or
  an earlier one.
- [B] A shared identity that can re-point or edit shared objects (webhooks, script repositories) is an access boundary: scope it or
  record the accepted risk.
- [B] Production app registrations never allow localhost redirect URIs. Never remove a service principal owner without a
  replacement owner.
- [B] A service account outside multi factor and conditional access is a security exception decision for the owner: name the
  compensating controls up front.
- [B] Long lived SAS tokens and account wide credentials are not acceptable defaults: use a managed identity, a short lived
  delegated token, or per object scope. Re-enabling local auth or bearer only webhooks reopens public invocation: scope it and
  record the waiver.
- [B] Every authorization check covers the actor, not only audits it.
- [B] A grant with a path limit gets a condition the platform accepts (for example a read only condition on a reader role is refused
  when it names write actions), and the documented directory roles cover every call and property the code reads.
- [B] A dedicated applier identity is allowlisted to its root, folder and tier in the discovery script, so no root can borrow its
  plan identity by changing metadata.
- [B] A policy resource type allowlist names concrete types (and children of allowed parents), never whole provider namespaces.
- [B] A host registration or bootstrap identity is scoped per host pool (one per trust tier at least), never one identity with the
  token action on a whole group shared by internal and vendor pools, and is attached only while it is needed.
- [B] Shares and sign in roles that serve separate audiences are granted per audience group at the narrowest scope, never a
  default that covers every authenticated identity; a data role for users lands only with or after the ACL that isolates them.
- [B] A guard policy that bounds a pipeline grant is enforced from the first apply, and the root that creates the guarded resource
  fails its plan unless the guard is enforced.
- [B] A certificate credential sets its start and end to the certificate's own validity, and a registration that carries a credential
  never keeps `ignore_changes` on the password, so a secret added outside the code is not hidden from the plan.
- [B] A rollout that reopens a pool wide window or grant scopes it to the hosts or principals being added, and the plan shows no
  update on the existing ones.
- [B] A lock lifting identity for a pipeline holds its role only on the locked parents that pipeline changes beneath, never on a
  whole tier group.

## C. Runtime correctness, scripts and application code

- [C] Optional API fields go in a separate best effort call with a try and catch after the critical create, never in the create
  payload.
- [C] Compare user names, emails and hostnames case insensitively. Identifier parsers for human replies (H1, M2) match case
  insensitively.
- [C] Never assume an async automation finished: re-read state right before the dependent write and treat "already done" as
  success. After an asynchronous remote action, poll the observed state with a bounded wait before a decision reads it.
- [C] Secret and setting names in code match the vault and the app settings exactly: grep both sides.
- [C] Null and empty upstream values are handled explicitly (never blank a whole report or pool). Field types match the target
  schema.
- [C] Hard coded environment values (parent keys, field ids, scope ids) are parameters with documented defaults.
- [C] Destructive or reclaiming runs carry a per run cap AND a total cap, and fail closed on short reads.
- [C] Read modify write calls check a version or etag before writing.
- [C] Never log secret values, even short ones: mask fully.
- [C] A matcher or regex used as a security gate is anchored and tested with a bypass case.
- [C] Route gates: read rights never unlock whole route families, and every new action id is checked against the registry. A
  security check that only runs for routes carrying a marker ships with a conformance test that fails when any route in scope lacks
  the marker, proven by flipping one route.
- [C] Never delete a module or constant other code imports (a version file is bumped, never removed). New imports in UI code are
  declared in the package and actually imported.
- [C] Safety rules in prompts or guardrails are not editable by the content they guard.
- [C] Alerting changes never silently stop paging: show what replaces it. An outcome that leaves a known exposure (a refused write,
  a held intent) fails the invocation and shows as a count, never only a warning on a run that reports success.
- [C] A query metric labelled with a fixed window reads that window in its own clause and every column that explains the state
  comes from the same clause. A latest snapshot view picks its run with no age cutoff, and count tiles return no row (not a green
  zero) when no run exists.
- [C] A text variable never goes into a query string through a quoting helper that leaves backslashes: bind it with an encoding
  function.
- [C] Usage and adoption counts are scoped to the program cohort so unrelated users of a shared platform are not counted.
- [C] Log rows sent to a general workspace carry outcomes only, never per user location detail copied from a security workspace.
- [C] In PowerShell never assign `$x = if (...) { ... } else { @() }` for a value passed to an array parameter (the empty branch
  yields null); a helper whose return value is assigned never writes progress to the output stream; a log ingestion body uses one of
  the two array forms, never both; retry for COM calls catches broadly and walks the inner exception; add a fixture member with no
  rows.
- [C] A sysprep or capture script never deletes the built in administrator and ends with a catch all that prints the FAIL marker.
- [C] An exemption keyed on an HTTP status plus a service error code uses a status and body captured live (in a test fixture) and
  reads every code in the error chain without ever throwing.
- [C] A group move that removes the old group re-reads membership right before every remove, and retries a read that follows its
  own add, since directory reads lag. Classify a group from member count reads, never from a capped member enumeration.
- [C] A runbook that widens its scope to a vendor automated mode leaves the items the vendor owns in that mode alone and fails
  closed on any unknown mode value; one that plans from object settings re-reads them before each write and stops that object when
  they changed since the plan.
- [C] Before committing on a branch rebased onto main, diff each touched file against origin/main and confirm every removed line
  is meant to go, never commit a working copy older than main.
- [C] A safety check that shells out with a timeout catches the timeout and OS errors and fails closed with a reason, so a loop of
  changes still writes its results and audit lines.
- [C] A test that asserts no call happened reads the call list recorded by the fake the code under test actually uses, never a
  fresh local list.
- [C] A not found check matches the object's own error code, never a bare `NotFound` substring, so a missing group or subscription
  fails closed. A paged list follows the next link only while it is a new string, caps the page count, and fails closed on an empty
  or malformed page.
- [C] A multi step state change on a live resource rolls back or verifies each step per resource; a user facing warning that failed
  to send never leads to a forced sign out; a backstop repeat of a confirmed change tolerates transient errors and checks the fresh
  read; a release on failure path tells a failed read apart from a confirmed change, so an outage never undoes protective state; a
  long running roll that re-reads main re-checks before every per host change.
- [C] A drift or auto correct path that re-applies infrastructure keeps access control, network, identity and secret changes
  report only, and never undoes an incident change automatically.

## D. CI and workflow mechanics

- [D] Workflows that diff against base fetch enough history (full depth, or fetch the base ref explicitly).
- [D] Every environment variable or secret a job reads is declared in that job or step. A token a helper needs is set on the one
  step and unset before any provider or local program runs.
- [D] Scanners that run on a pull request use the base commit's config, never the pull request's.
- [D] Em dashes fail the copy standard, including their escaped unicode forms in strings.
- [D] Workflow claims of environment gating are enforced in the workflow or the environment config in the same PR. A check on who
  started a run sits in the first step of every privileged job and reads the triggering actor, never in a separate prerequisite job.
- [D] Root registration keys (deploy descriptors, root lists) match what the discovery script reads. Deploy change detection treats
  a change to an app's own deploy descriptor as a trigger. A deploy matrix filter that drops apps fails closed when the app's block
  is missing, empty or not an object, and when a named app or alias cannot be resolved.
- [D] After a deploy gate restarts an app, it counts only answers from a process proven to start after the restart, and a gate never
  treats a few public health samples as proof that every instance loaded a package.
- [D] A job that runs after an apply checks out the pushed sha that apply used, never a floating branch, and stands down when the
  branch head already has newer inputs. A job that changes the platform from a checkout stops once main moved past its sha,
  re-checked right before each change.
- [D] A CI exception that trusts other open pull requests counts only same repo heads, only added files, never the current pull
  request or branch, and never an object the base already declares, and binds a claim to that pull request's own new folder.
- [D] A guard that reads machine readable plan output checks the exit code and validates the shape before treating an empty result
  as clean.
- [D] A job that must run after a matrix where one leg can fail uses `!cancelled()` with explicit result checks, never bare
  `success()` and never `always()`. Files uploaded by matrix jobs get a per row file name. A scheduled job never joins the
  concurrency group of a merge driven apply.
- [D] A workflow triggered by another run, or a long running one, reads config from the current main and re-checks it before each
  disruptive step; a reusable workflow that accepts a pinned ref checks that ref out in its discovery step too.
- [D] A workflow that lifts management locks around a saved plan refuses, before lifting anything, a plan that deletes a lock or a
  locked resource, and signs the helper identity out before the infrastructure tool runs.
- [D] A gate that decides auto apply or auto delete runs whenever the caller names a root, and an empty applier or tier is blocked.
- [D] A step that needs a not yet applied identity requires it only for the plans that need it.
- [D] A command substitution whose non zero exit is an expected outcome is written so it survives `set -e` and keeps the reason; a
  shell lookup over a glob uses an array and is tested with and without a match.
- [D] Git diff based root selection is tested against a real temporary history, never only with changed files monkeypatched.
- [D] A generated artifact (a dashboard from a generator) is regenerated in the same commit as its inputs.
- [D] A sweep over a scope that a pending apply creates keys on the scope being in state, never a live probe with the plan identity.
- [D] A drift classifier claims opt in resources only when the spec declares the opt in, in every tier.

## E. Documentation claims

- [E] Every README or PR body claim of enforcement points at the line or setting that enforces it. A document that claims more than
  the code does is a defect.

## F. Review state and finding trackers

- [F] Diff driven state trackers treat a pure insertion as moving neighbouring lines, never as changing them; line mapping inside a
  hunk walks it line by line; a map keyed by the old path is looked up before a rename swaps in the new path.
- [F] State persisted in a size capped marker or list is checked against an exact count on read, and any shortfall falls back to the
  strict path; machine readable locations are never cut to a length; a shortened or suffix matched path never drives a decision.
- [F] Fuzzy matches only find candidates. Replacing, carrying or dismissing a finding needs a strict match, and a match never
  lowers or hides a higher rating; a file only location never matches a location with line numbers.
- [F] A cap on a mixed trusted and untrusted list applies to the untrusted part only; a special case for one severity never bypasses
  the shared delete or change check.
- [F] State stored in a single overwritten record survives a failed or unavailable round: the failure write copies the last good
  state forward.

## G. Clients, caches and telemetry

- [G] A one time local storage carry over runs behind its own marker key and copies only when the target key is absent (`=== null`).
  A user preference is mirrored at the moment of the pick, never by watching state with a pending flag.
- [G] A UI dedupe key never stringifies framework nodes. Render structured columns through a formatter that returns strings only.
- [G] A same origin redirect check runs again on the URL resolved path (dot segments resolve to a protocol relative target after a
  raw string check). A navigation loop guard counts only navigations that left the page.
- [G] A client cache or request layer drops everything from before a session change; background reads acquire tokens silently only
  and map interaction required to a 401; a promise that waits on a navigation always has a timeout; a shared API client never sends
  a scoped call without a bearer while signed out and attaches the bearer only to relative paths on the expected origin.
- [G] A poll that must never sign in makes the call itself with the no sign in option, never accepting a caller callback made safe
  with call stack state. A redirect or report decision keyed on an error code allowlist defaults unknown codes to one attempt
  behind the loop guard.
- [G] A route or name exported to telemetry passes a per segment template allowlist and is sent as `-` otherwise, never a character
  denylist.
- [G] A rollup over many upstream calls treats only a 404 as an empty source; any other error carries a recent per source read or
  fails the refresh, so permissions drift never reads as zero.
- [G] A cache that fails closed for an alert job never stops alerting silently. A stale while revalidate cache counts its failure
  backoff from the failure, cancels a timed out run between batches, caps how long a cold request waits and rebuilds only from a
  freshly loaded input list. A cache on the authorization path is validated against a trigger bumped version row on every use,
  never a TTL plus in process invalidation, and break glass resolves before any database read.
- [G] A never block route never awaits even its cold first read: return honest placeholders and warm in the background; a hung
  upstream gets a timeout plus a no new call while running guard.
- [G] When a contract changes from never throws to throws or null, change and test the caller in the same diff.
- [G] When two feeds fill the same fill only attribute, give each device class one owner feed. A feed that starts writing a human
  curated attribute stays guarded in the map resolver and fill only.
- [G] A retry of a send resends only failures where nothing can have reached the target (no token, refused connection, unresolved
  name, 429 or 503); a timeout or reset may have landed and is dropped. Any request a single flight cache shares carries its own
  timeout. Bounded retry queues limit recovery fan out, and a shutdown drain bounds each last attempt.

## Appended by the learning loop

(none yet: a consumer's lines are appended here by the auto-fix starter)
