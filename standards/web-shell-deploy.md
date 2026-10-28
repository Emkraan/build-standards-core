# Shell build and deploy

Applies to a multi-module shell ([web-shell.md](web-shell.md)) built in one repository with its modules'
clients and APIs. Pipeline mechanics that any app uses (required checks, serialised deploys, the health gate,
branch deploys without the deploy token, rollback) are in [ci-cd-release.md](ci-cd-release.md) and
[pr-review-and-merge.md](pr-review-and-merge.md) and are linked, not repeated. This document adds what a
shell with several modules changes. The API layout is [web-shell-gateway.md](web-shell-gateway.md).

## 1. The model

| Fact | Detail |
|---|---|
| One repository, two tiers | `main` deploys the production tier. A branch named for a ticket deploys the dev tier. Resource names carry the tier prefix and the module (`<prefix>-<module>-api`) |
| The web is separate from the APIs | The shell and every module client are one static bundle; each API is an App Service. They deploy from different workflows on different triggers |
| The dev tier is shared | Every ticket branch deploys over the same dev tier, so a branch that is behind `main` is refused (section 5) |
| Cloud sign-in | Workload identity federation only, no stored cloud secret. Each tier's deploy runs under its own identity, chosen by the bound environment |
| Static host token | One token per environment; a branch run never holds it ([ci-cd-release.md](ci-cd-release.md) section 6, "Branch deploys never hold the deploy token") |
| Rollback | None automated. Recovery is fix forward: revert on a branch, merge through the queue, the same pipeline redeploys; infrastructure goes back the same way |

The rollback row differs from [ci-cd-release.md](ci-cd-release.md) section 7 (a manual rollback workflow that
redeploys a tag). A shell that runs forward-only is a documented exception to that section, with the reason
above; it does not remove the rule that migrations are forward-only and additive.

## 2. How a module change redeploys

| Changed path | What deploys |
|---|---|
| A module client, the shared packages, the web project | The whole bundle again (one bundle) |
| The shell API folder or its package file | The shell API: infrastructure first, then the app, then the health gate |
| The shared packages | Both of the above, and every API that vendors them |
| A module manifest only | The bundle, through the regenerated registry file under the shared packages (the manifest folder is not a web trigger by itself) |
| App infrastructure or the infrastructure roots | Terraform for that root, then the app deploy |
| Markdown and docs | Nothing |

A module author edits the manifest, regenerates the registry and commits it. Nothing else lists tools; CI fails
when the file is stale.

## 3. Gates before merge

The required checks are those of [pr-review-and-merge.md](pr-review-and-merge.md); a shell adds these:

| Check | What it does |
|---|---|
| Lint, typecheck, test, build | The workspace task graph on every member, dependencies built first; no path filter, so "affected" is the task runner's own graph and cache |
| Stale registry | `node scripts/build-registry.mjs --check` and the release-notes generator's `--check` run in the module contract package's build and lint, so a changed manifest or changelog without its regenerated file fails ([web-shell.md](web-shell.md) section 3). The deploys do not repeat it |
| Version bump | A forward bump of the changed app's version file; an escape label exists |
| Infrastructure | Format, validate, lint and a read-only plan per changed root and tier; a plan that deletes or replaces anything fails; the check passes without running when no infrastructure changed |
| Infrastructure standards | No platform CORS block (the app does CORS), host logging settings, network integration on every web app, gateway enforcement on every API |
| Secret scan | On every pull request |

## 4. The pipelines

**Bundle.** One static-host project per tier. Its build installs, builds the shell client with the per-module
`VITE_<SCOPEENV>_API_BASE_URL` and `_API_SCOPE` pairs, the brand name and the sign-in client and tenant ids,
then checks that the brand icon set exists. The static host rewrites every module prefix and every other path
to the one index page and sets `X-Frame-Options: DENY`, `X-Content-Type-Options`, a referrer policy and a
permissions policy; assets are immutable. Chunking puts the sign-in library and the UI library in their own
chunks, and one copy of each is forced across the shell and every module package.

**API code.** A detect step ships an app when a changed non-markdown file is in the shared packages, in the
kind's reusable workflow, in the app's watch globs, an include path or its own deploy block; a tier ships only
the apps that declare that tier. Each kind (App Service, function app, container app) has its own reusable
workflow; runs are not cancelled in flight. The App Service workflow:

1. Binds the environment and derives the app and resource group names from the tier prefix.
2. Vendors each shared workspace package into the bundle and repoints it as a file dependency. A package must be
   self-contained, list its entry in `files` and have no runtime dependency, else the step fails.
3. Installs production dependencies, assembles the server with a package file the server reads its version from.
4. Skips green when the target does not exist yet.
5. Turns on container logging so a failed boot is captured, records the version served before and the instance
   count.
6. Deploys, then gates on the health route: 200 with exactly the bundle's version on three polls in a row. A
   restart is used only when needed (same or unknown version before, or more than one instance, restarts at once;
   otherwise wait for the new version up to a bound and restart only if the old one still answers), and after a
   restart only a process that started after it counts ([ci-cd-release.md](ci-cd-release.md) section 6, step 7).

Migrations are not a pipeline step: the server applies them at boot, so a broken migration shows as a failing
health gate with the database subsystem named. The pipeline cannot roll one back.

**Infrastructure.** Roots live in one platform list and in each app's deploy descriptor (`infra.<tier>`: the root
path and the state key). The pipeline plans as the tier's plan identity and applies the saved plan as a
privileged identity under an environment, from `main` only. Destroy is manual (the production environment needs
approval, the dev tier none), and a drift job reports. State backends are one storage account per tier.

## 5. The dev tier behind-main guard

Every workflow that deploys to the dev tier first asks the code host how far the branch is behind `main`
(`compare main...<sha>`, three tries, 5 then 10 seconds apart). On `main` it exits at once. A failed read fails
the run (no silent pass). A behind count above zero fails with the command to bring the branch up to date.
Where a repository's rule is to merge `main` into the branch (never rebase or force-push,
[pr-review-and-merge.md](pr-review-and-merge.md)), the failure message names that command instead; the guard
needs only the behind count.

## 6. Branch names

A ticket branch is `<TICKET>-<short-slug>` from `main`; deploy workflows accept only that pattern for the dev
tier and `main` for production and fail on anything else. The pattern is a consumer parameter
([pr-review-and-merge.md](pr-review-and-merge.md) section 2). The branch is up to date with `main` before merge
by the branch ruleset (strict checks) and the merge queue.
