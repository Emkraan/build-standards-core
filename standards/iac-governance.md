# IaC Governance Standard

Version: 1.1 | Last reviewed: 2026-10-13 | Status: current | Scope: infrastructure as code (Terraform and equivalents)

How infrastructure code is planned, approved, applied and kept in step with what is live. The
examples use Terraform and a cloud platform with workload federation, but the rules hold for any
declarative tool. This doc is the source of truth. Where a reference implementation differs, the
implementation is fixed, or the consumer records an explicit exception (README, "Source of truth
and explicit exceptions").

Related: [Secrets and Credentials](secrets-and-credentials.md) (pipeline identities and grants),
[PR Review and Merge](pr-review-and-merge.md) (holds and the merge button),
[Automation Safety](automation-safety.md) (human gates), [CI/CD and Release](ci-cd-release.md).

---

## 1. Rules

1. **Everything is declared in code.** Every resource and setting in the managed scope is in code. Console and CLI changes are break-glass only and are back-ported within the back-port window (parameter, default one business day). Existing resources are adopted import-first: a pure-import plan, then an empty follow-up plan.
   - Prevents: live state nobody can rebuild or review, and an apply that reverts an untracked fix.
   - Acceptance (review): the nightly coverage sweep lists no unmanaged resource outside the recorded exclusions.
2. **State lives in a dedicated, locked backend.** State is remote, in a store that holds nothing but state, reachable only by the plan, apply and break-glass identities, with versioning, soft delete and a delete lock. Applies take the state lock. PR plans run read-only without it, and nobody force-unlocks a lock they did not take.
   - Prevents: state corrupted by concurrent applies, state readable by every workload, and a lost state file.
   - Acceptance (review): the backend config names the dedicated store and applies run with locking on.
3. **Every PR plans, and applies use only the reviewed plan.** Each PR runs format, validate, lint and plan for every root it touches and posts the plan. Applies run from `main` with the saved, reviewed plan behind an environment approval, never `-auto-approve` on an unreviewed plan.
   - Prevents: an apply that does more than anyone reviewed.
   - Acceptance (review): the plan job runs on every PR and the apply job consumes the saved plan artifact.
4. **Plan runs auto-approve only for low-risk diffs.** A gated plan run is approved automatically only when the diff cannot change what the pipeline executes or reads. Changes to workflows, code owners, backend or CLI config, external data sources, local or remote exec, non-allowlisted providers or module sources, and diffs too large to read wait for the owner.
   - Prevents: a PR that uses the plan identity's state access to read secrets or run arbitrary code.
   - Acceptance (test): the gate's matcher tests cover each hold rule and an ordinary diff that auto-approves.
5. **Deletes are guarded and released explicitly.** A plan with any delete or replace fails the normal path. Deletes apply only through an explicit release path (a destroy workflow from `main` in a protected environment with a typed confirmation) whose plan equals exactly the deletes the PR approved.
   - Prevents: data-bearing resources deleted as a side effect of a refactor, rename or stale branch.
   - Acceptance (review): the plan job fails on any delete count above zero and the release workflow requires its environment approval.
6. **Delete-time guards land before the removal.** Provider flags checked at delete time are read from prior state, so a guard is applied in its own PR before the PR that removes the resource.
   - Prevents: a guard added in the same PR as the removal, which protects nothing.
   - Acceptance (review): removal PRs of guarded types reference the guard PR that applied first.
7. **Roots that govern the pipeline are owner-applied.** Roots that create pipeline identities, grant roles, set policy or manage the state backend are applied only by an owner identity, never by the pipeline they govern.
   - Prevents: a pipeline that can grant itself more access.
   - Acceptance (review): the roots registry marks each root's applier and the pipeline identity has no write on owner roots.
8. **Drift is detected nightly.** A scheduled plan per root with a detailed exit code, plus a coverage sweep that compares live inventory (child objects included) with state, opens one work item per drift set.
   - Prevents: live changes that the next apply silently reverts, and resources nobody manages.
   - Acceptance (review): the drift workflow runs nightly and its last result is recorded.
9. **Change freeze windows block applies and deletes.** Applies, destroys and releases check the freeze calendar (parameter) read live on each run, and fail closed when it cannot be read.
   - Prevents: production changes in a window the business reserved, and a freeze answered from memory.
   - Acceptance (review): the apply and release jobs run the freeze check first and fail on a read error.
10. **Providers and modules are pinned.** Provider versions are pinned and the lock file is committed. A new provider address or a module from outside local paths and the allowlist is a held change.
    - Prevents: a supply chain change arriving through an unreviewed provider or module.
    - Acceptance (review): the plan job fails when the lock file adds a provider not on the allowlist without the owner's approval.
11. **Owner applies never delete open work's objects.** When an owner applies a root from a branch before it merges, that root's state runs ahead of `main`, and any later owner apply from a tree that lacks the branch plans those objects as deletes. Before applying a saved plan of an owner-applied root, a guard compares every planned delete with the resources that open pull requests declare in that root, and refuses on a match unless the owner names that pull request as meant to lose them. Merge a branch-applied change to an owner root before anything else applies that root.
    - Prevents: an unrelated owner apply silently deleting grants or policy another open change depends on, which then fails that change's plans with access errors nobody can explain.
    - Acceptance (test): the guard's tests cover a refused delete declared by an open pull request, an allowed override, a plan with no deletes, and a lookup failure that refuses (fail closed).

## 2. The pipeline shape

| Stage | Runs | Identity | Gate |
|---|---|---|---|
| Static | fmt, validate (`init -backend=false`), lint, policy scan | none | Required check |
| Plan (PR) | `plan -lock=false -detailed-exitcode` per root and tier | Plan identity per tier, read-only on state | Environment gate, auto-approved for low-risk diffs |
| Result | One job that needs every matrix job | none | The one required context |
| Apply (main) | The saved plan | Apply identity per tier | Environment approval, freeze check |
| Destroy (main) | A plan that only deletes | Apply identity | Destroy environment, typed confirmation, freeze check |
| Drift (nightly) | Plan per root plus coverage sweep | Plan identity | Opens a work item |

- One required result context means new matrix entries never need a ruleset edit. Make it required
  only after it is on `main`.
- Chain work inside one gated job rather than across two gated jobs, or each run asks for two
  approvals.
- When one job uses two identities, sign out of the first and confirm it is gone before the second.

## 3. Landing a removal

1. Prefer removing the live object first when it can safely go before the merge (a grant, an
   unscheduled job). Back it up, delete it, then the PR's plan only drops it from state and stays
   green.
2. Otherwise confirm the PR plan is only the intended deletes. Any extra change means the branch is
   behind or live state drifted. Find out which before going on.
3. Check the apply identity can delete what the plan deletes (conditions on its role grants).
4. The owner approves the hold. The merge starts the release path, whose plan is read before the
   destroy environment is approved.
5. Verify the objects are gone live and the root plans `No changes`. Merge a live-first removal
   quickly: until it lands, any apply from `main` re-creates the objects.

## 4. Locks on shared singletons

- Put delete locks on shared core singletons (databases, secret stores, the state backend, the
  public edge, log workspaces), never on a whole resource group, where they block routine cleanup
  and get removed and forgotten.
- A delete lock also blocks deleting child objects and role assignments scoped to the resource.
  A pipeline delete lifts and recreates it through the destroy workflow (section 7). A by-hand
  change removes it, makes the change and recreates it with the same name, level and notes in the
  same session.
- Declare the locks in code after import so a manual unlock shows as drift.

## 5. Local plans

- Plan against real state locally only with the real backend key. A placeholder key opens an empty
  state, and every resource shows as "will be created".
- Keep `TF_DATA_DIR` in scratch, and restore the committed lock file after a local `init` unless a
  provider upgrade is intended.

## 6. Checklist

- [ ] Every resource in code, break-glass changes back-ported, adoption import-first.
- [ ] Dedicated state backend with locking on apply, no force-unlock of others' locks.
- [ ] PR plans for every touched root, applies from the saved reviewed plan.
- [ ] Plan auto-approval limited to low-risk diffs.
- [ ] Destroy guard on, deletes only through the release path.
- [ ] Delete-time guards applied before the removal PR.
- [ ] Owner-applied roots marked and out of the pipeline's reach.
- [ ] Nightly drift and coverage sweep running.
- [ ] Freeze calendar read live before applies and deletes.
- [ ] Providers pinned, lock file committed, new sources held.
- [ ] Owner applies guarded against deleting objects open pull requests applied from their branches.

## 7. Saved plans and deletes

- **Hash-checked plans.** The plan job stores the saved plan with its sha256 and a short retention
  (one day). The apply job recomputes the hash and refuses a plan whose hash differs, so a swapped
  or stale plan cannot apply.
- **Deletes are split from applies.** The apply workflow fails any plan that deletes or replaces a
  resource. Deletes go through a separate destroy workflow. There, a role that can only touch locks
  lifts the locks on the parents of the planned deletes (never a lock on a whole group of
  resources), and a step that always runs recreates them and lists what it recreated.

- **Vendor secrets are declared as placeholders.** A secret whose value only a vendor can issue is
  declared once in IaC with a placeholder value, a `value-set` tag set to false, an owner tag and an
  expiry tag, and `ignore_changes` on the value. The real value is set by a person in the secret
  store and the tag flipped to true; it never passes through IaC, state or CI. A lister prints every
  secret whose `value-set` is still false, so a waiting vendor is visible.

**Acceptance (test):** an altered plan file fails the apply; a plan with a delete fails the apply
workflow and passes the destroy workflow; a vendor secret declared without the owner, expiry and
`value-set` tags, or with a real value, fails the IaC check.
