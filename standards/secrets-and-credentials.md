# Secrets and Credentials Standard

Version: 1.0 | Last reviewed: 2026-10-17 | Status: current | Scope: all

How automation, CI and apps authenticate, where the few unavoidable secrets live, how they move
without being seen, and how access is granted, narrowed, rotated and scanned. This doc is the
source of truth. Where a reference implementation differs, the implementation is fixed, or the
consumer records an explicit exception (README, "Source of truth and explicit exceptions").

Related: [CI/CD and Release Standard section 9](ci-cd-release.md#9-required-secrets) (the secrets
a first-party repo holds and the accepted merge token), the README recipe "CI that builds the app"
(read-only deploy keys), [CMTrace Logging section 9](cmtrace-logging.md#9-what-not-to-log) (what
never goes in a log), [PowerShell Scripting](scripting-powershell.md#2-authentication-order),
[IaC Governance](iac-governance.md).

---

## 1. Rules

1. **Identity before secret.** Use a managed identity, OIDC workload federation or a certificate whenever the caller and target support one. A stored secret is allowed only when the target supports nothing else, and then it has an owner, an expiry and a place in the secret store.
   - Prevents: long-lived secrets in code, variables and shares that leak and never rotate.
   - Acceptance (review): every credential in the inventory names why no identity option applies.
2. **Grants are least privilege and scoped to the resource.** Grant the narrowest role at the narrowest scope (a container or a single resource, not a subscription or a tenant). Narrowing creates the narrow grants first, proves them with a real run, and only then removes the broad grant.
   - Prevents: one compromised identity reaching everything, and a narrowing change that cuts access mid-run.
   - Acceptance (review): grant changes in code show the scope, and a narrowing PR cites the usage evidence it was based on.
3. **Federated credentials bind to protected environments.** A CI federation subject names one deployment environment with required reviewers and a main-only branch policy, never a branch pattern or a wildcard. Each tier has its own identity scoped to its own resources. Where a repo cannot set required reviewers (a plan without environment protection), a named operator list is accepted instead only when it is enforced twice, by the workflow step before any token is minted and by the receiving API, re-runs are refused, and the exception is recorded with an owner and a review date.
   - Prevents: any branch, fork or pull request minting a production token.
   - Acceptance (review): each federated subject is an exact environment subject and the environment has reviewers and a branch policy.
4. **Cross-repo reads use one read-only deploy key per consumer.** CI, or a managed host that must read another private repo (for example an agent host that consumes this core), uses a deploy key without write access, one per consumer repo or host, never a personal token. A host key has its private half backed up in the secret store, so a rebuilt host restores it instead of minting an unrecorded one.
   - Prevents: a classic token that can write to every repo its owner reaches, and one revocation breaking every consumer.
   - Acceptance (review): the consumer workflow checks out with `ssh-key`, or the host's convergence script names the key file and its store entry, and the key is listed read-only on the source repo.
5. **Secret values never pass through a person or a transcript.** Read a secret from the store straight into its destination in one step, test it before the write, compare the read-back by hash without printing, and unset it after. When a person must supply a value, use a masked prompt that names the account and the destination, never chat, a terminal echo or a command argument.
   - Prevents: secrets kept in chat logs, shell history, CI logs and screen recordings, each of which forces a rotation.
   - Acceptance (review): scripts that move secrets print only the secret name and update time.
6. **Secrets live only in a secret store.** Workloads read them at run time with their own identity. Never in a repo, a runbook or pipeline variable, a synced folder, a ticket or a CI log. One local exception: a delegated token cache that the sign-in library or engine must keep on disk may be a file owned by the running user with mode 0600, outside any synced or repo folder, holding only the refreshable token and never a client secret. Scripts and local apps follow [Python scripting](scripting-python.md) and [Local ops app](local-ops-app.md) for that file.
   - Prevents: copies nobody knows about, which survive every rotation.
   - Acceptance (review): the secret scan passes and the inventory names the store entry for every secret.
7. **Rotation revokes the old value and is planned per consumer.** Before rotating, list every consumer, plan the swap for the same minute (some issuers revoke the old value at once on reissue), verify each consumer on the new value, then delete the old credential and purge any soft-deleted copy.
   - Prevents: an outage window where a consumer holds a revoked value, and an old secret that stays valid because it was only replaced, not revoked.
   - Acceptance (review): the rotation record lists consumers, the verification of each, and the revocation of the old value.
8. **Every PR is scanned for secrets with a hardened scanner.** Scan the commits of every PR and the default branch with a pinned scanner, using the config from the base commit, with ignore files and inline allow comments disabled, and allowlist known false positives only by path or by an id-shaped match.
   - Prevents: a PR that allowlists its own secret, and broad allowlist patterns that let real secrets through.
   - Acceptance (overlay-ci): the template workflow `core-ci.yml` job `core-secret-scan` runs on every PR and the default branch, and the core's tests prove it fails on a planted test secret.
9. **Broad grants are an owner decision with a recorded risk owner.** A tenant-wide application permission (read-write on all objects, directory, role management, mail, full-control sites) is approved by the accountable owner, with the operational run path described and compensating controls recorded.
   - Prevents: an automation identity quietly gaining the power to read all mail or rewrite the directory.
   - Acceptance (review): the grant PR carries the owner's sign-off and the decision record names the risk owner.
10. **Accepted long-lived tokens are recorded risks.** A token that cannot be avoided (for example a classic personal access token for a merge lane, which cannot expire on a schedule you control) records its scopes, owner, consumers, the reason it cannot expire and a review date no more than a year out, and revoking it is the documented recovery. This is the named exception to the expiry rule; any other credential without an expiry is a defect.
    - Prevents: forgotten tokens with broad scope that nobody reviews.
    - Acceptance (review): the token appears in the inventory with scopes and a review date not in the past.

## 2. Choosing the identity

| Caller | First choice | Fallback |
|---|---|---|
| Cloud workload (runbook, app, function) | Managed identity | None needed |
| CI job deploying to the cloud | OIDC federation bound to an environment | None needed |
| Server outside the cloud | Agent-provided managed identity | Certificate, non-exportable key in the machine store |
| Managed endpoint | Platform-issued device identity | Narrow, time-bound, revocable token per purpose, never an account key |
| Vendor API with no federation | Vendor-scoped token in the secret store, read by the workload identity | None |
| CI reading another private repo | Read-only deploy key per consumer | None |
| Managed host reading another private repo | Read-only deploy key per host, private half backed up in the secret store | None |
| Local job calling a user-delegated API (mail, calendar, documents as the operator) | Authorization code with PKCE and a loopback redirect, first sign-in in the operator's browser, the token cached in a 0600 file (rule 6) | None. Never device code where policy requires MFA |

Interactive admin sign-in uses a browser prompt so MFA and conditional access apply. Device-code
sign-in is not used where policy requires MFA.

## 3. Moving a secret safely

1. Look for the value in the team secret store or password manager first. If it is there, read it
   with one call straight into the destination.
2. If a person must supply it, open a masked dialog that names the account, the system and the
   destination, and write the value in the same command.
3. Test the value against the issuer before the write (a read-only call).
4. Read the stored copy back and compare a hash of both. Print only the name and update time.
5. Unset every variable that held it. Close any dialog by its own process id.

Redact before printing any file that may hold a credential. Parse it and print only names, line
numbers and value lengths. A single redaction pattern that covers only one shape (for example only
signed URL signatures) lets a plain `secret = "..."` assignment through.

## 4. Granting and narrowing

- Prove what a principal really uses before narrowing it: activity log by caller, secret read logs,
  and a search of the workflows and scripts that run as it.
- Create the narrow grants live, run a real idempotent job as the identity, then remove the broad
  grant. In code, add the new grants as imports keyed on the live assignment ids so the plan shows
  imports only.
- Never claim "nobody loses access" without a live membership or permission check for every
  removed principal.
- A role assignment is deleted with the resource it is scoped to. Re-pointing a workload at a new
  resource needs a fresh grant.
- When reviewing a broad grant, verify each finding with evidence (principal id versus client id,
  the federation subject, the environment's reviewers) and describe each option's run path: who
  triggers it, what waits on approval, where it runs, where the identity lives and whether any
  secret exists.

## 5. Rotation

1. List consumers: every workload, pipeline and store copy that reads the value.
2. Schedule the swap. If the issuer revokes on reissue, have the re-store ready to run the moment
   the new value exists, and watch for the first rejection.
3. Re-store, then probe every consumer and every scope it needs.
4. Revoke and delete the old credential. Purge soft-deleted application objects, which can be
   restored with their secrets for a retention window.
5. Record the rotation date and the next review date.

## 6. Secret scanning

- Pin the scanner binary by version and checksum. Run on pull requests, on any merge queue event,
  and on pushes to the default branch.
- Check out the PR head commit with full history and no persisted credentials. Scan merge commits
  too.
- Read the scanner config from the base commit. Delete every ignore file in the tree before the
  scan, and disable inline allow comments.
- Allowlist known false positives by path (for example generated token dictionaries whose keys look
  like API keys) or by a match on names that end in an id suffix, scoped to the one rule that fires.
  Never allowlist a prefix plus anything.
- A history scan is a separate decision: check each hit live without printing it, and rotate what
  is still valid.

## 7. Checklist

- [ ] Identity option chosen from section 2, or the reason none applies is recorded.
- [ ] Grants at the narrowest scope, narrowing done create-first with evidence.
- [ ] Federation subjects are exact environment subjects with reviewers.
- [ ] Cross-repo reads use a read-only deploy key per consumer.
- [ ] No secret in chat, transcript, argv, echo or log, variables unset after use.
- [ ] Secrets only in the secret store.
- [ ] Rotation lists consumers, verifies each, revokes the old value.
- [ ] Hardened secret scan on every PR and the default branch.
- [ ] Broad grants carry the owner's sign-off and a risk owner.
- [ ] Long-lived tokens recorded with scopes and a review date.
