# Changelog

## 2026-10-27 (v1.27.6, own PR lane)

- Design only. `opscenter/DESIGN.md` section 5.3: the `review_lanes` manifest gains the optional `own_pr_lane` field beside `engine_check`, with the policy reference, what the core shows on the lane page (policy as read, open own pull requests with the policy's decision, last decisions), and the rule that the read never writes and the merge is a writer operation pinned to the head seen.

## 2026-10-27 (v1.27.5, repo-check false positives and kit capped table)

- `repo_checks.py` RC012: the import-name to distribution map gains `docx` (`python-docx`), `pptx`, `fitz`,
  `zmq`, `nacl`, `dns`, `grpc`, `slugify`, `websocket`, `socketio`, `engineio`, `bson`, `mysqldb`,
  `faiss`, `gi`, `cairo`, `bluetooth`, `jenkins`, `ruamel`, `snappy`, `wx`, `xlib` and `pythonjsonlogger`.
- RC017 (`scripting-python.1.3`): simple wrapper calls (`str()`, `Path()`, `os.fspath()`, `os.path.join()`) are
  unwrapped before the safe-suffix test, so `str(SECRETS_SRC)` passes; `src` is a safe suffix. A wrapped bare
  secret name still fails.
- RC002 (`pr-review-and-merge.1.6`) and every check that skips tests: the test-path classifier now treats
  `test_*.py`, `*_test.py` and `conftest.py` as tests (it already covered `test/` and `tests/` folders).
- Kit: `.table-wrap[data-capped]` no longer sets `min-height: 16rem`, so a short capped table has no blank
  space under it; the cap stays through `max-height`. Docs and the gallery note follow. Comments no longer name
  the UI standard by rule number.

## 2026-10-26 (v1.27.4, four doc contradictions fixed)

- Docs only. `CONTRIBUTING.md`: the rebase instruction is replaced by the core's rule (never rebase; merge
  `FETCH_HEAD` after `git fetch origin main`, and renumber the changelog top entry above the latest tag when
  another change took the number); the references to a provenance directory that does not exist are removed
  (provenance stays with the contributing account and the pull request description states adopt, adapt or
  reject); the pre-commit hook description now lists everything the hook runs; `--force-with-lease` advice
  removed. `hermes/README.md` follows ("merge rule").
- `templates/overlay/README.md` and `standards/ci-cd-release.md`: a pull request title or body edit runs every
  check (it is a pull request event), not two. `templates/overlay/README.md`: `core-ci.yml` and
  `lint-sweep.yml` are refreshed by every sync, which keeps the `OVERLAY` value, the overlay path prefix,
  lines marked `core-sync: keep` and a `schedule:` block; the runner is set with the `CORE_CI_RUNNER`
  repository variable; the "copy it again" notes for older workflow changes now say a sync refreshes the file.

## 2026-10-26 (v1.27.3, README and CONSUMING brought current)

- Docs only. `README.md` stays the overview and `CONSUMING.md` is the how-to for every channel; nothing is
  duplicated between them.
- `CONSUMING.md`: a channels table (overlay sync with `core-update.yml` and `standards.lock`, the opt-in
  reusable workflow `core-ci-reusable.yml` and its check `core-checks / core-checks`, agent skills through the
  nightly); the `--ui OWNER/REPO[=MODE:PATH]` syntax fixed (it was written with colons); the `pin-file` way and
  the `report_repo` key added; the `CORE_REPO` repository variable named; the reusable workflow's trigger
  behaviour corrected (an edit runs every check); the hand-made tag step removed.
- New sections 8 to 13: the eight statuses (pass, proved, attested, waived, not_applicable, excepted,
  unverified, fail) and exactly how `standards-local/proofs.json` records each, the `core-rule: <id>` tag and
  `PROOF_TAG_ENFORCED`, the nine kit-test rules that read `not_applicable` without UI adoption, RC001 to
  RC022 with how to run `repo_checks.py`, the UI lint config (`data_palettes`, neutral hairlines), the
  scrolling rule and its kit classes (`page-scroll`, `Table` `capped`, `LaneBoard` `fit`), automatic releases
  and how the version is assigned at merge, reporting and contributing, the update flow for an account with
  only the public docs, and what READY means with troubleshooting (a cancelled check, Python 3.9).
- `README.md`: five ways (`pin-file` added) and the three channels; layout and standards tables brought in
  line with the tree (`ingest/` removed, `opscenter/`, `claude/`, `skills/`, `tests/` and the workflows added;
  `web-shell.md` and `hermes.md` listed); the status and proof text now points at CONSUMING; the day-one
  steps name `CORE_REPO` and no longer require `gh` or an invitation; the version example reads from the
  latest release; versioning describes automatic releases; the checks list matches `checks.yml`; the kit
  gallery is no longer described as private.

## 2026-10-26 (v1.27.2, RC012 lock files and import aliases)

- `repo_checks.py` RC012 accepts a pip-tools hashed file (`pip-compile --generate-hashes` output named
  `requirements*.txt`, `constraints*.txt` or `*.lock.txt`) as a lock file for the project it sits beside, or in its
  `requirements/` or `locks/` subdirectory. Every requirement line in the file must carry a `--hash=sha256:`, so a
  plain or partly hashed file is still not a lock. A generated hashed requirements file no longer needs reason
  comments.
- The import-to-distribution table gains `googleapiclient`, `google_auth_oauthlib`, `google_auth_httplib2`,
  `oauth2client`, `httplib2`, `google.protobuf` (to `protobuf`), `markdown`, `magic`, `Crypto`, `ldap`,
  `pkg_resources`, `mpl_toolkits` and `skimage`; the `google-*` family still covers `google.auth`,
  `google.oauth2` and `google.cloud.*`. A truly undeclared import still fails.
- Tests cover each case.

## 2026-10-26 (v1.27.1, RC012 false positives)

- `repo_checks.py` RC012 (every import outside the standard library is pinned) no longer reports a declared
  dependency as missing in three cases. A requirements line is skipped only when it is a real URL, `git+`, `-e`,
  `-r` or option line, so a package whose name starts with those letters (`httpx`) counts as declared. The
  `pyproject.toml` dependency arrays are parsed properly (`tomllib` on Python 3.11+, a Python 3.9 compatible
  fallback that handles extras brackets, quotes, comments and multiline arrays), so an entry such as
  `uvicorn[standard]>=0.30` no longer hides every dependency after it; `project.optional-dependencies` and
  `dependency-groups` are read too. The import-to-distribution alias table gains the `pywin32` modules, `usb`
  to `pyusb` and the `google-*` family, matched case-insensitively with `-`, `_` and `.` normalised. An import
  whose distribution is not declared still fails.
- Tests cover each case and a genuinely undeclared import.

## 2026-10-26 (v1.27.0, proof batch 7: attested reviews and waivers)

- `core-status.py` reports two new statuses, counted apart in the summary and the human line: `attested` (a review
  rule with a valid dated `review` proof: a person looked, the record expires after `$max_review_age_days`) and
  `waived` (a valid `waiver` proof: `ref` to a record file, `date`, `reason` and `reviewed_by`; it sets a rule aside
  for that repo and expires like a review). `proved` now means a `ci` or `test` proof only. A waiver is never
  counted as proof and a broken, stale or reason-less one proves nothing. A review proof without `reviewed_by`
  adds a warning.
- Tests cover attested, waived and each way a waiver is rejected. `standards-local/proofs.json` and CONSUMING.md
  describe the four kinds.

## 2026-10-26 (v1.26.0, proof batch 6: a test proof must name its rule)

- `core-status.py` now checks that the test file a `standards-local/proofs.json` test proof points at carries the
  rule id (a comment such as `core-rule: web-ui.0.8`). Without it the proof still counts and the report gains a
  `warnings` entry (printed as WARNING); from the next release `PROOF_TAG_ENFORCED` turns the warning into a
  problem and the proof stops counting. A tag that is removed, or a test file that is replaced, now makes a proof
  fail instead of passing on file existence alone.
- Tests cover the warning, the tagged case and the enforced mode.

## 2026-10-26 (v1.25.0, proof batch 5: four more rules proved by kit tests)

- Four rules whose behaviour the kit already tests move to `core-ci` with that test as the command, each with
  `requires: ui-adoption` (pass for an app that adopts the kit whole, `not_applicable` otherwise): `web-ui.19`
  (rail state and pin persistence, `tests/shell.test.tsx`), `web-ui.24` (axe on the composite shell and each overlay
  in both themes, `tests/a11y.test.tsx`), `web-ui.26.1` (per-app dismissal keys, `tests/review-fixes.test.tsx`) and
  `web-shell.5` (module CSS scope, `tests/scope-css.test.ts`).
- Acceptance lines narrowed to what the kit test proves (statements unchanged): `web-ui.19` drops the browser
  check, `web-ui.24` covers the kit's composite and overlays rather than an app's routes, `web-ui.26.1` covers the
  storage key rather than the theme sharing, `web-shell.5` covers the selector scope.

## 2026-10-26 (v1.24.0, proof batch 4: web runtime and access rules)

- Four more `repo-check` rules: `web-client-runtime.4.1` (RC019, a bundled app has a bundle size budget check),
  `web-client-runtime.4.3` (RC020, a vite config sets `assetsInlineLimit`), `web-client-runtime.5.1` (RC021, an
  app's client code builds the bearer header in one file) and `rbac.3` (RC022, an app compares permissions by hand
  in one module only). RC021 and RC022 group files per app (`apps/<name>`, `packages/<name>`, `services/<name>`).
  Each has a failing and a passing fixture.
- Acceptance lines narrowed to what each check proves (statements unchanged): the entry chunk size itself
  (`4.1`) and the inline asset size in the built chunk (`4.3`) need a build and stay with the consumer's own
  build step; the checks prove the budget and the limit are configured.

## 2026-10-26 (v1.23.0, proof batch 3: web UI and build rules)

- Five more `repo-check` rules: `web-ui.9` (RC014, test suites run axe and cover both themes), `web-ui.25`
  (RC015, an app that mounts the app shell renders the build card), `web-build.8.1` (RC016, a verify script runs
  every check:* script and each typecheck, lint, build and test script the package defines), `scripting-python.1.3`
  (RC017, no secret-named value or flag in a subprocess argument list) and `web-client-runtime.4.2` (RC018, a vite
  config names its vendor chunks). Each has a failing and a passing fixture; the core passes them.
- Acceptance lines narrowed to what each check proves (statements unchanged): the log-redaction half of
  `scripting-python.1.3`, the route coverage of `web-ui.9` and the hash survival of `web-client-runtime.4.2` stay
  with review.

## 2026-10-26 (v1.22.0, proof batch 2: security, secrets and release rules)

- Three more `repo-check` rules: `secrets-and-credentials.1.4` (RC011, a checkout of another repository carries an
  ssh-key), `scripting-python.1.2` (RC012, every import outside the standard library is in a pinned requirements
  file with a reason comment, or in a declared dependency list with a lock file) and `ci-cd-release.6` (RC013, a
  stateful deploy workflow re-runs CI or waits on a CI job, and checks health afterwards; a static-site or Vercel-only
  deploy is carved out). Each has a failing and a passing fixture; the shipped overlay and the core pass them.
- Two rules bind to a job of the template workflow the repo already runs: `pr-review-and-merge.1.3` to
  `core-changelog` and `secrets-and-credentials.1.6` to `core-secret-scan`, both in `core-ci.yml`. Their acceptance
  lines now say what that job proves.
- Acceptance lines narrowed to what the check proves: the five rules above. Statements are unchanged.

## 2026-10-26 (v1.21.0, proof batch 1: ten rules get a static check, five a core test)

- New rule check kind `repo-check` and `scripts/repo_checks.py` (synced to every overlay). A repo check reads the
  repo's tracked files and returns findings; `core-status.py` runs the check of every `repo-check` rule and reports
  pass (no finding), fail (a finding) or excepted (an active exception names the rule), and `unverified` only when
  the check cannot run. A check passes when the repo holds nothing the rule governs and fails only on a violation
  (or, where the rule demands a thing, on its absence). A line with `core-exception: EXC-NNN` is skipped. Each
  check has a failing and a passing fixture in `tests/test_repo_checks.py`. `check-rules.py` binds every check to
  exactly one rule with the same ref and requires the rule's acceptance line to name it.
- Ten rules move from review or test to `repo-check`, and their acceptance line now says what the check proves:
  `automation-safety.1.9` (RC001, no kill by name or pattern), `pr-review-and-merge.1.6` (RC002, merge calls pass
  the head sha), `ci-cd-release.4` (RC003, no major auto-merge in a renovate config), `ci-cd-release.5` (RC004, a
  trusted-trigger workflow never checks out or runs pull request code), `web-api-runtime.3.3` (RC005, no platform
  CORS list in hosting or infrastructure config), `data-safety-sqlite.2.10` (RC006, a SQLite repo's deploy
  workflows queue and wait for a health endpoint that names the sha; a workflow that only publishes a static site or a Vercel app is carved out), `data-safety-sqlite.2.12` (RC007, no
  destructive migration and no NOT NULL column without a default), `identity-and-people-data.1.7` (RC008, fixture
  emails only on reserved test domains), `web-client-runtime.1.2` (RC009, the auth redirect handled in at most one
  non-test file), `ci-cd-release.9` (RC010, every secret a workflow reads is named in a documentation page).
- Five rules whose acceptance is a test the kit already ships move to `core-ci`, proved in the core before release
  by that test, and count as pass only for an app whose UI adoption is adopted (`check.requires` is `ui-adoption`);
  any other app reports `not_applicable`, a new status counted apart in the summary: `web-ui.0.8` (toast Undo), `web-ui.12` (theme init), `web-ui.18` (count-up), `web-ui.22`
  (changelog parser) and `web-shell.3` (generated registry). `check-rules.py` fails a `core-ci` command that
  names a kit test file that does not exist.
- The ops-center sync lane now merges its sync pull request with `--match-head-commit` on the commit it pushed.
  CONTRIBUTING documents the one repository secret the workflows read.

## 2026-10-26 (v1.20.0, boards and wide tables keep their own scrollbars)

- New UI rule 0.12 (`web-ui.md`, registered as `web-ui.0.12`, a review rule): the page body is one vertical
  scroll container, a board is sized to the window with a floor, a wide table has a capped scroll area with a
  floor, a page header is never capped with a viewport fraction, and `overflow: hidden` is never put on a flex
  parent to fit a board. The proof is loading every route with a board or wide table at a window about 700px
  tall. A row in the gates table records it as a hand-reviewed gate.
- Kit: `page-scroll` class (full height, vertical scroll), `Table` `capped` prop (at most the window height less
  15rem, never under 16rem, a named focusable region so the keyboard can scroll it) and `LaneBoard` `fit` prop
  (the window height less 6rem, never under 360px, sideways scroll on the board edge, each lane scrolls on its
  own). Both props default to off, so existing uses are unchanged. Gallery specimen and tests added.

## 2026-10-26 (v1.18.0, fix: UI lint exempts data palettes and no longer flags neutral hairline dividers)

- Fix, replacing the advisory notes of the previous release: the notes only labelled findings and left them
  failing. `ui_lint.py` now exempts files matched by the optional `data_palettes` globs in `ui-lint.json` from
  the colour-literal rule (UI003), since a chart theme or category colour table holds data colours. Every other
  rule still applies to those files, and a colour literal in any other file still fails.
- The edge-bar rule (UI001) no longer flags a one-sided border under 2px in a neutral grey (a hairline
  divider). A coloured hairline, a 2px or thicker one-sided border and every accent edge bar still fail, and
  the exit code for real violations is unchanged.
- The `::notice` lines, the `N advisory` summary count and the `advisories` key of `--json` are removed.
  `tests/test_ui_lint_advisory.py` is replaced by `tests/test_ui_lint_data_palettes.py`; fixtures and
  `lint/README.md` follow.

## 2026-10-26 (v1.16.0, UI lint advisory notes for data palettes and neutral dividers)

- `ui_lint.py` adds advisory notes. A finding that probably is data rather than theme keeps its finding, its
  `::error` annotation and the exit code exactly as before, and gains a `::notice` line, an `N advisory` count
  in the summary and, with `--json`, an `advisories` list. Two notes: `data-palette` (a UI003 colour literal in a
  file matched by the new optional `data_palettes` globs in `ui-lint.json`) and `neutral-divider` (a UI001
  one-sided border under 2px in a neutral grey). A note never hides or adds a finding and never fails a build.
- Self-test fixtures and `tests/test_ui_lint_advisory.py` cover both notes, the coloured and thick cases that
  carry none, and an unchanged exit code. `lint/README.md` documents the config key and the notes.

## 2026-10-26 (v1.14.1, lint-sweep sets up Node for web repos)

- `lint-sweep.yml` ran the repo's "Lint sweep command" on whatever the runner carried, so on a self-hosted
  runner without Node a web repo's sweep failed with `pnpm: command not found` and was filed as a lint issue.
  When `core-ci.py params` reports `web=true` and a sweep command is set, the job now sets up Node
  (`actions/setup-node`, SHA-pinned) at the repo's Node major, runs `corepack enable` so `package.json`
  "packageManager" picks the package manager, and installs from the lockfile (pnpm, yarn, bun or npm; no
  lockfile is a `toolchain missing` error). A Python-only repo runs no extra step.
- A sweep command that exits 127 now fails the run with `::error::toolchain missing` instead of opening or
  updating the `lint-sweep` issue.
- `core-ci.py params` gains a `node` output: the parameters row "Node major version", else `.nvmrc`,
  `.node-version` or `package.json` engines.node; empty means `lts/*`. Tests cover the output and the template.

## 2026-10-26 (v1.14.0, sanitised and consumer-neutral checks gain a diff mode)

- `check-sanitised.py` and `check-consumer-neutral.py` take `--diff BASE` (the lines `git diff BASE...HEAD`
  adds) and `--staged` (the lines staged for commit). Only added lines are checked, so a hit that already sits
  in a historical file such as this changelog no longer fails a change, and a new hit on an added line does.
  With no argument both still check the whole tree exactly as before.
- The pre-commit hook uses `--staged` and now also runs the consumer-neutral check. The pull request CI job
  runs both checks as `--diff` against the base commit, so a commit made with `--no-verify` is caught there.
  A new `sweep.yml` runs the two full-tree checks weekly.
- Tests cover a pre-existing hit passing in diff mode, a new hit failing, and a `--no-verify` commit caught by
  the CI invocation. Ops center prerequisite P1.

## 2026-10-26 (v1.13.4, release.yml runs on ubuntu-24.04)

- `release.yml` set up Python 3.9 on `ubuntu-latest`, which is Ubuntu 26.04 and has no Python 3.9, so the
  first automatic release (v1.13.3) failed at `setup-python`. It now defaults to `ubuntu-24.04` like the other
  workflows that need the Python floor.
- `core-ci.py workflow-lint` flags `ubuntu-latest` in any workflow that sets up Python, so the combination cannot
  come back. A test covers it.

## 2026-10-26 (v1.13.3, release.yml was invalid YAML; the lint now catches it)

- `release.yml` (v1.13.2) was never valid: an unquoted `description:` value contained `default: ...`, which YAML
  reads as a nested mapping. GitHub rejected the file and reported a failed run on every push (including the
  merge queue's), so the first automatic release did not run and v1.13.2 was tagged by hand. The value is quoted.
- `core-ci.py workflow-lint` (and so the template CI) now flags any `key: value` line whose unquoted value contains
  `: `; block scalars (`run: |`), quoted values, flow collections and comments are skipped. It reports the line
  that broke `release.yml` and nothing in the other workflows. Tests cover the finding, the skips and every core
  workflow file.

## 2026-10-26 (v1.13.2, automatic releases)

- New `.github/workflows/release.yml` and `checks/auto-release.py`: a push to main whose top CHANGELOG entry
  is a version with no tag now gets an annotated `vX.Y.Z` tag on that commit and a GitHub Release whose notes
  are exactly that entry body. Same commit already tagged is a no-op; a tag on another commit, or a top
  version not greater than the latest tag, fails the run and no tag is ever moved. A push with no new entry
  does nothing. `workflow_dispatch` takes an optional commit. Permissions are `contents: write` on a hosted
  runner (`CORE_RUNNER` honoured).
- `gallery-release.yml` gains a `workflow_call` trigger with a `tag` input; `release.yml` calls it after the
  release exists, because a tag or release made with the workflow token starts no other workflow. Pushing a
  tag by hand still triggers it as before.
- CONTRIBUTING.md no longer asks for a hand-made tag. `python3 checks/auto-release.py --dry-run` prints the
  decision for any commit (`--sha`, repeatable `--ignore-tag`) without changing anything.

## 2026-10-26 (v1.13.1, private-list terms removed)

- A consumer account's private list flagged 16 terms on 176 lines of the public tree (hashes only were
  reported). Twelve of the hashes were removed from the current tree by hash: organisation, product and
  vendor names in examples became neutral placeholders, and a sample person name in the kit gallery and
  combobox test changed (the `marks` gallery visual baselines were regenerated). Those twelve hashes are now
  in `checks/denylist.sha256`, so any reintroduction fails the sanitiser. A new test pins them.
- Four hashes were left in place and are NOT in the shared list, because renaming them would break code or
  consumers: two are the core's own feature name (a consumption mode value and a design directory), one is a
  vendor domain used in XAML namespaces and a container registry image, and one is a deploy action name.
  No terms are listed here.
- Earlier commits of the public history still contain the old text; this release changes the current tree
  only.

## 2026-10-26 (v1.13.0, core-update for private repos: App token, dispatch trigger)

- `core-update.yml` (template): when the repository variable `CORE_APP_ID` is set, the job mints a short-lived
  GitHub App installation token with `actions/create-github-app-token` (SHA pinned), scoped to contents,
  pull-requests and workflows write on the repo, and uses it to check out, push and open the pull request,
  so a private repo needs no personal access token. The App's private key is the secret `CORE_APP_PRIVATE_KEY`,
  or any existing secret named by the variable `CORE_APP_KEY_SECRET`. `CORE_TOKEN` stays supported and is used
  only while `CORE_APP_ID` is unset. A missing token now fails the job with one clear message.
- `workflow_dispatch` is now the only default trigger. The template no longer ships a `schedule:` cron:
  GitHub drops scheduled runs of private repositories, so a consumer dispatches the workflow from its own
  scheduler (or adds a cron itself). A sync keeps a `schedule:` block the repo added (`corehash.merge_workflow`).
- The job is serialised with a `core-update` concurrency group so two dispatches never race on one branch.
- CONSUMING.md, README.md, the overlay README and `standards/ci-cd-release.md` describe both token lanes and
  the dispatch trigger. New tests in `tests/test_core_update_app_token.py`.

## 2026-10-26 (v1.12.2, core CI runs on ubuntu-24.04)

- GitHub moved `ubuntu-latest` to Ubuntu 26.04, which has no prebuilt Python 3.9, so every job that sets up the
  Python floor (3.9, the oldest interpreter the core supports for consumers) failed with "version 3.9 was not
  found for Ubuntu 26.04". That broke the core's own `ci` check on every pull request and would break a consumer
  on the default runner.
- The core's `checks.yml`, the `core-ci.yml` template and the reusable `core-ci-reusable.yml` now default to
  `ubuntu-24.04` (still supported by GitHub for years). `CORE_RUNNER` and `CORE_CI_RUNNER` still override it.
  A consumer that sets neither variable gets the fix from `sync-core.py` (template path) or by moving the pin
  (reusable path); one that sets a runner variable was never affected.
- Raising the Python floor is the other fix and is a separate decision (3.9 reached end of life in October 2025).

## 2026-10-25 (v1.12.1, an edit runs every check)

- `core-ci.yml` (template) and `core-ci-reusable.yml`: a pull request `edited` run (title or body) now runs
  every check, like `synchronize`. It used to run only the title and attribution checks. The merge gate reads
  the newest result for the check name `core-checks`, and an edit made right after a push cancels that push's
  run through the concurrency group, so the lighter edit run reported a green `core-checks` for a commit whose
  full checks were cancelled or had failed. Observed on a consumer: a push followed by a body edit seconds
  later left only the light run, and a merged pull request carried no full run.
- Cost: one more single-job run per title or body edit; the one-job budget per run is unchanged.
- Consumers pick it up with `sync-core.py` (template path) or by moving the pin (reusable path). A new test
  asserts no gate excludes `edited` and that the template still triggers on it.

## 2026-10-25 (v1.12.0, reusable core-ci workflow)

- New opt-in distribution path: `.github/workflows/core-ci-reusable.yml`, a `workflow_call` workflow that runs
  the same ONE job `core-checks` with the same named steps, `FULL` and `COMMITS` gating and job budget as the
  template `core-ci.yml` (a test keeps the steps and gating byte for byte equal). A repo, internal or on another
  account, hosted or self-hosted, calls it from a tiny caller pinned to a release sha. It checks out the
  caller's repo at the pull request head and the core at the commit the workflow was called at
  (`job.workflow_sha`), so the pinned scripts always match the workflow. Inputs: `runs-on` (falls back to the
  `CORE_CI_RUNNER` variable, then `ubuntu-latest`), `overlay`, `core-ref`, `core-repository`.
- The check a caller reports is `<caller job> / core-checks`, so `core-checks / core-checks` for a caller job
  named `core-checks`; GitHub offers no way to keep the bare name. CONSUMING.md has the migration recipe, which
  changes the required check in the same sitting as the caller.
- `core-ci.py` and `check-exceptions.py` read the overlay folder named by `CORE_CI_OVERLAY` when it is set (the
  folder above the script otherwise, as before). `core-ci.py required-checks` and `wait-checks` understand a
  caller (`core-checks / core-checks`), `core-status.py` reads the core steps of a caller and the qualified job
  name, and `sync-core.py` leaves a `core-ci.yml` that calls the reusable workflow alone.
- The synced-copy path is unchanged for every current consumer. Docs: CONSUMING.md, `standards/ci-cd-release.md`
  section 2, `templates/overlay/README.md`. Tests in `tests/test_reusable_ci.py`.

## 2026-10-24 (v1.11.1, undici security fix)

- `undici` (dev only, through jsdom) raised from 8.11.2 to 8.12.3, and an `overrides` entry lifts the copy
  pinned by `@scalar/json-magic` from 7.29.1 to 7.30.1. Both close the content-encoding denial of service
  advisory. No kit API or behaviour change.

## 2026-10-24 (v1.11.0, lane board)

Carried over from the previous core repository, where it was opened 2026-10-23 as item D-004 of a
consumer report.

- `LaneBoard`: lanes as columns with cards, a drop indicator, an empty-lane state and an `onMove({ cardId, from, to, index })`
  callback. Cards drag with the pointer, or by keyboard: Space or Enter picks up, left and right choose the lane, up and
  down the position, Space or Enter drops, Escape cancels; every step is announced in a polite live region. The board holds
  no data rules and never reorders itself.
- Tests in `kit/tests/lane-board.test.tsx`, gallery specimen `lane-board`, docs in `kit/README.md`.
## 2026-10-24 (v1.10.0, ops center design)

Carried over from the previous core repository (opened 2026-10-23), where the owner made the decisions
it records on two consumer reports: Table B rows B-01 to B-31 and the 20 assessment decisions, all as
recommended.

- New `opscenter/DESIGN.md`: the layout and the synced copy, slots versus parameters, the loopback
  server with one Host and Origin guard and the `{success, data|error}` envelope, live reads, the single
  default-deny writer and the `/api/approvals` inbox, the cost-gated analyzer and heartbeats, per-file
  schemas on six envelope kinds with the conformance checker and the migration contract, the app on the
  kit shell, the slot interfaces with reference adapters for the code host, work tracker and docs home,
  every parameter including the declared exceptions, the deploy contract, automerge, `adopt`, the build
  plan (P1 to P3, then R1 to R9) and each consumer's migration path.
## 2026-10-24 (v1.9.0, confirm runs its action, D-005)

Approved consumer item D-005 (consumer report on the intake).

- `useConfirm` options take `action`: it runs inside the dialog. While it runs the confirm button shows
  busy and Cancel and Escape are held, so the dialog cannot close half done; a rejection shows its
  message inline (or `errorText`, default "That did not work. Try again.") and keeps the dialog open for
  a retry; `confirm()` resolves true only after the action succeeds.
- `validate` returns an error string to keep the dialog open with the message inline, or null to go on;
  it runs before `action`.
- Without `action` or `validate` the dialog behaves as before. Tests for the busy run, the failed run and
  retry, validation, and the unchanged default; gallery specimen `confirm-action`; docs in
  `kit/README.md`.
## 2026-10-24 (v1.8.0, AccountMenu actions, D-004)

Approved consumer item D-004 (consumer report on the intake).

- `AccountMenu` takes `actions`, buttons shown above Sign out (`{ key, label, onSelect, busy?, tone?,
  icon? }`; `tone: 'danger'` uses the subtle danger button, `busy` shows it working and blocks a
  second click). An action runs without closing the panel.
- `status`, a polite live line for the actions' result (for example "Permissions refreshed"); pass it
  whenever the panel has actions so the live region exists before its text changes.
- New type `AccountAction`. Defaults unchanged. Tests for the unchanged default, an action with its
  status in an open panel, and a busy action; gallery specimen `account-actions`; docs in
  `kit/README.md`.
## 2026-10-24 (v1.7.0, search routing, D-003)

Approved consumer item D-003 (consumer report on the intake).

- `PALETTE_OPEN_EVENT` (the document event that opens the palette) is exported, with
  `onPaletteOpen(listener)`, which hears every open request (a trigger, the feed strip,
  `openCommandPalette`, `openScopedPalette`) with its scope and returns the unsubscribe.
- `SearchTrigger` and `FeedStrip` take `onSearch`: called instead of opening the kit palette, for an
  app that still mounts its own during a migration. Unset, both behave as before.
- Tests for the event export and listener, the unchanged default and the routed trigger through the
  feed strip; gallery specimen `search-routing`; docs in `kit/README.md`.
## 2026-10-24 (v1.6.0, Table phone cards and sticky-head opt-out, D-002)

Approved consumer item D-002 (consumer report on the intake).

- `Table` takes `mobile: 'scroll' | 'cards'` (default `scroll`): with `cards`, at 640px and below each row
  becomes a card of label and value pairs, the label being the column header (`data-label`; a
  `hideHeader` column gets none). The head stays in the accessibility tree, visually hidden.
- `stickyHead={false}` keeps the head in place for a short table inside a card (default true).
- `wrapClassName` adds a class on the scroll wrapper, next to `className`.
- Defaults unchanged. Tests for the defaults, the labels and the wrapper attributes; a real-browser
  check in `kit/visual/interactions.visual.ts` that the rows become labelled cards at 390px and a table
  again at 1280px; gallery specimen `phone-cards`; docs in `kit/README.md`.
## 2026-10-24 (v1.5.0, ThemeToggle system option, D-001)

Approved consumer item D-001 (consumer report on the intake).

- `ThemeToggle` takes `withSystem`: a compact three-way Light, System, Dark control (icon segments
  built on `Segmented`, the labels as accessible names) instead of the flip button, so a user can go
  back to following the OS after picking a theme. `system` is stored as its own value and follows
  `prefers-color-scheme` while it is set; the reveal grows from the pressed segment. New props
  `groupLabel`, `lightLabel`, `systemLabel`, `darkLabel`. Without `withSystem` the toggle is unchanged.
- New icon `IconMonitor`.
- Tests: the default button unchanged, the three-way choice and its storage, custom labels. Gallery
  specimen `theme-system`, docs in `kit/README.md` and `standards/web-ui.md` section 6.

## 2026-10-24 (v1.4.0, month calendar grid)

Carried over from the previous core repository (item D-011 of a consumer report, approved).

- New `MonthGrid` primitive: weeks of day cells, weekday headers, event chips with a "+N more"
  line, a today marker (`aria-current="date"`, a filled number) and roving keyboard navigation (arrows,
  Home, End, PageUp, PageDown, Enter and Space to pick a day). Dates are ISO day strings, so no time zone
  moves a cell. Events arrive as a list; `renderEvent`, `renderDay` and `dayHint` are the slots, and what an
  event means (coverage, shifts, leave) stays in the app. `onMonthChange` fires when keys leave the month.
  Exports `monthWeeks`, `isoDay` and `addDays`.
- Tests in `kit/tests/month-grid.test.tsx`, a gallery specimen `month-grid` and a README line.
- Known limit, noted in `kit/README.md`: an event covers one day; multi-day spans are not supported.

## 2026-10-24 (v1.1.1, public repository automerge)

- `.github/workflows/automerge.yml`: the repository is public, so it merges through the owning org's
  reusable automerge workflow (pinned to a commit) on hosted runners, with a twice daily safety-net sweep.
- `checks/check-sanitised.py`: `.github/workflows/automerge.yml` joins `LICENSE` and `renovate.json` as
  the only identity files exempt from the term lists (it names the org whose workflow it calls). Test
  extended.

## 2026-10-24 (v1.1.0, the public core needs no account to read)

- `templates/overlay/scripts/corehash.py`: `clone()` and `latest_tag()` try `gh` first, then plain `git`
  over anonymous HTTPS (`git_url()`, overridable with `CORE_GIT_BASE`). A machine or CI job without
  `gh`, an account or a token can sync, check the pin and find the newest release.
- Docs: README "Day one" (no invitation or sign-in), "CI that builds the app" (a plain checkout, no deploy
  key), the FAQ and the troubleshooting table; hermes/README.md managed hosts (read over HTTPS, no host
  key); CONSUMING.md and the `core-update.yml` comment (`CORE_TOKEN` only opens the PR on the
  consumer's own repo).
- Tests: the git fallback (highest semver tag, clone at a ref, one plain message for a missing ref).
## 2026-10-24 (v1.0.0, core-ci is one job)

BREAKING for every consumer's merge gate. The workflow file changed: copy `core-ci.yml` again, then in
the merge gate require `core-checks` and remove the old per-check names in the same change
(`python3 scripts/core-ci.py required-checks --fix` prints both).

- `templates/overlay/.github/workflows/core-ci.yml`: one job, `core-checks`, with every check as a named
  step (`core-secret-scan`, `core-ascii`, `core-python` and the rest). A failed step does not stop the
  others. A pull request runs every step; a title or body edit runs only `core-pr-title` and
  `core-attribution`; a merge queue entry (new `merge_group` trigger) runs every step that does not
  read the pull request; a push to the default branch runs only `core-secret-scan`. A busy consumer
  ran 12 jobs per pull request run and 7 per push; it now runs 1.
- `core-status.py`: a rule's `check.jobs` may name a job or a `core-` step; `--ci` reads step results,
  and fills the steps a push run skipped from the run on the head of the last merged pull request
  with the same tree.
- `core-ci.py required-checks`: the gate needs `core-checks`; old per-check names a gate still requires
  are reported as obsolete, and `--fix` prints the commands that remove them.
- `checks/check-rules.py`: overlay-ci bindings are checked against the template's jobs and steps.
- Docs: `standards/ci-cd-release.md` section 2 (required checks and the migration), the overlay README
  "CI workflow", CONSUMING.md.
- Tests: the one-job template contract (one core job, unique core- steps, every check step runs after
  a failure, push runs only the secret scan), obsolete gate names, step results and the push-run fill.

## 2026-10-24 (v0.102.0, consumer reports go to a private intake only)

The core is moving to a public repository, so a consumer report (one account's design inventory and
evidence) must never be filed on it.

- `hermes/report.py`: new `report_target()`. The nightly files the upward report only in `report_repo`
  (machine config, or `CORE_REPORT_REPO`), and only when that repository is not the core and reads as
  `PRIVATE`. Unset, equal to the core, not private or unreadable: nothing is filed and the run says why.
- `hermes/consumption.py`: report issues (peers and the account's own) are read from `report_repo`;
  core pull requests are still read from the core. Approvals are matched against the intake owner, a
  user, so they keep working when the core belongs to an organisation.
- `hermes/setup.py --report-repo OWNER/REPO` records the intake. The `core-consumer-report` skill files to
  the intake and stops when it is unset, the core, or not private.
- Docs: CONSUMING.md, hermes/README.md and README.md say where reports go.
- Tests: the target guard (no intake, the core, public or internal, unreadable visibility) and the feed
  reading reports from the intake only.

## 2026-10-23 (v0.101.0, palette grouping, ranking and shortcuts)

- `CommandPalette`: `PaletteItem` takes `group` (rows gather under a header, groups in the order they first
  appear in the ranked results) and `shortcut` (keys in the shortcut grammar, shown on the row in place of
  the kind). Inside a `ShortcutLayer` each item shortcut is registered in the shared registry, so the help
  sheet lists it and the keys run `onSelect`. New `filters` and `allLabel` props add tabs under the input,
  cycled with Tab and Shift+Tab, and the footer hint names the key. #115 D-008
- Ranking: `filterPaletteItems` now scores matches (exact label, label prefix, word start, label substring,
  then exact, prefix and substring keyword, then kind) and keeps ties in the given order. New exports
  `scorePaletteItem`, `groupPaletteItems` and the type `PaletteFilter`. Items without the new fields behave
  as before apart from the finer ranking.
- With v0.98.0: a custom `rank` and `limit` apply inside the active filter tab, and a row with both a
  `badge` and a `shortcut` shows the keys next to the badge. When a `toolbar` is present Tab keeps its
  native move into the toolbar and the filter tabs join the tab order instead of cycling on Tab.
- Tests in `kit/tests/palette-groups.test.tsx`, a browser check of the filter tabs in
  `kit/visual/interactions.visual.ts`, grouped and filtered gallery palette, README and
  `standards/web-ui.md` text. The gallery sections list gains the `freshness` specimen.

## 2026-10-23 (v0.100.0, freshness grid)

- New `FreshnessGrid` (with `formatAge`, `liveFreshness`): one tile per upstream source over a
  `{ id, label, state, ageSeconds, thresholdSeconds, reason }` shape, with a state badge, an age that
  ticks every 15 s between polls and a fresh source that turns stale at its threshold without a refetch.
  A failing source shows the last failure reason, others the stale threshold. #115 D-003
- Tests in `kit/tests/freshness-grid.test.tsx`, a `freshness` gallery specimen and a README line.

## 2026-10-23 (v0.99.0, tile reorder end zone and edge side, #117 K-11)

One owner-approved item from the consumer report #117.

- `useTileReorder` (#117 K-11): returns `endZoneProps` for the empty space after the last tile, so a drop
  there moves the dragged tile last (hidden tiles keep their place, and an already last tile says so). A new
  option `edge` (`true` or `'x'`, or `'y'`) reads the cursor against the tile midpoint, places the drop before
  or after that tile and sets `data-drop-edge` on the tile under the cursor for the indicator (an outline with the target half tinted). The horizontal
  sides flip in a right to left list. Without `edge` a drop behaves as before, and `data-drop-target` still
  carries the highlight.
- Tests in `kit/tests/tile-reorder-edge.test.tsx` (end zone drop, already last, hidden tile, highlight reset,
  both axes, right to left, keyboard unchanged, axe). Gallery specimen `tile-edge`. Docs in `kit/README.md`
  and `standards/web-ui.md`.
## 2026-10-23 (v0.98.0, palette ranking, toolbar and richer rows, #117 K-10)

One owner-approved item from the consumer report #117.

- `CommandPalette` (#117 K-10): an optional `rank(query, items)` replaces the substring filter (the default
  stays the substring filter), a `limit` prop caps the rows (default 50, `Infinity` allowed, applied to a
  custom `rank` too) and a `toolbar` slot under the search row holds filter chips, in a group named by
  `toolbarLabel`. Keys pressed inside the toolbar keep their own meaning, so Enter on a chip never opens a
  result. `PaletteItem` gains an optional `description` (second line) and `badge` (status mark). Recent first
  order and the scope rule need no change: the host controls `items` order for an empty query and can drive
  `open` itself.
- Defaults leave every current palette unchanged. Tests in `kit/tests/palette-rank-toolbar.test.tsx` (default
  filter, rank order and empty query, limit forms, row markup, toolbar keys, axe). Gallery specimen
  `palette-rank`. Docs in `kit/README.md` and `standards/web-ui.md` section 13.

## 2026-10-23 (v0.97.0, meter info tone)

- `Gauge` and `RingProgress` (and `MeterTone`) gain an `info` tone, drawn with `--info`, so a ring or
  gauge whose colour is not a status (a share, a category) is expressible. It is fixed only: thresholds
  never produce it and its value text carries no state word. Existing meters are unchanged (#117 K-9).
- The docs and the prop comments now state that `thresholds` are in the units of `value` and `max`
  (not a 0 to 1 share) and that higher is worse unless `higherIsBetter` is set, so a caller moving from
  fraction pairs can convert (#117 K-9).
- Tests cover the tone style, the value text and thresholds in value units. A gallery specimen shows
  the info ring.

## 2026-10-23 (v0.96.0, multi choice lookup in the filter panel)

- `FilterPanel`: a `lookup` field takes `multiple: true`. The cell keeps several chosen options as
  removable chips (a list named "Selected <label>", a "Remove <option>" button each) above the same
  combobox and emits one `in` clause of the chosen values. Chosen options drop out of the suggestions,
  Backspace on an empty input removes the last chip, and the loader, abort signal, status line and
  keyboard behaviour are unchanged. `draftFromFilters` seeds the chips from an `in` clause, and
  `FilterDraft` also holds a list of options. Without `multiple` the lookup is unchanged. #117 K-8
- Tests in `kit/tests/filter-bulk.test.tsx`, a Reviewers specimen in the filter panel gallery, and the
  matching text in `standards/web-ui.md` and `kit/README.md`.

## 2026-10-23 (v0.95.0, record preview seed)

- `RecordTypeDef` takes an optional `seed(ref, context?)` and `merge(seed, live)` (#117 K-7). The dialog paints
  the seed at once instead of the skeleton, marks the body `aria-busy` and `data-pending` while the live `load`
  runs and merges the live result over the seed. The loading, error and Retry handling stays on `load`, so a
  host no longer moves the fetch into the body to get a fast first paint. A seed that returns nothing or throws
  keeps the skeleton and a `merge` that throws shows the error state.
- `RecordBodyContext` gains `reload()` (a quiet refresh after an edit in the body, the body stays on screen) and
  `context`. `open(ref, context?)` and `RecordChip` (`context` prop) take an optional bag that reaches the seed
  and the body. New exported type `RecordOpenContext`.
- Defaults are unchanged: a type with no seed behaves exactly as before.
- New `kit/tests/record-preview-seed.test.tsx` and a gallery specimen `record-preview-seed`. Docs in
  `standards/web-ui.md` and `kit/README.md`.
## 2026-10-23 (v0.94.0, facts: lazy disclosure, status tones, layout hook)

- `Disclosure` gets opt in `lazy` (#117 K-6): the children mount when the panel opens and unmount on close.
  The panel element stays, hidden and empty, so `aria-controls` always resolves. Default off, so the
  panel keeps its children while closed as before.
- `FactTone` widens with `success`, `warning`, `urgent`, `danger` and `info`, the same tokens the stat
  value uses (#117 K-6). The value text must still say the state, ink is never the only signal.
- `FactRow`, `FactList` and `Disclosure` take a `style` passthrough merged over their own custom
  properties, and `--disclosure-gap` joins `--fact-gap` and `--fact-label-width` as the documented
  spacing route (#117 K-6). Defaults emit no style attribute, so existing consumers are unchanged.
- Tests in `kit/tests/markdown-facts.test.tsx`, a gallery specimen in Facts, docs in `standards/web-ui.md`
  and the kit README.
## 2026-10-23 (v0.93.0, pagination for an unknown total)

- `Pagination` `total` is optional (or null) for a server paged list that cannot say how many rows exist.
  It then reads "Page N, N on this page" from the new `itemCount` and does not invent a last page.
  New `hasMore` decides Next when given (with or without a total), otherwise a full page (`itemCount`
  equal to `pageSize`) keeps Next on and a short one turns it off. New `onPage(page)` gets the target
  page for Previous and Next when `onPrev` or `onNext` is not given. A known total, and every current
  consumer, renders and behaves as before. #117 K-5
- `usePagination(null)` supports an unknown total: no last page to clamp to, and `props.total` is left
  out so it spreads straight onto `Pagination`.
- New `kit/tests/pagination-unknown-total.test.tsx`, a gallery specimen and docs in `kit/README.md` and
  `standards/web-ui.md`.

## 2026-10-23 (v0.92.0, free text fallback for Combobox, #117 K-4)

One owner-approved design item from the consumer report #117.

- Free text fallback for `Combobox` (#117 K-4): a lookup that cannot work at all no longer leaves the
  user with "no match" and no way to add anything. `search` rejecting with the new `UnavailableError`
  (or any error with `unavailable: true`, see `isUnavailableError`), or `onSearchError` returning
  `'unavailable'`, switches the part to an `unavailable` state. The input becomes a validated free
  entry field (no combobox role, no list, no further lookups), a one line hint shows the message
  (`messages.unavailable`, or the `validate` message while the text is invalid), and Enter adds
  `{ free: text }` (`ComboboxFreeEntry`) through `onSelect` once `validate(text)` accepts it.
  `validate` returns null, undefined or true for fine, a message string or false for invalid
  (`messages.invalid`). `defaultUnavailable` starts in the state. An invalid text is `aria-invalid`
  and described by the hint, a polite live region announces the hint.
- Opt in, nothing changes for a current consumer: the second type argument defaults to `never`, an
  unmarked failure still shows the error state with retry, and no specimen changes except the new
  card.
- The input is 44px tall on a coarse pointer, the same touch height as the rows under it (before, only
  rows and the retry button were). Documented that ArrowUp and ArrowDown wrap.
- Tests in `kit/tests/combobox.test.tsx` (marker helpers, entering the state from both triggers, the
  retry state kept for an unmarked error, Enter and validate in both outcomes, no `validate`, empty
  text, `clearOnSelect`, messages, Field description and axe in both text states, arrows wrap).
  Gallery: a card with the state at rest and a live one. Visual baselines are generated in CI.
## 2026-10-23 (v0.91.0, root rules option in the scope plugin, #117 K-3)

- `scopeModuleCss` takes `root: 'wrapper' | 'document'` (default `wrapper`, today's behaviour). In `document`
  mode, for a host that sets `data-module` on the document element and styles it from module sheets,
  `:root` and `html` stay on the document element and are scoped to it (`:where(html[data-module="<id>"])`),
  and `body` and `#root` stay descendants of it (`:where([data-module="<id>"]) body`). The selector
  helper `scopeSelector` takes the same option, and scoping twice still gives the same selector.
- New `keyframes: 'warn' | 'strict' | 'rename'` option (default `warn`, `strictKeyframes: true` still means
  `strict`). `rename` prefixes an unprefixed keyframes name with `<id>-` and rewrites the `animation` and
  `animation-name` references in the same sheet (vendor prefixes and nested at-rules included, quoted text
  and function arguments untouched). A rename that would collide with an existing name is an error, and a
  name that is not a plain identifier stays a warning.
- Tests in `kit/tests/scope-css.test.ts` (both root modes through PostCSS and applied in jsdom with the
  attribute on the document element, the default unchanged, rename cases, option validation). Documented
  in `standards/web-shell.md` section 5 and `kit/README.md`.
## 2026-10-23 (v0.90.0, manifest extensions in the registry generator, #117 K-2)

- `kit/scripts/build-registry.mjs` takes host manifest keys, opt in. `--allow-keys a,b,x-*` (repeatable,
  a trailing `*` is a prefix) lets a manifest carry its own keys. They are carried into the generated entry
  after the seven kit fields, sorted, and typed: the file exports `ModuleExtras` inferred from the values
  and types `MODULES` as `RegistryEntry<ModuleExtras>`. A changed host value fails `--check`.
- `--extra-accents brand` adds host accent names to the kit list. The generated file exports `ModuleAccent`
  (`AppAccent` or the host names). The host owns the CSS for the extra accent.
- `--validate-with check.mjs` loads a host hook (default or `validate` export) called with
  `(manifest, { label, dir, root })` for every manifest, for checks such as a client path or a folder that
  must equal the id. `run()` takes it as `{ validate }` in a third argument, `runCli()` is the loading entry.
- `ModuleManifest`, `RegistryEntry`, `GeneratedRegistry` and `ModuleDescriptor` take optional type
  arguments for the host's own members and accents (`ModuleDescriptor<TRoutes, TExtra, TAccent>`).
  The defaults keep every current use unchanged. With no new option the generator output is byte for byte
  as before, and an unknown key or accent is still an error.
- Tests in `kit/tests/build-registry.test.ts` (parsing, key matching, type inference, hook, typecheck of a
  committed generated fixture in `kit/tests/fixtures/registry-host`). Docs in `standards/web-shell.md`
  section 3 and `kit/README.md`.
## 2026-10-23 (v0.89.0, switch control in the collapsed rail, #117 K-1)

One owner-approved kit item from the shell verification report. Both options are opt in, so every current
consumer renders exactly as before.

- `Rail` (#117 K-1): new `keepBrandSlotCollapsed` (default false). The collapsed rail still hides the
  `brandSlot` unless it is set, then the slot stays, centred on its own line under the brand mark
  (`data-keep` on the slot). A host with its own control no longer needs a sheet override of the kit rule.
- `ToolSwitchButton` (#117 K-1): new `collapsible` (rail form only). In a collapsed rail at desktop width
  the control becomes its mark with a small corner glyph chip, and the name, description, tooltip, `T`
  shortcut hint and popup state stay as in the full form. New `variant="mark"` is that collapsed form on its
  own. Both are CSS only, so there is no state to keep in sync. A hover or pin that opens the rail shows the
  full form again.
- Enter on the current tool stays a no op in the launcher, now covered by a test that opens it from the
  collapsed control.
- Docs in `standards/web-shell.md` section 10 (the collapsed rail paragraph) and `kit/README.md`. Gallery:
  the collapsed form shows in the tool switcher specimen.
- Tests in `kit/tests/shell-switcher.test.tsx` (defaults unchanged, attributes, same name and description in
  every form, opens from the kept control, sheet rules, axe).

## 2026-10-23 (v0.88.0, pin-file consumer mode)

- New consumer mode `pin-file` (`hermes/pin_file.py`, `hermes/setup.py --ui OWNER/REPO=pin-file:PATH`): for
  a repo that records the core as one `KEY=<tag>` line, for example a deploy repo whose host syncs the
  pinned release at deploy time. The nightly reads the pin from the default branch and, when it is behind,
  rewrites the line in a throwaway worktree, runs the entry's `after` commands (a checksum regeneration,
  say), commits as the clone's noreply identity, pushes `chore/core-pin-<release>` with retry and opens the
  pull request with `--body-file`. The class is approval-gated: the repo's own merge path takes it. An open
  pull request is reported (red CI as a problem), `--check` writes nothing, and the worktree is always
  removed.
- Optional `metrics` in the entry push two gauges to a Pushgateway after every check,
  `<prefix>core_pin_behind` and `<prefix>core_pin_last_check_timestamp_seconds`, so a stuck bump turns
  into an alert. A failed push is an info line only.
- The consumption feed reads a pin-file consumer's release from its pin line; the upward report skips it
  (a pin line has no kit to scan).
- New `tests/test_v088.py` runs it against a fixture remote.

## 2026-10-23 (v0.87.0, pushes retry a dropped connection)

- `merge-pr.py` and `hermes/ops_center.py` push with a large HTTP buffer and retry a transient network
  failure (a dropped connection, a 5xx, a timeout) up to three times, 10 seconds apart. A rejection (a
  hook, a failed lease, a protected branch) is never retried. Pushing a pull request with many screenshot
  baselines dropped the connection twice before.
- New `tests/test_v087.py`.

## 2026-10-23 (v0.86.0, an ops center sync commits the targets.map copies)

Found on the first pull request apply of a repo whose overlay is a subfolder with a `targets.map`.

- `hermes/ops_center.py` commits every destination in the overlay's `targets.map` with the sync (new
  `target_paths`), next to the overlay folder and the template workflows. Before, the sync wrote the copy
  (for example a UI package's token stylesheet) but left it out of the commit, so the repo's drift check
  failed on the pull request and the apply rolled back. A destination outside the repo is skipped.
- A failure of a kind already reported is no longer silent: the nightly prints it as an info line marked
  "still failing, reported before", so a run started by hand never shows an empty result after a failure.
- New `tests/test_v086.py`.

## 2026-10-23 (v0.85.0, tooltip layer adopts native title, #115 D-016)

One owner-approved design item from the consumer report #115.

- Tooltip layer (#115 D-016): `TooltipLayer` now serves an element with a native `title` too. On first
  hover or keyboard focus the text moves to `data-tip`, so the browser's own slow, unstyled tooltip never
  shows and the page has one tooltip. A control with no other accessible name (an icon-only button) keeps
  the text as its `aria-label`, so removing `title` does not remove its name. An element that already has
  `data-tip` is left alone, and an empty `title` is dropped.
- Tests in `kit/tests/tooltip-title.test.tsx` (hover, keyboard focus, icon-only name with axe, existing
  label kept, existing `data-tip` kept).
## 2026-10-23 (v0.84.0, table density, #115 D-007)

One owner-approved design item from the consumer report #115.

- Table density (#115 D-007): `Table` takes `density` (`comfortable`, the default, or `compact`). Compact
  tightens the cell and header padding for long, scan-heavy lists. It applies only to a fine pointer: a
  touch screen keeps the comfortable rows, so a row stays easy to hit. `ListTable` rows keep their own
  spacing and are not changed.
- Gallery shows a compact table under the default one. Visual baselines are generated in CI. Tests in
  `kit/tests/table.test.tsx` (the attribute, the default, and rows and roles unchanged).
## 2026-10-23 (v0.83.0, noreply merges with no account setting)

A consumer could not turn on the GitHub email privacy settings v0.82.0 required: its account also pushes
to repositories that expect another address, and "Block command line pushes that expose my email" would
have rejected every one of those pushes. The core now keeps every address out of history on its own side,
so no contributor changes any account setting (owner decision, #117).

- `merge-pr.py` builds the squash commit itself where the repo allows rebase merging: one commit on the
  base branch tip holding the pull request's merged tree (`git merge-tree --write-tree` when the base moved
  on), titled `<title> (#<n>)` with the pull request body, authored and committed by the signed-in
  account's noreply address. It pushes it to the pull request branch with `--force-with-lease` on the head
  it read, waits for the checks with `core-ci.py wait-checks` (`--timeout`, default 60 minutes) and merges
  it with `--rebase`, which keeps the author. A branch already in that shape is merged without a new push.
  A fork branch, a moved head, a conflict or failed checks refuse (exit 2) and merge nothing. It works with
  plumbing only, so the work tree is never touched (git 2.38 or later).
- Where the repo does not allow rebase merging, `merge-pr.py` keeps the squash merge with the noreply
  author hint and the refusal of non-noreply commits; the fix it names is "Allow rebase merging", never an
  account setting. The leak recovery names the same.
- `pr-review-and-merge.md 1.18` (`must`) is rewritten: only noreply author emails land in history, with no
  account setting required. `rules.json`, the generated `core-practices` skill, `CONTRIBUTING.md` and
  `CONSUMING.md` follow.
- `hermes/email_privacy.py` is removed, and `hermes/setup.py` and the nightly no longer read
  `gh api user/emails` (the nightly's step 6 is gone; the consumption feed is step 6 again).
- New `tests/test_v083.py` runs the git side for real against a fixture remote.

## 2026-10-23 (v0.82.0, mandatory email privacy, workflow sync)

Email privacy becomes a mandatory rule with enforcement, and a sync now refreshes the overlay's template
workflows in the consumer repo (a gap a consumer found).

- Email privacy (owner decision, `pr-review-and-merge.md 1.18`, `must`): every account that commits to or
  opens pull requests on a consumer repo or the core turns on "Keep my email addresses private" and "Block
  command line pushes that expose my email". A GitHub squash merge takes the pull request author's primary
  email unless that setting is on, and the merge API's author hint is ignored. The rule text, `rules.json`,
  `CONTRIBUTING.md` and `CONSUMING.md` say so.
- `merge-pr.py` reads every commit of the pull request first and refuses (exit 2) when one carries an author
  or committer email that is not a noreply address, naming the commit, the account and the domain only.
  After the merge it re-checks the merge commit as before and, on a leak, prints the exact recovery (an
  owner-approved rewrite: the account settings, the amend and `--force-with-lease` push while the commit is
  the tip, `git filter-repo --mailmap` otherwise, moving tags) and exits 1.
- New `hermes/email_privacy.py`: `hermes/setup.py` and the nightly (new step 6) read `gh api user/emails`;
  a primary address whose visibility is not `private` is a problem line, and a token without the scope gets
  the `gh auth refresh -h github.com -s user` command. The nightly reports each kind once until a clean run.
- Workflow sync: `scripts/sync-core.py` refreshes the template workflows the repo already has
  (`.github/workflows/core-ci.yml`, `core-drift.yml`, `core-update.yml`, `lint-sweep.yml`, at the root of the
  git work tree) and keeps the repo's settings: the `OVERLAY` env value, the overlay path prefix in front of
  `core-drift.yml`'s relative paths, and every template line marked `# core-sync: keep` (the cron lines of
  `core-drift.yml`, `core-update.yml` and `lint-sweep.yml` are marked). Other workflows are never touched and
  a missing template workflow is never added. When `core-ci.yml`'s job names change, the sync prints the
  old -> new required-check names (and appends them to the file `CORE_SYNC_NOTES` names).
- `hermes/ops_center.py` commits the refreshed workflows with the sync and puts the refreshed list and the
  required-check changes in the sync pull request body and the nightly line; `core-update.yml` writes its
  pull request body with `--body-file` and includes the same lines. A `CORE_TOKEN` needs workflows write to
  push the refreshed files.
- Tests in `tests/test_v082.py`: merge refusal, the recovery text, the email check and its once-per-kind
  state, the workflow merge rules, the renamed check names, and `sync-core.py` against a fixture core and a
  fixture consumer repo whose overlay is a subfolder.

## 2026-10-22 (v0.81.0, stat tile delta and selection, modal meta slot and action icon, directory names, #115 D-013 D-014 D-015)

Three owner-approved design items from the consumer report #115, shipped as small additions to existing
kit parts. The parts that were already in the kit are named in each entry.

- Stat tile (#115 D-013): `StatTile` takes `delta` (`{ text, direction }` with `up`, `down` or `flat`),
  `selected` and `tip`. The delta is an arrow plus text with a hidden direction word, so the colour never
  carries the meaning. `selected` marks the active filter (a ring on the tile, and `aria-pressed` when the
  tile is interactive). `tip` is served by the shared tooltip layer. New type `StatDelta`.
- Modal meta slot and action icon (#115 D-015): `Modal` takes `meta`, rendered beside the title and outside the
  accessible name (the dialog is named by the title alone). `ModalAction` takes `icon`, shown in the primary button. The rest of the
  hub's modal action object was already in the kit: `danger`, `loading`, `disabled`, `cancelLabel: null` to
  hide Cancel, and `footerStart` for a left side note.
- Directory names (#115 D-014): `initialsOf` reads "Last, First" as "First Last" and ignores a trailing note
  in parentheses. The stable hue from the name has been in `Avatar` since v0.12.0.
- The visual test that screenshots every specimen gets the extended time budget (`test.slow()`), as the axe test
  already has, because it timed out on a busy runner.
- Gallery stat specimen shows a delta tile, a selected tile and a tip in both themes. Visual baselines are
  generated in CI. `kit/README.md` notes the directory name rule. Tests in
  `kit/tests/stat-modal-avatar.test.tsx` (delta words and arrow, no delta, `aria-pressed` rules, tip, click and
  keys, the modal icon, the name rules, axe).

## 2026-10-22 (v0.80.0, polling hook and stacked progress bar, #115 D-001 D-002)

Two owner-approved design items from the consumer report #115.

- `usePolling` (#115 D-001): loads at once and refreshes on an interval. It follows
  `web-client-runtime.md` 3.8: no poll fires while the document is hidden, and one immediate refresh runs
  when it is visible again. A poll never overlaps itself, an older reply never replaces a newer one, a failed
  poll keeps the last good data and sets `error`, and `reload()` loads now. `enabled` pauses it and
  `whileHidden` opts out of the pause. The rule in 3.8 now points at the hook.
- Stacked progress bar (#115 D-002): `ProgressBar` takes `segments` (`value`, `tone`, `label` each) drawn left
  to right of `max`, scaled down if they exceed it. The spoken value lists each part, so no part is told by
  colour alone. A bar with no `segments` is unchanged.
- Gallery shows a stacked bar. Visual baselines are generated in CI. Tests in
  `kit/tests/polling-segments.test.tsx` (interval, hidden pause and resume, hidden at mount, no overlap,
  last good data, disable and unmount, segment widths, scaling, axe).

## 2026-10-22 (v0.78.0, generic icons, #115 D-005)

One owner-approved design item from the consumer report #115, shipped as a kit part.

- Nine generic icons (#115 D-005): `IconCalendar`, `IconClock`, `IconEdit`, `IconEye`, `IconEyeOff`,
  `IconFolder`, `IconList`, `IconMail` and `IconTrash`, drawn like the existing chrome icons (24 unit
  box, 2 unit stroke, `currentColor`, decorative by default, `size` prop). The tenth icon the report
  named, an external link, already exists as `IconExternal`.
- Gallery specimen `icons` ("Generic icons") shows all nine in both themes. Visual baselines are
  generated in CI.
- `kit/README.md` lists the icons. Tests in `kit/tests/icons-generic.test.tsx` (each icon's name,
  hidden from assistive technology, `currentColor`, size and attribute pass-through, axe).

## 2026-10-22 (v0.77.0, consumer findings: core- job names, gate trigger, parameters rows, wait progress, core.bare)

Five findings from the consumer report #115, fixed together.

- **core-ci job names (migration).** Every job of the template `core-ci.yml` now has an id and a
  check name that start with `core-` (`core-python`, `core-identity`, `core-ascii`; the helper is
  `core-setup`). The template's `python` job and a repo's own `python` job used to share a check
  name, so a merge gate keyed on check names read the two as one. `rules.json` `check.jobs` and the
  acceptance lines, the standards docs, `core-ci.py required-checks` and `wait-checks` (which read the
  names, `name:` when set), `core-status.py` and `checks/check-rules.py` (which now fails a template
  job without the prefix or whose `name:` differs from its id) use the new names. **Consumers: copy
  `core-ci.yml` from the template again, then run `python3 scripts/core-ci.py required-checks --fix`**:
  it prints the new names the gate does not require and, under "Replace each", every old core-ci
  name the gate still lists (`python -> core-python`). Until the workflow is copied again,
  `required-checks` notes that the copy predates the new names and `core-status.py` reports the
  overlay-ci rules as failing. templates/overlay/README.md "Job names (v0.77.0)" has the steps.
- **Merge-gate trigger.** `standards/ci-cd-release.md` section 5 and the overlay README say a merge
  gate triggered by `workflow_run` lists `core-ci` (and `lint-sweep` when it requires that check) next
  to the repo's own workflows, with an example; a gate that lists only its own workflows never runs
  when a core-ci job finishes last. `core-ci.py workflow-lint` warns (it does not fail) on a
  `workflow_run` trigger that lists workflows but not `core-ci`.
- **Template parameters rows.** `sync-core.py` appends every row of the template parameters sheet
  that the overlay's `standards-local/parameters.md` lacks to its table, with the template's value
  cell and a marker comment (`<!-- sync-core: row added from the template vX.Y.Z; set a value -->`),
  never changes an existing row (a label matches by its prefix, as scripts read it) and prints one
  line naming the rows. A missing `Commit emails` row had failed a sync's identity check. The
  ops-center apply commits the sheet with the sync.
- **Progress while waiting for checks.** `core-ci.py wait-checks` prints a progress line at most every
  5 minutes (`--progress MIN`): minutes waited and checks done, pending and failed. The nightly streams
  that line from an ops center's sync pull request to its own output as it comes (`hermes/nightly.py`
  `sh(..., echo=...)`, `hermes/ops_center.py` `progress_printer`), so a 30 minute wait is visible.
- **core.bare flipping to true (cause found).** The ops-center apply pushed from its gate worktree.
  Git hands a hook `GIT_DIR`, from a worktree `<clone>/.git/worktrees/<name>`; a pre-push hook, or the
  tests it runs, that calls `git init` with it set reinitialises the clone and, since that path does
  not end in `/.git`, writes `core.bare = true` into the clone's shared config, after which `git pull`
  fails. Pushes (and the branch delete on rollback) now run from the clone, so the hook runs as it does
  for a push by hand there. The nightly also drops `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE` and the
  other variables that point git at one repository from every command it runs. A guard checks the core
  clone and every consumer clone before and after the run (and around each ops-center apply), sets
  `core.bare = true` on a clone with a work tree back to false, and reports it once per clone.
  CONSUMING.md section 3 says why a repo's fixture tests should drop those variables too.
- Tests: `tests/test_consumer_findings.py` (template names and the check-rules guard, stale names and
  the re-copy note, core-status by the new names, the trigger warning in both list forms, the rows
  added by a real `sync-core.py` run and by the helper, progress with a fake clock, streaming and the
  dropped variables, the reproduced flip from a worktree push, core.bare false after an ops-center
  apply whose pre-push hook runs `git init`, and the guard).
- **Visual baselines.** README.md "Visual gate": after an update-baselines run, copy the full linux
  baseline set from the artifact, never a single specimen (copying one left unrelated specimens one
  pixel off in a consumer). The overlay README names the `core-ascii` job in its ASCII section.

## 2026-10-22 (v0.76.0, core-ci retries the analyzer download and falls back to the CDN)

A downloaded tool in `core-ci.py` no longer fails a pull request on one bad answer from the host.

- Retry and fallback (fix): `fetch` retries a transient failure (HTTP 404, 408, 429, 500, 502, 503 or 504,
  a network error or a timeout) three attempts in all, waiting 5 and then 15 seconds, and says
  `attempt n of 3 failed: reason` for each. The PowerShell gallery API answers 404 once in a while for
  a package that exists, so `install-psscriptanalyzer` then falls back to
  `https://cdn.powershellgallery.com/packages/psscriptanalyzer.<version>.nupkg` (same three attempts)
  before it fails. `install-gitleaks` is the only other download in the script and gets the same retry
  with no fallback. Any other HTTP answer is final for that URL.
- The checksum check is unchanged and still runs on the bytes received. A mismatch (`ChecksumError`)
  fails at once, with no retry and no fallback.
- Tests in `tests/test_core_ci.py` (class `Fetch`, network faked): first try, 404 then success, API
  fails then the CDN succeeds, checksum mismatch on either URL fails at once, everything fails gives
  one clear error, a final HTTP error is not retried, and the install passes the CDN URL.

## 2026-10-22 (v0.75.0, list table and split layout, #117 D-017 and D-018)

Two owner-approved design items from the consumer report #117, shipped as kit parts. A page with a
list beside a detail pane can now build it from the kit.

- List table (#117 D-017): `ListTable` is a separate part from `Table`, chosen after reading it. `Table` is a
  column grid with sort, a sticky head and column cells, and its semantics are table semantics, so
  list rows (primary, secondary, leading and trailing slots), group header rows and an open row do
  not fit it without breaking what makes it a table. `ListTable` reuses its selection contract
  (`useRowSelection`) and its rule for controls inside a row. Rows are list items, groups are nested
  lists named by their header, the open row carries `aria-current`, a row checkbox selects without
  opening, and the header checkbox turns indeterminate over the rows on screen and skips rows that
  cannot be selected. Arrow keys, Home and End move between rows with one tab stop, Enter and Space
  open a row. `groupRows` is exported.
- Paging (#117 D-017): `Pagination` already takes `pageSizeOptions` and `onPageSizeChange` (v0.70.0).
  New `usePagination(total, size)` holds page and size, slices the rows,
  keeps the first row on screen when the size changes and pulls the page back when a filter shrinks
  the total.
- Split layout (#117 D-018): `SplitLayout` with a list pane and a detail pane. The list width is no
  longer fixed: a resize handle (a focusable separator with a value) moves with the arrow keys, 16
  pixels, Shift 64, Home, End, Enter to reset, or by dragging, reverses in a right to left layout and
  keeps the detail pane at 320 pixels or more. Under 720 pixels of layout width (measured on the
  layout, so a narrow column stacks too) the panes stack, list above detail, the handle goes away
  and the list is capped in height. `width` and `onWidthChange` make the width controlled.
  Exported `clampSplitWidth` and the `SPLIT_*` constants.
- New `.list-table`, `.list-row`, `.split` rules in `kit.css`, tokens only, light and dark through the
  tokens, with no motion to hold still under reduced motion.
- Gallery specimen `list-split` ("List table, paging and split layout") shows grouped rows, an open
  row beside checked rows, the pager with sizes and the split in both themes. Visual baselines for it
  are generated in CI.
- `standards/web-ui.md` section 7 has a "List and detail" entry that says why the list part is separate. `kit/README.md` lists
  the parts.
- Tests in `kit/tests/list-split.test.tsx` (slots, groups, open and checked rows, keyboard, the checkbox
  and button never opening a row, indeterminate header, page sizes, `usePagination`, the handle by
  keyboard and pointer, clamping, controlled width, right to left, stacking and unstacking, the
  stacked stylesheet rule, axe in both layouts).

## 2026-10-22 (v0.74.0, template palette preview and reorderable tiles, #117 D-024 and D-025)

Two owner-approved design items from the consumer report #117, shipped as kit parts.

- Palette preview and scoped shortcut (#117 D-024): `CommandPalette` takes a `preview(item)` slot that
  renders a read-only pane beside the list for the active row (`previewLabel` names the region, the
  pane is hidden at 640px and below, `undefined` is passed when nothing matches). A new `scope` prop
  makes a palette answer Cmd or Ctrl and K only while focus is inside a region marked with
  `paletteScope(name)`. The global palette stays shut inside a region a mounted palette owns, and
  closing still works from anywhere. The bare `/` key (v0.68.0) follows the same rule. New
  `openScopedPalette(name)` and `paletteOwnsKey` (the rule).
  `openCommandPalette()` is unchanged. A scoped palette lists its own entry in the shortcut help.
- Reorderable tiles (#117 D-025): `useTileReorder` reconciles a saved order with the tile catalog
  (removed ids dropped, new ids appended, duplicates collapsed), returns the draggable props for
  each tile, moves with Alt and an arrow key (Home and End go to the ends) and announces each move in
  a live region (`TileReorderStatus`). Hidden tiles keep their place and are skipped. The storage is a
  contract the host implements (`TileOrderStore`, one store per person), a late read never overwrites
  a move, and a failed read or write keeps the page working and says so. `createMemoryTileOrderStore`
  is the reference store. The pure helpers `reconcileOrder`, `moveInOrder` and `placeInOrder` are
  exported. The settling reasons are closed: tests and keyboard reorder.
- Gallery specimen `palette-tiles` ("Palette preview and reorderable tiles") shows a composer with a
  scoped template search and a grid of tiles in both themes. Visual baselines are generated in CI.
- `standards/web-ui.md` section 13 describes the preview pane and the scoped shortcut rule, and the
  home section describes reorderable tiles and their acceptance test. `kit/README.md` lists the parts.
- Tests in `kit/tests/palette-preview-tiles.test.tsx` (preview follows the arrows and the no match
  case, scope rule in both directions, by name and after unmount, reconcile, moves, hidden tiles,
  drag and drop, failed read and write, late read, reset, catalog growth, axe).

## 2026-10-22 (v0.73.0, record preview and an error boundary that resets, #117 D-022 and D-023)

Two owner-approved design items from the consumer report #117, shipped as kit parts. A module no
longer needs its own record preview or its own page crash panel.

- Record preview (#117 D-022): `RecordPreviewProvider`, `RecordChip`, `useRecordPreview` and
  `createRecordRegistry` in `overlays/RecordPreview.tsx`. The host registers a loader and a body per
  record type (with an optional title, full page link and icon) and the kit owns the rest: a labelled
  `Modal`, a skeleton while loading, an `ErrorState` with Retry when the loader rejects, a stale
  load never overwrites a newer one (the previous load is aborted), and every open loads again. A
  chip for an unregistered type, or outside a provider, is plain text. A body that throws is caught
  inside the dialog. "Open full page" goes through `navigate` when the host gives one, and the
  href passes `safeHref`. New `.record-chip`, `.record-preview-body` rules, tokens only, static under
  reduced motion.
- Error boundary that resets (#117 D-023): `ErrorBoundary` takes `resetKey` (Object.is, arrays
  element by element) and `variant` (`app` is the existing full screen crash, `page` is an inline
  panel with Try again and the stack in a closed disclosure). The crash clears in the same render the
  key changes in, a crash caused by the new key stays and reports once. `PageErrorBoundary` is the
  page variant with `resetKey` required, for hosts to key by the route. New `.page-crash` rules.
- Gallery specimens `record-preview` ("Record preview") and `page-crash` ("Page error boundary").
  Visual baselines for them are generated in CI.
- `standards/web-ui.md` section 7 gains "Record preview" and "Error boundary" (registry, mounting,
  keying by route). `kit/README.md` lists the parts.
- Tests in `kit/tests/record-preview.test.tsx` (registry, loading, error and Retry, Escape and focus
  restore, keyboard open, unregistered and provider-less chips, hook outside a provider, aborted and
  stale loads, full page link, unsafe href, throwing body, axe, reset key compare, reset on key
  change, no reset without a change, new key crash, host navigation, Try again, closed stack
  disclosure, array keys, app variant, axe).

## 2026-10-22 (v0.72.0, filter panel and bounded bulk runs, #117 D-019 and D-020)

Two owner-approved design items from the consumer report #117, shipped as kit parts. A page with
several filterable columns and an action over many selected rows can now build both from the kit.

- Filter panel (#117 D-019): `FilterPanel` is a form with one typed cell per column (text, number
  and date from and to, select, multiselect, boolean and a lookup with an async loader) and Apply
  and Clear. It emits a neutral list of `{ key, op, value }` clauses (`FilterClause`) and nothing
  shaped like a host's data. `buildFilters` and `draftFromFilters` are the pure halves, and `value`
  seeds the cells from the applied list. Every cell has a visible label, ranges and multiselects
  are labelled fieldsets, and the lookup is a small local combobox (role combobox, listbox,
  arrow keys, Enter, Escape, a polite status line, an abort signal, stale answers dropped) that
  moves onto the shared kit combobox when it lands. The cells wrap to one column on a narrow screen.
- Bulk run (#117 D-020): `useBulkRun(task, { concurrency, itemKey })` runs one task per item with a
  hard cap on tasks in flight (default 4), progress counts, a per-item error list and cancel (an
  `AbortSignal` for every task, no new task after it, aborted on unmount). A failed item never
  stops the others and a second run is refused while one is active. `SelectionBar` gets `run`,
  `onCancel`, `itemNoun` and `name` (the landmark name, so several bars can share a page): a named progress bar, Cancel while running, the errors afterwards and
  a locked Clear during the run. Without `run` the bar is unchanged.
- Settling reasons closed: tests (`kit/tests/filter-bulk.test.tsx`, 30 cases including a check that
  the cap is never exceeded at caps 1, 2, 3, 4, 5 and 50, and a mutation of the cap fails them), full aria
  labelling with an axe check on the panel, the open lookup and the bar in each state, and the
  neutral clause shape.
- Gallery specimen `filter-bulk` ("Filter panel and bulk run") shows the panel with its emitted list
  and the bar idle, running and finished with errors. Visual baselines for it are generated in CI.
- `standards/web-ui.md` section 7 gains "Filter panel and bulk runs". `kit/README.md` lists the parts.

## 2026-10-22 (v0.70.0, one async Combobox with a person row, and ListControls, #117 D-012 and D-013, #115 D-009)

Three owner-approved design items from consumer reports, shipped as two kit parts. The five typeahead
variants across the shell and three tool modules are replaced by one part, and the three ported
copies of the list controls by another.

- Typeahead chooser (`#117 D-012` and `#115 D-009`): new `Combobox` in `primitives/Combobox.tsx`, one
  part over an async `search(query, signal)` that the app owns, so no directory or data shape is in
  the kit. It takes the best of each variant: the debounce and minimum length, the stale reply guard
  (now also an abort signal), the loading, empty and retryable error states, outside press to close,
  the Escape that closes the list and never the dialog around it (a non-modal layer on the kit stack),
  the exclude list, the clear after a pick, and 44px rows on touch. Keyboard follows the ARIA
  combobox pattern (`aria-activedescendant`, arrows wrap, Enter picks, Tab leaves) and a polite live
  region announces searching, the count, none and failure. `renderOption` is the row slot.
- Person picker (`#115 D-009`): a usage of `Combobox`, not a second part. `PersonOption` is the row
  (an `Avatar`, name, detail line and muted meta) over the neutral shape `{ name, detail, meta, src }`
  that an app maps its directory entry to. The directory stays in the app.
- List controls (`#117 D-013`): new `ListControls` in `primitives/ListControls.tsx` (filters, sort
  with a direction button, group by, `rightSlot`), `GroupHeader`, and the helpers `applySort`,
  `applyGrouping`, `paginate` and `usePagedState`. Neutral data shape: options are `{ id, label }`
  and filters take `{ value, label }` options, sorting and grouping read values through a getters map.
  One look from the kit tokens replaces the three copies' different looks, native selects named by a
  visible label, a direction button named for its state, and a stacked layout below 640px.
  `Pagination` gains `pageSizeOptions`, `onPageSizeChange` (a "Rows per page" select) and `loading`,
  all optional, so existing callers render as before.
- Gallery specimen `lookup-and-lists` ("Combobox and list controls") shows the person picker with
  Avatar rows, a plain-row chooser, a failing lookup with its retry, the row slot at rest, and the
  list controls with grouping and paging, in both themes. Visual baselines for it are generated in CI.
- `standards/web-ui.md` section 7 documents the typeahead chooser and the list controls, and
  `kit/README.md` lists the parts.
- Tests in `kit/tests/combobox.test.tsx` (roles, debounce and minimum, stale abort and late reply,
  loading, empty, error and retry, `onSearchError`, keyboard, pointer, `clearOnSelect`, `excludeKeys`,
  the person row, outside press, the Escape test inside a Modal, axe) and
  `kit/tests/list-controls.test.tsx` (sort, grouping, paging, the state hook, the bar, group header,
  the page size select, axe).

## 2026-10-22 (v0.69.0, module CSS scope plugin and registry generator, #117 D-006 and D-007)

Two owner-approved items from the consumer report #117, shipped as build tooling for a multi-module
shell. A shell can now scope each module's stylesheet and generate its module list from manifests
with parts from the core instead of local copies.

- Per-module CSS scope (#117 D-006): `kit/scripts/scope-css.mjs` exports `scopeModuleCss`, a PostCSS
  plugin (a plain object, no new import for the app) that builds the listed module sheets inside
  `:where([data-module="<id>"])`. `:root`, `html`, `body` and `#root` map onto the module element,
  keyframes and font faces stay global, rules inside media, supports and layer at-rules are scoped,
  and a keyframes name without the `<id>-` prefix is a warning (an error with `strictKeyframes`).
  Scoping is idempotent and a bad id fails when the plugin is created. `scopeSelector` and
  `scopeOf` are exported for tooling. `standards/web-shell.md` section 5 gains the usage and an
  acceptance test.
- Registry generator (#117 D-007): `kit/scripts/build-registry.mjs` reads the module manifests
  (`--manifests` glob, ASCII JSON) and writes one deterministic TypeScript registry (`MODULES`,
  the `ICONS` map and `FALLBACK_ICON`). It validates ids, routes, accents and unknown keys, reports
  every problem at once, and `--check` fails when the committed file is stale. A module with no icon
  gets the fallback. `standards/web-shell.md` section 3 documents it with the acceptance test.
- Module descriptor type (#117 D-007): `kit/src/shell/module.d.ts`, exported from the kit root as
  types only: `ModuleManifest`, `RegistryEntry`, `GeneratedRegistry`, `ModuleDescriptor<TRoutes>`,
  `ModuleRailEntry`, `ModuleFeedSource` and `ConfigureHost`. A module that drifts from the contract
  fails the typecheck. Section 4 of the standard describes it.
- Both scripts sync into the app's `scripts/` folder with `gen-changelog.mjs` (`SYNC_FILES` in
  `corehash.py`) and `check-consumer-neutral.py` scans them as shipped content. `kit/README.md`
  lists the three parts. `postcss` is now a declared kit dev dependency for the scope tests.
- Tests in `kit/tests/scope-css.test.ts` (selector mapping, comma lists, at-rules, keyframes, font
  faces, strict mode, listed and unlisted sheets, and the output applied in a document to prove one
  module never matches another) and `kit/tests/build-registry.test.ts` (arguments, glob, every
  manifest rule, duplicates, deterministic output, fallback icon, the staleness check for an added,
  edited and removed manifest and a hand edit, exit codes, the command line and the descriptor
  type).

## 2026-10-22 (v0.68.0, tool switcher, account menu and the search key, #117 D-005, D-008 and D-009)

Three owner-approved shell chrome items from the consumer report #117, shipped as kit parts. A
multi-module shell can now build its tool switcher, its account menu and its search key from the
kit instead of local copies.

- Tool switcher carousel (#117 D-005): `ToolSwitchButton` (a compact `rail` form for the Rail
  `brandSlot` and a `prominent` form for a screen with no rail) opens `ToolLauncher`, a full window
  `Modal` carousel of plain `LauncherTool` data (id, name, tagline, description, hue, mark,
  `external`). The focused tool sits large in the centre, the others smaller and dimmed (a ring for
  three or more, side by side for two), with its details and an Open button below. Left, Right, Home,
  End, Enter, the arrow buttons, the dots, a swipe and a tile click drive it, `useToolLauncher`
  holds the open state, returns focus to the opening control and registers the `t` shortcut in the
  help dialog. It advances on its own (`autoAdvanceMs`, `idleMs`) and holds on hover, keyboard
  focus and interaction, with a Stop button. Every duration and curve is a motion token. Under
  reduced motion nothing moves on its own, there is no Stop button and no animation. Below 640px the
  far tiles drop out and the step shrinks. Pending reads show a quiet loading line, no tools shows an
  empty state, the current tool is marked and never opens itself, an external tool is badged. New
  `.tl-*` rules in `kit.css`, tokens only. New icons `IconGrid`, `IconExternal`, `IconArrowLeft`.
- Account menu (#117 D-008): `AccountMenu` for the Rail footer, with an `AccountIdentity`, extra
  `AccountFact` rows, `AccountLink` rows (new tab, `noopener`, `safeHref`), the Light, Dark and
  System `Segmented` choice and Sign out. A rejected `onSignOut` keeps the panel open with an inline
  alert. It renders nothing without a name or an email and takes no data from anywhere. New
  `.account-*` rules in `kit.css`, new icon `IconLogOut`.
- `/` opens search (#117 D-009): `CommandPalette` binds a bare `/` and lists it in the shortcut help.
  It does not fire inside an input, textarea, select or editable region, with Ctrl, Meta, Alt or
  Shift held, on a repeat, during composition, when another handler took the key, or over another
  dialog. `slashOpens={false}` turns it off and `isSlashOpen` is the pure rule. `isTypingTarget`
  now reads the `contenteditable` attribute as well as the computed value, so an editable region is
  found where the computed value is missing.
- Gallery specimen `shell-switcher` ("Tool switcher, account menu and search key") shows both
  switch buttons and the account menu. Visual baselines for it are generated in CI.
- `standards/web-shell.md` section 10 describes the switcher, the account menu and the search key
  with their acceptance tests, `standards/web-ui.md` section 13 states when `/` fires, and
  `kit/README.md` lists the parts.
- Tests in `kit/tests/shell-switcher.test.tsx` (the pure helpers, opening and focus return, the
  shortcut in and out of fields, keyboard and pointer movement, wrap around, details, opening by
  button, Enter and tile click, external and current tools, auto-advance with hold on hover, focus
  and interaction, Stop, reduced motion, swipe, empty and pending states, account identity, facts,
  theme change, links, sign out and its failure, Escape and outside press, the `/` rules for
  inputs, textareas, selects, editable regions, modifiers, repeats, composition, handled keys and
  open dialogs, and axe on every part).

## 2026-10-22 (v0.67.0, markdown reader and fact rows, #117 D-004 and D-014)

Two owner-approved design items from the consumer report #117, shipped as kit parts. A console can
now show a document and a detail panel from the kit instead of local copies.

- Markdown reader (#117 D-004): `Markdown` renders headings, paragraphs, bold, italic, code, fenced
  code, quotes, rules, nested bullet and numbered lists with task checkboxes (named Done or Open)
  and tables, with no dependency. It is safe by default: it builds React elements only, so raw
  HTML in the source shows as plain text and no image is rendered. A link is an anchor only for
  http, https, mailto and tel (new tab, `noopener noreferrer`). A relative document link calls
  `onLink` with the target (fragment removed) so the host opens it in place, and shows as plain
  text when the host gave no handler. Every other scheme (javascript, data, vbscript, file),
  control characters inside a scheme and protocol-relative URLs render as the label with no href.
  `classifyLink` is the exported pure rule. `headingOffset` (default 1) keeps the page heading the
  only h1. A code block and a table that scroll are keyboard reachable.
- Fact rows (#117 D-014): `FactRow` (label, value or children, `mono`, `tone`, `hint`,
  `labelWidth`) and `FactList` (`label`, `gap`) are a description list, so a screen reader hears
  each label with its value. An empty value shows a dash announced as None, zero is a real value.
  Below 480px the value wraps under its label and a long value wraps instead of being cut off.
- Disclosure (#117 D-014): a button with `aria-expanded` and `aria-controls` that opens a panel,
  uncontrolled with `defaultOpen` or controlled with `open` and `onOpenChange`, an optional
  `count` and a `dense` size. The panel stays in the document while closed, hidden. The chevron
  turn is static under reduced motion.
- New `.md-*`, `.fact-*` and `.disclosure-*` rules in `kit.css`, tokens only, light and dark.
- Gallery specimens `facts` and `markdown`. Visual baselines for them are generated in CI.
- `standards/web-ui.md` describes the three parts and the markdown safety rule. `kit/README.md`
  lists them.
- Tests in `kit/tests/markdown-facts.test.tsx` (raw HTML as text, seven unsafe link targets, external
  link attributes, relative links with and without a handler, `classifyLink`, literal code, every
  block, heading offset, description list pairing, empty versus zero, standalone row, keyboard
  toggle, controlled and default open, axe on each part).

## 2026-10-22 (v0.66.0, toggle chip group and standalone chart legend, #117 D-002 and D-003)

Two owner-approved design items from the consumer report #117, shipped as kit parts.

- Multi-select toggle chip group (#117 D-002): new `ChipGroup` primitive for filters where any number
  of options can be on (`Segmented` stays one of many). `value` is the list that is on and `onChange`
  receives the new list in the order of `options`. Each chip is a button with `aria-pressed` inside one
  named group, Tab reaches every enabled chip, Space and Enter toggle it, the arrow keys, Home and End
  move focus only and skip disabled chips. An option takes a status `tone` (a dot, and a tinted fill
  and border while pressed, from the status tokens, so a consumer's per-severity inks need no local
  CSS), a `badge` and `disabled`. Chips wrap on a narrow screen and a long label truncates. New `.chip-*`
  rules in `kit.css`, tokens only, with the hover transition static under reduced motion.
- Standalone chart legend (#117 D-003): `ChartLegend` is exported from the charts entry. Items are
  `{ label, color?, line? }` and a missing colour takes the next categorical hue in order, so two
  consumers' copies collapse into one part. It is a named list a screen reader reads (the legend inside
  the kit charts stays hidden because each chart has its own data table), with a decorative swatch,
  a line swatch for threshold series and wrapping on a narrow screen. `ChartLegendItem` and
  `ChartLegendProps` are exported as types.
- Tests: `kit/tests/chip-group-legend.test.tsx` covers the group name, pressed state, any number on,
  option order of the result, Space and Enter, Tab order, arrow and Home and End focus moves, disabled
  chips, tone and badge, unknown values, the legend list, default and given colours, empty items and
  axe for both parts. The gallery shows both (a Severity filter in the tabs specimen and a Legend card in
  the data charts specimen) and so is covered by the existing axe and visual gates in both themes.
  Documented in `standards/web-ui.md` and `kit/README.md`.

## 2026-10-22 (v0.65.0, font weight tokens and line numbers in the text diff, #117 D-010 D-011)

Two approved items on #117, built as one pull request.

- Font weight tokens (#117 D-010): `tokens/tokens.json` gains `--fw-medium` 500, `--fw-semibold` 600,
  `--fw-bold` 700 and `--fw-extrabold` 800, theme independent, regenerated into `tokens.css`,
  `tokens.ts`, `tailwind.preset.cjs` (`fontWeight`: `medium`, `semibold`, `bold`, `extrabold`) and
  both WPF dictionaries (`Weight.FwMedium` and the rest, as `FontWeight`). `tokens/build.py` emits
  the new `fontWeight` type. The kit stylesheets now set those four weights from the tokens. The
  values equal the numbers they replace, so nothing renders differently. The 650 step on titles and
  stat values stays literal. Docs: `standards/web-ui.md` section 4. Gallery: font weights in the
  Type roles specimen. Tests: `kit/tests/type-roles.test.ts`.
- Line numbers in `TextDiff` (#117 D-011): new `lineNumbers` option adds an old and a new line
  number gutter. The gutter is sized to the widest number so columns never shift, uses tabular
  figures, is hidden from assistive technology and is not selected on copy, so the `+` and `-`
  markers stay the accessible signal. Off by default. `diffLines` now returns `oldNumber` and
  `newNumber` on every line (null on the side a line is absent from). Docs: `kit/README.md`.
  Gallery: Text diff with line numbers. Tests: `kit/tests/promoted-parts.test.tsx`.

## 2026-10-22 (v0.64.0, gated ops center by pull request and an honest feed, #117 G-033 to G-037)

Owner decision on #117: an ops center whose source is a repo with its own CI gate stays in the
apply-at-once class, and each release lands as a pull request that merges as soon as that CI passes.
The five gaps from the account's step reports are fixed (renumbered G-033 to G-037 in the order
posted).

- Gated ops center (#117 decision): `hermes/ops_center.py` has a pull request path, selected by
  `"apply_via": "pr"` in the entry or detected (a remote whose default branch requires status checks,
  or the repo's own pre-push guard). It syncs in an isolated worktree of the remote's default branch,
  runs the local gate before and after, pushes `chore/core-<release>`, opens the pull request, waits
  for the repo's own checks on that head with `scripts/core-ci.py wait-checks` (bounded by
  `pr_timeout_min`, default 60) and merges at once with `scripts/merge-pr.py --match-head-commit`.
  It never waits for the owner and never writes the deploy checkout. A failure or timeout closes the
  pull request, deletes the branch and leaves the pin unchanged, reported once per kind. Documented
  in `CONSUMING.md` (`ops-center`, the keys table and the class table), `ci-cd-release.md` section
  11 (new item 3, rule `ci-cd-release.11` wording) and `local-ops-app.md` section 19.
- One report issue per run (#117 G-033): `hermes/report.py` creates the consumer-report issue at most
  once per nightly. The section that creates it records its number in a run dict the nightly passes
  to both sections, and the other reads that number directly instead of the lagging issue list.
- Overlay node_modules (#117 G-034): the ops-center gate also links `<clone>/<overlay>/node_modules`
  into the worktree when the overlay is a subfolder that has one.
- `core-status.py --ci` fallback (#117 G-035): with no run of a workflow on the default branch (a
  merge gate that merges with the workflow token never starts a push run), the run on the head of the
  most recently merged pull request whose tree equals the default branch's tree stands in.
- Feed CI results (#117 G-036): `hermes/consumption.py` runs `core-status.py --json --ci`, so the
  feed no longer shows CI rules failing while CI is green. A CI rule whose result is unread counts as
  `unverified`, never `fail`, with the reason in `not_collected`.
- Approved items on closed reports (#117 G-037): `account.approved_unopened` reads every
  consumer-report issue of the account, open or closed, most recent first, so an item approved on a
  closed issue still appears.
- Closing keywords: new `checks/check-closing-refs.py` (a `checks.yml` step) fails a pull request
  whose title, body or commit message puts a closing keyword in front of a reference to a
  `consumer-report` issue, so a core merge can no longer close an account's report.
  `CONTRIBUTING.md` says to write `Refs #N` instead.
- Tests: the pull request path (merge, failed checks, refused merge, detection), the overlay
  node_modules link, exactly one issue created in a run with no open issue, the `--ci` fallback on
  fixtures, the feed's `--ci` run and unverified counts, approvals on a closed issue, and the closing
  keyword check.

## 2026-10-21 (v0.63.0, hub home blocks and pin the current page, D-015 and D-026)

Two owner-approved design items from the consumer report #117, shipped as kit parts. A multi-module
shell can now build its hub from the kit instead of a local copy.

- Hub home blocks (#117 D-015): `HubHome` lays keyed blocks out in three zones (strip, main pair,
  side) with container queries and no gap for a hidden or empty block. `FeedBlock` (skeleton while
  loading, one quiet line per unreadable source, empty state), `ActionsBlock`, `PinnedBlock` (pins
  with unpin, then recents, a recent that is pinned is not repeated), `ToolChip`, `HomeItemRow` and
  `HubLink` (a real anchor that opens through the shell on a plain click, href through `safeHref`).
  Blocks take plain data through props and never markup. `addRecent` and `sanitizeRecents` are the
  pure helpers for the host's recents list. New `.home-*` rules in `kit.css`, tokens only, with the
  hover transition static under reduced motion.
- Pin the current page (#117 D-026): `PinButton` for every module header, the `PinsStore` contract a
  host implements (snapshot, subscribe, pin, unpin, denied state, optional load), `pageAt` (the
  longest declared route, so a detail route never pins), `usePins` and `createMemoryPinsStore` (the
  reference store). The control is absent until the store has answered and when the read is denied,
  disabled with a reason at the maximum, and reports success or failure in a toast. The pinned block
  reads the same store, so the two always agree. New `IconPinOff`.
- Gallery specimen `hub-home` ("Hub home and pinned pages") shows the header control, a denied
  control and the three-zone hub in both themes. Visual baselines for it are generated in CI.
- `standards/web-shell.md` section 9 describes the hub parts, the store contract and the acceptance
  tests. `kit/README.md` lists the parts.
- Tests in `kit/tests/hub-home.test.tsx` (pin and unpin, absent when denied, full store, failed
  write, store and block in step, blocks in every state, zones and tiles, recents, `pageAt`, axe).

## 2026-10-21 (v0.62.0, type-role tokens, #117 D-016)

Approved item D-016 on #117, live report #134: the type steps a console sets by role, which the
kit lacked.

- New type tokens in `tokens/tokens.json` (theme independent, regenerated into `tokens.css`,
  `tokens.ts`, `tailwind.preset.cjs` and the WPF dictionaries): `--fs-title` 24px, `--fs-stat` 18px,
  `--fs-subtitle` 15px, `--fs-caption` 11px, `--fs-mono` 12px, `--fs-mono-caption` 11px,
  `--lh-display` 1.04, `--lh-title` 1.15, `--lh-stat` 1.1, `--lh-subtitle` 1.3, `--lh-label` 1.35,
  `--lh-caption` 1.4, `--track-stat` -0.018em, `--track-subtitle` -0.010em, `--track-label`
  0.004em, `--track-caption` 0.008em and `--track-eyebrow` 0.10em.
- Kit: the monospace captions (`.release-group-meta`, the text diff legend and body, the key cap,
  the flow node meta) now use `--fs-mono-caption`, and the two monospace body rules use `--fs-mono`.
  The values equal the sizes they replace, so nothing renders differently.
- Docs: `standards/web-ui.md` section 4 lists the type roles. Gallery: new Type roles specimen.
  Tests: `kit/tests/type-roles.test.ts`.

## 2026-10-21 (v0.61.0, page redaction script for screenshots)

- Page redaction script (#117 P-007): new `checks/redact_page.js`, one self-contained expression
  evaluated in the page right before a screenshot. It swaps the body for a static clone so a live
  re-render cannot paint real text back, replaces letters with `x` and digits with `0` in text, input
  values, placeholders and `title`, `aria-label` and `alt`, blurs images, canvases, iframes, large
  icons and every text-bearing element, and returns `count` (text nodes still holding a real letter
  or digit, must be 0), `leftover` and `cssGenerated` (rules drawing text with `attr()` or
  `counter()`, checked by eye). The `core-consumer-report` skill's screenshot step now loads it and
  refuses a capture while `count` is above 0. Covered by `kit/tests/redact-page.test.ts` and a page
  fixture, including a timer that re-renders text after the redaction.


## 2026-10-21 (v0.60.0, gauge and ring charts)

Approved consumer report item, as two generic kit chart parts.

- Gauge and RingProgress (#117 D-021, live report #134): `kit-core/charts` gets `Gauge` (a half ring)
  and `RingProgress` (a full ring with a label and sub label). Both are hand-drawn SVG with no chart
  library, the wrapper is `role="meter"` named by `label` with `aria-valuenow`, `aria-valuemin`,
  `aria-valuemax` and an `aria-valuetext` that adds the state word, and the drawing is hidden from
  assistive technology. `value` is clamped to 0 through `max` (a non-finite value or a `max` of 0 or
  less draws an empty chart). The tone comes from `thresholds` (`warning` and `danger` values, a
  higher value is worse unless `higherIsBetter`) or a fixed `tone`, and maps to the `--success`,
  `--warning` and `--danger` tokens, else `--accent`. The arc travels on `--dur-travel` and does not
  animate under reduced motion. The pure helpers `clampValue`, `fraction`, `thresholdTone` and
  `meterText` are exported too. Gallery specimens in Data charts, tests in
  `kit/tests/meter-charts.test.tsx`, and a short rule in the UI standard section 8.

## 2026-10-21 (v0.59.0, consumption classes, the ops center as approval desk, the shared consumption feed, G-031 and G-032)

The owner's principle for how a core release reaches an app, stated as a rule, with the data an ops
center needs to act as the owner's approval desk. Plus the two core fixes approved on #117.

- Two consumption classes (README "Direction", CONSUMING.md section 3, `ci-cd-release.md` section 11,
  rule `ci-cd-release.11`). Apply-at-once: an ops center (and the agent home) takes every release at
  once, nightly, behind its own gate, with rollback, as before. Approval-gated: every other app
  (product repos, hubs, multi-module shells, vendored copies) never changes without the owner's
  approval; each release arrives as a pull request and kit adoption happens through planned pull
  requests the owner approves. Nothing is applied to such an app directly. CONSUMING.md has the
  table of who does what per class.
- `core-update.yml`: new default `CORE_UPDATE_MERGE=approve`. The sync pull request opens as a draft,
  so no merge gate that merges green pull requests picks it up, and waits for the owner (approval:
  mark it ready). `wait` and `gate` stay, as the owner's standing approval for one repo. Copy the
  workflow file again.
- `hermes/nightly.py`: an open sync pull request is reported as awaiting owner approval with its CI
  state; only failing checks on it are a problem (it was a problem after a day).
- Core consumption panel (`standards/local-ops-app.md` section 19, rule `local-ops-app.19`): what an
  ops center shows per registered consumer and for the account, the approvals (one action each,
  only through the pull request or issue-comment path), the never-apply rule for approval-gated
  apps, and the acceptance tests.
- Shared feed: new `hermes/consumption.py`, run by the nightly as step 6 (`apply.consumption`, on by
  default), writes `~/.config/build-standards-core/consumption.json` atomically, format
  `build-standards-consumption/1` (schema in section 19.2): per consumer class, pin, latest, behind,
  sync pull request and CI, core-status counts, UI verdict, adoption suggestions with risk; this
  account's items awaiting a decision and approved items with no core pull request; and a `peers`
  block from every open `consumer-report` issue, with other accounts' shipped D items as
  suggestions, the new ones marked. Read-only on every remote. New entry key `sync_head` names a
  vendoring tool's pull request branch prefix. Tests in `tests/test_consumption.py`, fixtures only.
- `hermes/setup.py` prints each registered repo's class: an `ops-center` repo applies at once, any
  other mode is approval-gated.
- #117 G-031: a `vendored` repo registered report only now gets its machine record each night (the
  record only reads the clones and writes on this machine), and the report sections scan its clone
  at the root against the core clone's kit, so it appears in `nightly:candidates` and
  `nightly:changes`; the changes section lists a change of the release its copy carries.
- #117 G-032: `check-sanitised.py` and `check-consumer-neutral.py` in file mode now accept the
  account login in a raw gist link to a moved `.md` table
  (`gist.githubusercontent.com/<login>/<id>/raw/<file>.md`), the same allowance as screenshots; the
  report skill and CONTRIBUTING.md name that link form. Any other file type in that URL still fails.

## 2026-10-21 (v0.58.0, approved consumer report items: rewrite recovery, vendored release, push guards, changelog and lint sweep, report skill)

Owner-approved items from the consumer reports #115 and #117 that live in the core's own docs,
scripts and skills. Design items and the page redaction script are built by the accounts that hold
their source, not here.

- History rewritten (#115 G-001): `hermes/nightly.py` detects a core clone with no merge base with
  `origin/main`. A clean clone is reset (`fetch --tags --force`, `reset --hard origin/main`, the old
  tip kept as branch `core-before-rewrite-<sha>`) with one log line; a clone with local edits is left
  alone and the run fails with the one-line recovery command. The normal pull now fetches tags with
  `--force`. `check-core-sync.py --remote` checks out the pinned commit when it exists and the tag
  otherwise (new `corehash.checkout_pinned`), so the lock is compared by tag and content hash.
  CONSUMING.md section 6 has a "History rewritten" entry.
- Report skill (#115 G-002, G-003, G-004; #117 G-026 to G-030): the core clone is the `core` key of
  `consumer.json`; a count the pinned `core-status.py` lacks comes from the core clone's copy run
  against the overlay, or reads `not collected: key added after the pin`; ways are written by neutral
  label (workflow, apply-at-once, vendored, agent-home); the screenshot scrub freezes the page as a
  static clone, replaces letters and digits, removes CSS-generated text (`attr()`, `counter()`) and
  counts what is left; a v1 report's `D<n>` gaps carry over as `G-nnn`; the body stays under 65,536
  characters, with whole tables moved to a gist file. The issue template and CONTRIBUTING.md say the
  same, and that the checks see only the file passed to them, so a comment is checked the same way.
- Screenshot hosting (#117 G-027, decided): `check-sanitised.py --file` and
  `check-consumer-neutral.py --file` accept the account login inside a raw gist image URL
  (`gist.githubusercontent.com/<login>/<id>/raw/<file>.png`), the posting account's own public
  login, and still check everything else. Shipped files never get the allowance.
- Push guards (#115 G-005): `hermes/setup.py --ui OWNER/REPO=ops-center:PATH` looks for a pre-push
  hook, branch protection or an active ruleset on the default branch and prints which mode fits; the
  nightly's failure line names a refusing pre-push hook and the two fixes. CONSUMING.md section 3.
- Vendored release (#117 G-025): the vendored record holds the release the copy carries, from the
  vendoring tool's pin file (`pin` on the entry) or the recorded source hash matched against each
  release in the core clone (new `nightly.source_hash_at`), never the newest release; it records
  `latest` and `behind`. `core-status.py --vendored` prints `behind` and exits 3; `--latest` reads
  the newest release through gh. A record with neither source is reported, not guessed.
- Report-only registration (#117 G-024): CONSUMING.md section 5 explains how a machine whose repos
  take the core through its own local job joins the report; `setup.py --report-only` writes
  `"apply": false` on the entry and the nightly skips its apply.
- Per-PR changelog (#115 P-001): new `core-ci.py changelog-entries` (a second step of the
  `changelog` job in `core-ci.yml`; copy the workflow again), on with the parameters row
  `Changelog entries` = `per-pr`: exactly one new entry per pull request in the fixed heading,
  newest first, every older entry byte for byte; a pull request that touches only the sync's overlay
  paths is exempt; an unknown base fails in CI. New should rule docs-and-changelog.md 1.9. The
  core's own `checks/check-changelog.py` now fails closed in CI on an unknown base or diff and
  still skips with a line on a local run.
- Lint sweep (#115 P-002): new template `lint-sweep.yml`, weekly and on demand, runs the overlay
  lints and the repo's `Lint sweep command` over the whole tree and keeps one `lint-sweep` issue:
  opened once, then updated, never a second, closed on green. SHA-pinned, `CORE_CI_RUNNER` as in the
  other templates. New should rule ci-cd-release.md 2.1; `core-status.py --ci` reads its run when
  it is installed.
- Required checks by repo shape (#117 e.2 #3): ci-cd-release.md section 2 opens with a table for a
  single hub app, a monorepo with IaC, a docs-only repo and a local ops center, built on the
  `core-ci.yml` job names; the hub's full list follows it.
- Bounded own-PR merge lane (#117 e.2 #5, owner decision 2026-10-21): automation-safety.md section
  8 and rule 1.10, and pr-review-and-merge.md section 5: a standing lane may bypass the approval
  count on the owner's own pull requests only, never a red check, a freeze, a hold label or an
  escalation, only while its switch is on, and it logs each bypass. New rule automation-safety.8.
- Trust holds (#117 P-001): pr-review-and-merge.md section 4 adds three hold kinds (first PR of a new
  app, an author's first N merged PRs, device-shipped paths) and "a failed lookup holds". New rule
  pr-review-and-merge.4 and two parameters rows.
- Handled decisions (#117 P-002): automation-safety.md rule 1.6 adds that a handled item aliases a
  regenerated one unless there is new source evidence dated after the decision, that model prose is
  never evidence, and the acceptance test.

## 2026-10-20 (v0.57.0, sync merges after CI, required checks, kit peers, ASCII in every file)

- `core-update.yml` never uses `gh pr merge --auto` again: on a repo with no required status checks
  GitHub merged the sync pull request at once, before CI (consumer report, #115). The job now waits
  for every check on the pull request's head commit (`core-ci.py wait-checks`: every core-ci job
  present, all complete and green on two reads in a row, `CORE_UPDATE_WAIT_MINUTES`, default 60) and
  squash merges that commit with `merge-pr.py --match-head-commit`; a failure or the timeout leaves
  the pull request open. `CORE_UPDATE_MERGE=gate` leaves the merge to the repo's own merge gate.
  The workflow file changed: copy it again.
- `hermes/setup.py --ui OWNER/REPO` refuses a `workflow` repo whose default branch requires no
  status checks (branch protection, an active ruleset, or a `REQUIRED_CHECKS` list in a workflow, read
  through gh). `--allow-no-required-checks` registers it anyway with a warning.
- New `core-ci.py required-checks`: which core-ci jobs the merge gate does not require; `--fix`
  prints, never runs, the command that adds them. `core-status.py --ci` (or `--required-json FILE`)
  lists missing jobs as a problem when `core-ci.yml` is installed.
- New `core-ci.py kit-peers` and the `kit-peers` job in `core-ci.yml` (copy the workflow again): no
  file the kit root reaches imports an optional peer, every tsconfig that includes the whole kit copy
  excludes each optional entry whose peer the app does not declare, and with `tsc` installed the copy
  typechecks with those peers blocked (#115). The core's `kit.yml` runs `npm run typecheck:nopeers`
  and `checks.yml` runs `kit-peers` over `kit/src`.
- ASCII in every file: new rule pr-review-and-merge.md 1.19. The `ascii` job reads every tracked text
  file by default (binaries, lockfiles, synced copies and `targets.map` destinations skipped); the
  ASCII patterns parameter still narrows it and says so. Existing non-ASCII files take a time-boxed
  exception per path, never a script or XAML file. `checks/check-ascii.py` uses the same selection.

## 2026-10-20 (v0.56.0, consumer report v2: data-driven report, report skill, nightly changes section)

- The `consumer-report` issue template and the CONTRIBUTING.md outline are rewritten as a
  data-driven report: a. machine and ways in (role-labelled `consumer.json`, nightly jobs, way,
  pin, `core-status --json` counts and UI verdict per repo), b. design inventory per app (tokens,
  shell, every part with its source, interaction, typography and density, light and dark,
  layout-only screenshots in both themes), c. a part-by-part design diff against the kit at the
  pinned release, d. functionality inventory and an adoption risk table, e. practice and CI,
  f. gaps in the core's instructions, g. changes since the last report. Proposal items carry stable
  account-scoped ids (`D-nnn`, `P-nnn`, `G-nnn`) so the owner approves or rejects each one; each
  item states ready or settling, evidence, and what changes in the core. Data that could not be
  collected is written as "not collected" with the reason.
- New shared Hermes skill `core-consumer-report`: the step-by-step procedure to collect that data
  from real state, sanitise it, run `check-sanitised.py --file` and `check-consumer-neutral.py
  --file`, and update the account's single report issue in place, keeping the nightly marker
  sections. Registered in `hermes/README.md` section 2; the nightly's skill sync installs it.
- CONSUMING.md section 7 and the template give the one-line command:
  `hermes chat -Q -s core-consumer-report -q "Produce and file this account's consumer report now, following the core-consumer-report skill."`,
  and the fallback for an agent without Hermes.
- `hermes/report.py` keeps a second marked section `nightly:changes` current: per registered UI
  repo (hashed label), local parts added, removed or with a changed signature, lint counts for
  local tokens, accents and kit-class restyles, core-status count deltas and new local parts that
  match a kit role. State lives in `~/.config/build-standards-core/`; the issue is edited only when
  the section changes, and the sanitiser holds it on a hit. Tests: `tests/test_nightly_changes.py`.
- CONTRIBUTING.md "Sanitising evidence" uses the checks' `--file` mode on the draft.
- Fix: the nightly candidates section was recomputed per repo, so with several UI repos only the
  last repo's candidates survived. `report.update` now takes every registered UI repo, computes
  candidates in one pass, groups them per repo under the same hashed label as the changes section,
  and edits the issue at most once per nightly. Test with two repos in `tests/test_nightly_report.py`.
- The skill's screenshot upload is the tested path: a secret gist made from a text file, PNGs pushed
  into it with git, each raw URL checked.

## 2026-10-20 (v0.55.2, overlay CI fits a private monorepo)

- `core-ci.py python-config` ignores ruff configs inside the synced copies (the core's own lint
  fixtures in `lint-core/` are not the consumer's config).
- The content hash skips tool caches (`.ruff_cache`, `__pycache__`, `.pytest_cache`, `.mypy_cache`), so
  running ruff or Python over a synced copy no longer reads as drift.
- `core-drift.yml` and `core-update.yml` take the same `CORE_CI_RUNNER` variable as `core-ci.yml`,
  so a repo with no hosted minutes runs them on its own runner.
- The core's `visual.yml` pins its test image by digest, and CI lints every core workflow.

## 2026-10-20 (v0.55.1, python-config reads every ruff config in a monorepo)

- `core-ci.py python-config` checks every tracked ruff config at any depth (`ruff.toml`, `.ruff.toml`,
  or a `pyproject.toml` with `[tool.ruff]`), each against the Python floor. It read the repo root
  only, so a monorepo with one config per app always failed. Test added.

## 2026-10-20 (v0.55.0, template CI workflow, proof records, merge-pr from any worktree)

- New template workflow `templates/overlay/.github/workflows/core-ci.yml`, copied with the overlay
  like `core-drift.yml`, and its checks in `templates/overlay/scripts/core-ci.py` (standard library,
  refreshed by every sync): `secret-scan` (gitleaks 8.30.1 pinned by sha256, the base commit's
  config, ignore files and allow comments off), `workflow-lint`, `ascii`, `pr-title`, `commitlint`,
  `attribution` (with an optional hashed private term guard), `identity`, `changelog`, `python`
  (floor interpreter, committed ruff config, hash-pinned ruff 0.16.10, the test command),
  `powershell` (parser and `PSUseCompatibleSyntax` with PSScriptAnalyzer 1.25.0 pinned by sha256)
  and `node-pin`. Every action is pinned by full commit sha with a version comment; the existing
  template workflows and core `checks.yml` are pinned the same way. New parameters rows for the
  values the jobs read.
- `rules.json`: 11 rules retagged from `review` back to `overlay-ci`, each naming the workflow and
  its jobs (`check.workflow`, `check.jobs`) with an acceptance line naming them:
  secrets-and-credentials 1.8, pr-review-and-merge 1.2 and 1.4, docs-and-changelog 1.3,
  ci-cd-release 1 and 3, scripting-python 1.1 and 1.10, scripting-powershell 1.7,
  wpf-design-system 6.1, wpf-powershell-gui 6. `check-rules.py` fails an `overlay-ci` rule whose
  workflow or job does not exist in the template. The docs' acceptance lines match.
- `core-status.py`: an `overlay-ci` rule fails when its workflow or job is not installed, and
  passes or fails from the job's result with `--ci` (latest default-branch run) or `--ci-results
  FILE`. New consumer-owned `standards-local/proofs.json` records how a rule is proved (ci job,
  test file or dated review); a valid record reports the rule `proved`, counted apart from `pass`,
  and an unknown rule, weaker kind, missing file or job, or stale review is a problem. A missing
  `Stacks` row in `parameters.md` is now a problem and fails `--require-lint-config`, which
  otherwise checked nothing.
- `merge-pr.py`: no longer passes `--delete-branch` to `gh pr merge`, whose local step failed from a
  worktree whose base branch is checked out elsewhere or from a detached HEAD after the merge had
  landed, and was then reported as a refusal. The remote branch is deleted through the API and the
  local branch only when no worktree holds it; a non-zero gh exit on a merged PR is never reported
  as refused.
- Tests in `tests/test_core_ci.py`, including a planted secret the scan must catch despite an ignore
  file, an allow comment and a permissive config in the same PR. Core CI installs the pinned scanner
  for it and lints the template workflows.
- The core's own `kit.yml`, `visual.yml` and `gallery-release.yml` pin every action by full commit SHA.

## 2026-10-20 (v0.54.0, token-efficiency standard for an agent home)

- New `hermes/token-efficiency.md`: where an agent home's model spend goes and the setting for each
  part (cache lifetime per session source, compression and pruning, shell output and terse voice,
  delegation pinning and turn ceiling, budgets for scheduled jobs and sub-agents). Source: the
  agent-home token audit of 2026-10-13 (30 days of per-call usage). Values the audit did not
  measure (prune threshold, turn ceiling, per-job budgets, tool savings) are not invented: each
  has the measurement that sets it.
- `hermes/configurations.md` section 11, `hermes/README.md`, `README.md` and `CONSUMING.md` point at it.

## 2026-10-20 (v0.53.0, consumer report audit: every open item closed or marked)

Every item in consumer reports #115 and #117 was checked against v0.52.0; the checklist is in #118.
This release closes every item that was partly or not done and is not settling.

- Shared denylist: `checks/denylist.txt` named the terms it protects. It is now
  `checks/denylist.sha256` (sha256 per term); `check-sanitised.py` hashes every span of one to four
  words and reports a hit by place, never by term, and `--hash TERM` prints the line to add.
  `ci-cd-release.md` section 2 states the private term guard rule.
- Owner decisions on three settling items: the pre-run gate library stays a documented pattern
  (`hermes/configurations.md` 16); count floors and change caps are registered as a `should` rule
  (`automation-safety.7`); `ButtonLink` is documented in the kit README.
- `rules.json`: 33 new entries for rules added in v0.50.0, v0.52.0 and here (web-shell 1 to 10,
  web-api-runtime 1.7, 3.3, 5.7 and 7, web-ui 12 and 26, notifications 9, local-ops-app 17 and 18,
  data-safety-sqlite 7.1 to 7.4, iac-governance 7, pr-review-and-merge 3, secrets 2, web-build 4,
  7, 8.1 and 10); five section entries extended for the rules added to them.
- `web-api-runtime.md`: group lookups limited to referenced groups, batched (20 ids, 4 in flight),
  400 and 429 handling and a generation guard (1.7); no CORS at the hosting platform (3.3); export
  retry at 2, 5 and 10 seconds with a 2,000-span buffer (5.7).
- `web-shell.md`: platform sign-in as its own column in the client-runtime table (no browser
  token, sections 1, 2 and 5.2 do not apply); no silent sign-in frame in a module; the shared
  descriptor type and host hook; font faces, root selectors and portals under the module scope;
  new section 10 (one `AppShell` per module, rail `brandSlot`, mount, route, adding a module).
- `web-build.md`: `ToolManifest` gains `visibleTo`, `hiddenWithPermission` and `hue`, `NavLink`
  gains `previewFlag`, with the helpers and a test; the `TOOLS` array and `ICON_MAP` rule are for a
  single app; search indexes file text with a highlighted passage and reports index health.
- `rbac.md`: preview ceiling and stored-role drift. `iac-governance.md`: vendor secrets as tagged
  placeholders; the lock rule points pipeline deletes at the destroy workflow.
- `ci-cd-release.md`: merges use the declared method, a quiet period with one merge per pass,
  branch deploys that never hold the deploy token, ringed device releases.
  `pr-review-and-merge.md`: the review bot as a fail-closed required check; the triage marker
  parser ships as the overlay's `scripts/triage_marker.py` with a self-test.
- Kit: `kitThemeInit()` (a Vite HTML transform) and `hasCurrentThemeInit()` in the new
  `theme-init` entry deliver the theme script without pasting; `web-ui.md` section 12 and the kit
  README say so. The kit README documents `iconBadge` and `brandSlot`.
- Overlay: `core-status.py --require-lint-config` fails a declared stack with no lint config, and
  `core-drift.yml` runs it. `core-status.py` reports a local component named like a kit export in a
  file that never imports the kit as a stand-in, so the UI stays partial. The overlay README names
  `standards-local/` as the only consumer-owned folder and says where a consumer's own scripts go.
- `hermes/setup.py`: `--claude`, `--no-claude`, `--safe-restart` and `--no-safe-restart`; it
  removes the wrapper scripts of retired core jobs it wrote. `CONSUMING.md` lists each config key
  with the release that added it and points the scope rule at the CONTRIBUTING test, as does the
  generated `core-practices` skill. `claude/README.md` says what "required" means in the opt-in step.
- Safe restart: a chat turn in flight (a live, unexpired turn lease) counts as busy, and an
  unreadable model slot or cron run list counts as busy, with tests.
- `check-hermes-skills.py` fails a hand-written shared skill that carries a date or a ticket id.
- `hermes/configurations.md`: signal-only script jobs, the weekly dependency-major review, memory
  and context jobs, and the plugin-directory route for a runtime that cannot see entry points.
- `lint/README.md`: UI009 and UI010 in the table; the ratchet is not for a UI consumer.
  `kit/MIGRATION.md`: optional kit entries excluded from the typecheck, and the path for an app the
  core was taken from. README vendoring: word-boundary deny terms, optional entries left out whole.
- `local-ops-app.md`: the stack rows name the kit as the only UI and chart library; the first
  sign-in never takes focus. `secrets-and-credentials.md`: a row for a local job calling a
  user-delegated API.
- `wpf-powershell-gui.md`: the three remaining empty `catch` blocks report their error.
  `wpf-design-system.md`: no nav active bar in the fixed dimensions.
- `CHANGELOG.md`: every older heading carries the release that shipped it, the missing v0.31.0
  heading is restored, the v0.48.0 to v0.52.0 headings carry their release date in version order,
  and an issue link is a bare number.

## 2026-10-20 (v0.52.0, new patterns and kit fixes from consumer reports)

- Kit: a critical banner carries `role="alert"` (critical only). A numeric table header aligns
  right (`.table th.cell-num`). `NavItem` takes `iconBadge` (a count or `'dot'`, defaults to a
  numeric `badge`) shown on the icon while the rail is collapsed. `Rail` takes `brandSlot` for a
  tool switcher. New `ButtonLink` renders an anchor through `safeHref`. The accent names ship as
  data in `accents.json` (export `./accents.json`).
- Tokens: `tokens/layers.css` declares `@layer base, core;`.
- Standards: new `standards/web-shell.md` (multi-module shell), web-build 8.1 one local gate and
  section 12, email renderer and CI guard (notifications 9), count floors and change caps
  (automation-safety 7), hash-checked plans and split deletes (iac-governance 7), bearer rules and
  dev identity (web-api-runtime 7), heartbeat watch and runner-lost alert (local-ops-app 17 and
  18), pre-run gate library (hermes/configurations 16).

## 2026-10-20 (v0.51.0, PowerShell, WPF and logging fixes)

- One logger: `wpf-powershell-gui.md` section 8 and the scaffold no longer carry their own
  `Write-CMTraceLog`; both point at `cmtrace-logging.md` section 2. The old copy defaulted the
  component to the script path and lacked the null-path guard, ASCII scrub and rotation. The log
  path snippet creates the folder with .NET and sets `$script:LogComponent`.
- `Write-Warning` and stdout: `Write-CMTraceLog` skips its failure warning when
  `$script:LogQuiet` is `$true`. `cmtrace-logging.md` section 7 states the `powershell.exe -File`
  rule and the test (stdout is exactly `True` or `False`, with a valid and an unwritable log path).
- Trial switch naming: `TrialRun` is canonical; `WhatIf`, `Trial`, `TrialMode` and `TestMode` stay
  accepted aliases. The CI row in `cmtrace-logging.md` lists `TrialRun`. `standards/rules.json`
  `scripting-powershell.1.2` and the generated `core-practices` skill say the same. No lint under
  `lint/` checks these names.
- `wpf-powershell-gui.md`: "four make the difference" is now "three" (items 9 to 11). The NuGet
  bootstrap example captures its error instead of an empty catch. The owner-account capture prompt
  uses a named constant instead of a literal account id. The reference path is no longer broken by
  a mechanical name replacement, and the section 12 heading reads as a heading.
- `wpf-design-system.md`: the sidebar avatar uses neutral initials. The tracked-label example no
  longer sets `Margin` on a `Run` (invalid); it uses an `InlineUIContainer`. The TextBox template
  takes `Padding` on the border, as section 3 of the GUI doc says. The TabItem template draws a
  hairline pill instead of an accent bottom border, matching the no-edge-bar rule.

## 2026-10-20 (v0.50.1, generated core-practices skill keeps the rule level)

- `hermes/build_skills.py` writes the `level` of each rule (`must` or `should`) into a new Level
  column. It dropped it, so a `should` rule read as mandatory in the generated skill. The skill
  intro now says what each level means. `--self-test` proves the level survives, and CI runs it.

## 2026-10-20 (v0.50.0, web, API, auth, data and CI standards fixes)

- `rbac.md`: audit and server-side View-As are `[target]` (phase 3, in review), no longer `[enforced]`. Rule 1.3 now says every route is covered by at least one guard and may stack a blanket guard with a specific one. `hasPermission` is `checkPermission`. The `accessPrefixes` field is declared in `ToolManifest` (`web-build.md`). The old standard name is a link. App-role claims are not an evaluator input.
- `web-build.md`: the dev bypass is development or test only, with a boot preflight.
- `web-api-runtime.md`: writes include every POST not on a read-shaped allowlist, the origin guard returns 403 from whichever layer refuses, no stock access logger, the shared package carries security helpers, new rules 6.3 (full bearer validation) and 6.4 (dev identity).
- `web-client-runtime.md`: scope covers polling apps, either MSAL cache policy qualifies, new rules 1.3 (validated return target) and 1.4 (account change clears state).
- `pr-review-and-merge.md` and `ci-cd-release.md`: the merge commit rule and the `identity` check no longer conflict (merge commit noreply, branch commits may use the organisation address), garbled text fixed, core sync PRs are exempt from the changelog entry rule.
- `secrets-and-credentials.md`: named 0600 token cache exception and the long-lived token (classic PAT) risk path.
- `docs-and-changelog.md`: 1.3 is a review rule, `check-changelog.py` is not proof of it.
- `identity-and-people-data.md` has numbered sections. `rules.json` gains entries for it and `notifications.md` and the new rules above.
- `rules.json`: the 31 rules tagged `overlay-ci` that have no template workflow are retagged `review`. No new template workflow ships because actions must be pinned by SHA and none is vetted.
- `hermes/configurations.md` and `hermes/tools.json`: usage ledger retention.
- `web-ui.md`: rule 9 covers the hub as home in a multi-tool shell, the accent in a multi-tool shell and the kit's exported accent list, a Home button row in section 25, vendored-consumer adoption proof, theme script injected from the kit, new section 26 (several apps on one origin, `appId`).
- `local-ops-app.md`: one deny-by-default gate for Host, Origin, headers and body cap, with a route-table test.
- `pr-review-and-merge.md`: declared merge method and merge queue, one branch pattern parameter, one triage marker pattern shared by lane and planner, changelog entry timing when the docs home is elsewhere.
- `ci-cd-release.md`, `secrets-and-credentials.md`, `web-build.md`: free-plan assumption and paid-plan exception, monorepo version exception, deploy health on three polls from a newer process, named-operator approval fallback, auth model per app type, one Node pin across workspaces.
- `data-safety-sqlite.md`: new section 7 (server databases, backups and restore drills, migration screen, audit chain).
- `hermes/configurations.md`: skill date and ticket count, idle proof covers every runtime for safe restart.
- `iac-governance.md`, `scripting-python.md`, `scripting-powershell.md`: leftover `overlay-ci` acceptance labels retagged `review`.
- Not changed here: the generated `core-practices` skill still drops `level` (fix is in `hermes/build_skills.py`, owned by another PR).
- Note on history: older headings without a version (for example `2026-10-12 (single token source)`) and the missing v0.31.0 heading are left as they are. v0.31.0 was never published as a heading; v0.30.0 is followed by v0.32.0.

## 2026-10-20 (v0.49.0, nightly: modes, config v2, ops-center apply-at-once, vendored record, upward report)

- Nightly UI modes: `workflow`, `ops-center` and `vendored`. `local` stays as an alias of `ops-center`.
- Config version 2. A version 1 `consumer.json` is migrated in place with `consumer.json.v1.bak` beside it.
  `apply.claude` and `apply.safe_restart` default off; the claude step is skipped quietly when the CLI is
  absent. `apply_setup.py --safe-restart` installs the safe restart job only on request.
- `hermes/ops_center.py`: apply at once behind a local gate. The gate runs on the current pin first, in an
  isolated worktree of the committed default branch; the sync lands only when it passes before and after,
  and rolls back otherwise. A failure on the current pin is reported as the consumer's.
- `vendored` mode keeps `{release, source_hash}` on the operator machine; `core-status.py --vendored` reads it.
- `core-status.py`: a declared stack whose lint has no config is a failure, not a silent skip.
- `check-exceptions.py` flags a baseline file whose `EXC-` ids are not in the exceptions table.
- `hermes/report.py`: one `consumer-report` issue per account, one machine-owned section, edited only when
  it changed, sanitised first, never a pull request.
- `check-sanitised.py` and `check-consumer-neutral.py` gain `--file`; the neutral check matches whole words.
- New `checks/check-kit-comments.py`; kit comments no longer name a doc file.
- `tests/` with unit tests, run in CI.

## 2026-10-20 (v0.48.0, the core states what it is for: one direction, four ways in, one way up)

- **README gains a `Direction` section**: the core is the mandatory baseline for UI design, web
  frontend and backend practice, proven CI workflows, and agent runtime practice. It names the
  four ways to take the core (`workflow`, `ops-center`, `vendored`, `agent-home`), the
  baseline-first rule (sync and adapt through call-site-keeping adapters before any swap),
  core-owned vs consumer-owned paths, and the rule that the core names no build: a build
  contributes designs by role, never by name. "Consuming the core", "What an overlay may and
  may not do" and "Contributing back" now match it. (#118, #115, #117)
- **CONSUMING.md rewritten as the agent's runbook**: setup per way, a table of every step the
  nightly applies with what it changes and its opt-out key, `consumer.json` v2 with every key
  and default, and the upward path. The nightly never installs `caveman-compress`: one truth
  with `hermes/configurations.md` 11.3. (#115, #117)
- **CONTRIBUTING.md gains "Reporting from a consumer"**, and the new issue template
  `.github/ISSUE_TEMPLATE/consumer-report.md` carries its outline: one report issue per
  account, labels `consumer-report` and `settling`, the owner approves items and the owning
  account opens the pull request. The scope test resolves "contribute it back" against
  "machine-specific stays local": parameterise it or keep it local. Evidence rules:
  layout-only screenshots, measured numbers as ratios and deltas. A repo the core was first
  taken from feeds later changes as any other consumer does, pull request by pull request.
  Core changelog issue references are bare numbers, never owner-qualified URLs. (#115, #117)
- `kit/MIGRATION.md` gains step 0, baseline-first: sync first, adapters that keep call sites
  where they are, and a monorepo's shared UI package as the baseline plus additions;
  `standards/web-ui.md` 0.11 counts adapters over kit parts as adoption and local parts
  duplicating a kit role as not. (#115, #117)
- `standards/local-ops-app.md` gains the overlay row and the deploy rule: the app consumes
  the core in the `ops-center` way, kit from `kit-core/`, tokens from `tokens-core/`, local
  additions in `src/`, and the build runs against the synced copies. (#117)

## 2026-10-19 (v0.47.4, Hermes config guidance: reasoning key, fallback proof, board retirement)

- `hermes/configurations.md` names `agent.reasoning_overrides`, the key Hermes reads, instead of
  `prompt_caching.reasoning_overrides`.
- New section 15: prove the fallback with a stub-model run, the built-in `default` board cannot be
  removed, and the order for retiring a board.

## 2026-10-19 (v0.47.3, overlay keeps the core source on upgrade)

- `corehash.core_repo()` records a legacy `repo=` lock value as `core_repo` in the machine-local
  `consumer.json` the first time it falls back to it. The sync rewrites the lock without that line,
  so an overlay set up before `hermes/setup.py` recorded `core_repo` failed its sync handover and
  every later run with "Cannot tell where the core lives". A config it cannot parse or write is left
  alone and reported.

## 2026-10-19 (v0.47.2, nightly calls the Claude Code step quietly)

- `hermes/nightly.py` runs `apply_claude.py --quiet`. Without it, a clean run printed "claude setup
  matches the core decisions", which the nightly counts as a problem, so a consumer with nothing to
  change failed the job with exit 1.

## 2026-10-19 (v0.47.1, caveman-compress checks its tools only when a file is due)

- `apply_claude.py` decides which registered memory files are due (new or changed and at least
  `min_bytes`) before it looks for the caveman-compress skill, Python 3.10+ and the `claude` CLI. A
  consumer whose memory file is under the threshold no longer fails the nightly sync on tools it
  does not need. A due file with the tools missing still reports MISSING and names the file.

## 2026-10-18 (v0.47.0, kit wave 2: app library parts promoted)

- Three optional kit entries, each on an optional peer dependency so the kit root keeps zero
  runtime dependencies: `kit-core/charts` (recharts), `kit-core/graph` (`@xyflow/react`, with
  `graph.css`) and `kit-core/api-reference` (Scalar, with `api-reference.css`, themed by the kit
  tokens, following the kit theme, no fonts and no telemetry).
- Root parts: `FormSection`, `ErrorState`, `SelectionBar`, `ListFooter`, the media query hooks, a
  removable `Badge`, `ProgressBar meter`, `Skeleton variant="list"`, `data-tip-side` placement and a
  `selection` prop on `Table`.
- `CardHead` gains `variant` (`card`, `panel`, `label`), `count` and `level` instead of a second
  section head part. `kit/MIGRATION.md` maps the old app part names onto the kit parts.
- Vendor sheets load into `core.vendor`, nested in `core`, so the core sheets keep one layer block.
- Gallery specimens for every new part. Visual baselines for the new specimens come from the visual
  workflow dispatch. The gallery page state sizes to its content, so the wayfinding baseline no
  longer grows with the gallery length.

## 2026-10-18 (v0.46.0, Claude Code secrets rule)

- `claude/tools.json` gains the `mcp-secrets` rule (a literal token in the user config is reported) and
  the advisory `claude-ai-connectors` rule. `apply_claude.py` checks the first nightly.

## 2026-10-18 (v0.45.0, Claude Code setup standard)

- New `claude/` registry and `apply_claude.py`, run by the nightly sync: rtk hook, context-mode,
  codebase-memory-mcp as the single code-graph standard at user scope, token-savior rejected, and
  caveman-compress mandatory for the user-level memory file. No per-session or per-repo commands.
- `hermes/configurations.md` section 11.3 points at it.

## 2026-10-18 (v0.44.0, safe restart in the nightly sync)

- The nightly sync now installs and refreshes the safe restart job on macOS: both scripts, the
  launchd agent and the job, created paused. Consumers stay in lockstep with no manual install.

## 2026-10-18 (v0.43.0, safe Hermes restart)

- New `hermes/safe-restart/` and `hermes/configurations.md` section 14: a self-disabling restart job
  that waits for idle work, restarts Hermes once from outside the gateway, verifies it and reports.

## 2026-10-18 (v0.42.0, local model guidance for Hermes)

- New `hermes/configurations.md` section 13 and shared skill `core-local-model`: set the real
  per-slot window, cap cron, kanban and gateway concurrency to the slot count (kanban has no default
  cap), treat long timeouts as a capacity signal, and route every failure to a human.

## 2026-10-18 (v0.41.0, parts promoted from a consumer library, and the kit as a workspace package)

- Kit: new `Breadcrumb` and `Pagination`, `Mono`, `RelativeTime`, `CopyButton` (announces the copy),
  `formatRelative` and `freshness`, `Forbidden` and `NotFound` page states, `SearchInput` (with an
  optional focus hotkey), `ProgressBar` (determinate or indeterminate), `TextDiff` with `diffLines`,
  `ImpersonationBanner`, the crash-screen `ErrorBoundary`, and the `IconShield` and `IconCopy` icons.
  They were generic parts of a consumer's own library; app branding and heavy-dependency parts stay
  in the app.
- The overlay sync writes `kit-core/package.json` (from `kit/consumer/package.json`), so a monorepo
  adds the synced kit to its workspace and imports `kit-core` with no path alias. The content hash
  skips `node_modules`, `dist` and `.tsbuildinfo` inside a synced copy, so installing is never drift.
- kit/README.md: the workspace route, and how an app's own component library becomes a layer on the
  kit instead of being deleted. MIGRATION.md points to it.

## 2026-10-17 (v0.40.1, an excepted UI adoption passes the drift check)

- `core-status.py` reports `ui: excepted` instead of `partial` while an active, named exception covers
  web-ui.md 0.11, so `--require-ui-adopted` passes during a dated migration. The exception still expires
  and CI fails once its review date passes.

## 2026-10-17 (v0.40.0, the UI is adopted whole or not at all)

- New rule web-ui.md 0.11: a UI consumer uses the shell, tokens and kit as shipped. Syncing the overlay
  is not adoption. Lint rule UI010 flags any app stylesheet that redefines a core token, a baseline in
  `ui-lint.json` is refused, and `core-status.py` reports `ui: adopted` or `partial`
  (`--require-ui-adopted` fails the drift workflow). `kit/MIGRATION.md` gives the order.
- Kit: new `Alert` (inline status message), `Select size="sm"`, a keyboard-operable clickable `Card`
  (`interactive` with `onClick`), the `--text-on-accent` token, and the app font and ink on `body` so
  portaled parts match.
- Fixes the gaps a consumer raised in #101.

## 2026-10-17 (v0.39.1, known history is allowlisted in check-authors)

- `checks/check-authors.py` skips the commits already in `main` whose author email is not a noreply
  address (squash merges before `merge-pr.py` existed), listed by full hash. Rewriting `main` was
  rejected: it would break every clone and tag. New commits are still checked.

## 2026-10-17 (v0.39.0, merges never write a personal or work email into history)

- New rule `pr-review-and-merge.md 1.18` (registered, check core-ci): a squash or merge commit carries only a
  noreply author email. GitHub builds the squash commit with the opener's primary account email even when
  every branch commit is noreply, which put a work address into this repo's main. The rule asks for three
  layers: the account keeps its email private, clones set a noreply `user.email`, and merges go through the new
  overlay script `scripts/merge-pr.py`, which squash merges with `--author-email <id>+<login>@users.noreply...`,
  reads the merge commit back and exits 1 on any other address. Section 5 and the checklist carry the flag.
- `merge-pr.py` ships to every overlay on the next sync (it is in the refreshed overlay scripts).
- CONTRIBUTING.md tells contributors to merge that way.

## 2026-10-17 (v0.38.0, an overlay never names the core's owner)

- **The overlay `standards.lock` no longer carries a `repo=` line.** The source is resolved on the machine
  that runs the scripts: `CORE_REPO` in the environment (CI sets it from a repository variable, which
  `core-update.yml` now reads), then `core_repo` in the machine-local `consumer.json`, which
  `hermes/setup.py` writes from the core clone's own remote and `nightly.py` passes to the overlay scripts.
  A sync rewrites an old lock without the line. `scripts/check-core-sync.py` (the offline drift check every
  overlay runs) now fails if a lock names a repo, so the leak cannot come back. `core-status.py` no longer
  prints or reports the repo. Existing overlays pick all of this up on their next sync.
- New `checks/check-consumer-neutral.py` (in CI) fails when anything that ships to a consumer (standards,
  tokens, lint, kit source, the overlay template, the Hermes skills) names the owner login or core repo slug
  read from the clone's origin remote or a private denylist.
- `checks/check-authors.py` skips merge commits. GitHub builds a pull request's merge commit with the
  opener's account email, so a contributor with a work primary email failed the check on a branch whose own
  commits were all noreply. The branch commits are still checked.
- `hermes/tools.json` records `quota` as adopt (optional) and `homeassistant` as reject (not approved for any
  consumer), so the nightly audit stops reporting both as undecided. `hermes/configurations.md` section 4
  says consumers keep unapproved plugins disabled.

## 2026-10-17 (v0.37.2, setup keeps a renamed core-nightly job)

- `hermes/setup.py` finds its cron job by the wrapper script, not the name, so a consumer can rename
  `core-nightly` to its own naming rule (configurations.md section 2) without a rerun creating a second
  job. New `--name` and `--deliver` options. A rerun no longer resets the delivery target to `origin`
  unless `--deliver` is given.
- `CONSUMING.md` step 3 documents the two options.

## 2026-10-17 (v0.37.1, managed hosts consume the core through a deploy key)

- Secrets and Credentials rule 4 and the identity table now cover a managed host that reads a
  private repo, not only CI: one read-only deploy key per host, private half backed up in the
  secret store. This is the same process CI consumers already use.
- `hermes/README.md` section 3 adds "Managed hosts (converged from git)": pin a release in the
  host's repo, sync skills from the convergence script over the host's deploy key, and do not run
  `setup.py` or the nightly job on a host whose setup is applied from git.

## 2026-10-17 (v0.37.0, What's new can link to the full changelog)

- Kit: `BuildCard` and `ReleaseNotesDialog` take an optional `link` ({ href, label }) shown in the
  dialog foot, for the full changelog in the docs home. Only http and https links render
  (`safeReleaseLink`). `ReleaseNote.date` is optional, so notes summarised by an API render without a
  date. A release can carry its own `link`, for a dialog that lists releases from several tools, and
  `BuildCard` takes a `seenKey` so the New pill returns when the notes change without a version
  change.
- `web-ui.md` section 22: notes that must follow the user's permissions are served by the app's API
  behind the tool's own permission, never shipped in the bundle.

## 2026-10-17 (v0.36.4, the standard covers only what it lists)

- The nightly job no longer reports enabled plugins that `tools.json` has no decision on, and no
  longer tells agents to contribute one. That prompt led a consumer agent to write its own
  smart-home plugin into the shared standard. Machine-specific plugins are out of scope;
  `CONSUMING.md` and `hermes/README.md` now say so.

## 2026-10-17 (v0.36.3, an agent can consume the core from nothing)

- `CONSUMING.md` now states the operator's one-sentence instruction, how to clone to a permanent
  path, what to do when the UI repos are unknown (run without `--ui`, report, rerun later) and how to
  recover a clone whose pull is blocked by generated files. `README.md` carries the clone command.
- `hermes/setup.py` refuses a clone under `/tmp`, `/var/folders` or the Hermes scratch folder, which
  macOS clears and which would silently break the nightly job.

## 2026-10-17 (v0.36.2, agents find the consumer steps on their own)

- New `AGENTS.md` at the root, which Hermes loads automatically when a session opens in the repo. It
  sends an agent on a machine without the `core-nightly` job to `CONSUMING.md`, and contributors to
  `CONTRIBUTING.md`.
- `caveman-compress` stays optional and manual (owner decision): the nightly job never installs it.

## 2026-10-17 (v0.36.1, keep the core clone clean)

- v0.36.0 committed a compiled `hermes/__pycache__` file. Running the nightly job rewrote it, which
  left the consumer's clone dirty and could block the fast-forward pull. Removed it, added a
  `.gitignore` for bytecode, and `nightly.py` no longer writes bytecode.

## 2026-10-17 (v0.36.0, consumers apply the standard themselves)

- New `CONSUMING.md`, linked from the top of `README.md`: the steps an agent follows the first time
  it reads this repo. They set up the nightly job and verify it.
- New `hermes/setup.py`: one-time, idempotent consumer setup. Writes the consumer file, the cron
  wrapper and the Hermes cron job `core-nightly`, removes the superseded `core-skills-sync` job, and
  runs the job once.
- New `hermes/nightly.py`, the nightly job: pull with retries and self-handover, core skills sync,
  Hermes setup, then UI consumers moved to the newest release through their core-update workflow
  (or a local clone), with a pull request open over a day reported.
- New `hermes/apply_setup.py` replaces `audit_setup.py`: installs the rtk binary and plugin and the
  caveman skill from `tools.json` (version 2: install commands per tool, plus settings) instead of
  only reporting. `nightly_sync.sh` is now a shim onto `nightly.py`, so existing consumers move over.
- `caveman-compress` changes from adopted to adapted and optional: the Hermes skills security scan
  blocks it (verdict dangerous), so the job does not install it. `configurations.md` 1.5, section 11.3.
- A tag push now publishes its GitHub release (`gallery-release.yml`). v0.34.3 and v0.35.0 were tags
  without releases, so UI consumers, which move only to published releases, never received them.

## 2026-10-17 (v0.35.0, Hermes token economy and the contribution model)

- `hermes/configurations.md` 1.4. New section 11, token economy: decisions for rtk (adapted),
  caveman (adapted) and caveman-compress (adopted), each with install and enable, scope across
  interactive, cron agent jobs and sub-agents, a never-rewrite list, recovery of dropped output and
  how to measure the saving. New section 12, context, memory and output size (compression trigger,
  tail protection, proactive pruning, memory caps, prompt caching), with the open items.
- New `hermes/tools.json` decision registry, `hermes/audit_setup.py` and
  `checks/check-hermes-tools.py` (in CI). The audit reports MISSING required tools and UNDECIDED
  plugins. `hermes/nightly_sync.sh` runs it and exits 4 on a difference; `CORE_APPLY=1` lets it run a
  missing plugin's own install command. The script now also works from a git worktree.
- New shared skill `core-token-economy`, installed by the existing nightly skills sync.
- `ingest/hermes-token-economy-gap.md`: why the category was missed (ingest per source, lessons only,
  no return signal, self-referential audit) and the process fixes, plus the sibling review.
- `CONTRIBUTING.md`, `README.md` and `hermes/README.md`: the repo owner is the final say and every
  consumer account is that same owner, so any consumer account opens and merges its own pull request
  once `ci` and `visual` pass. Category survey added to the ingest rule.

## 2026-10-17 (v0.34.3, rebase rule)

- `CONTRIBUTING.md`: rebase on the current `origin/main` before pushing and before merging, never
  take a whole side of a conflict or write from a stale copy, so a later change cannot clobber an
  earlier one.

## 2026-10-17 (v0.34.2, Hermes scheduled job hygiene)

- `hermes/configurations.md` 1.3, section 2. Three new entries: gates hash material input apart
  from ambient context, the failure watcher covers every enabled job by default with a reasoned
  opt-out list, and a nightly script job removes finished one-shot jobs and prunes dead job ids from
  the registries.

## 2026-10-16 (v0.34.1, art mark and surface hardening)

- Art mark input. `hue` and `hot` must match a plain token name (`/^[a-z][a-z0-9-]*$/`), anything
  else falls back to the default hue. A `src` holding a quote, parenthesis, backslash or control
  character (line breaks included) still renders as a plain image but stays out of the CSS mask
  variable, and the sheen and slide layers are hidden for that mark. `size` is clamped to 1 to
  1024 (non-finite gives 28), `intensity` to 0 to 3 (non-finite gives 1), and non-finite anchor
  numbers are skipped. New exports `isArtHue` and `isArtSrcSafe`.
- Art mark layout. A feed window with a width or height of 0 no longer divides by zero, the feed
  anchors are skipped.
- Art mark motion. Pausing now stops every animated layer, pseudo-elements included (the sheen and
  the bar), and wins over the recipe rules. The beacon picture animation only runs inside a live
  host or on host hover and focus, like the other recipes.
- Art mark pause hook. A tab that is already hidden at mount pauses at once, and an
  IntersectionObserver batch uses the latest entry instead of any entry.
- Page header. The tinted block is opt-in again: `PageHeader wash`, or `data-wash` on a hand-written
  `.page-header`. A plain `.page-header` keeps the pre-0.34.0 look. A consumer that took the wash
  from 0.34.0 adds `wash` (or the attribute) to keep it.
- Shell canvas. The wash is a fixed pseudo-element layer behind the content, not
  `background-attachment: fixed`, and the shell is an isolated stacking context.
- Tokens. `--danger-hover` in dark moves from `#f2757c` to `#ff9fa4` so hover is distinguishable
  from `--danger`, still certified on every surface. The solid danger button hover is `--danger-700`
  instead of a brightness filter. Every accent block was checked to define `--accent-rgb` and a test
  now keeps it so.
- Kit CSS. The page and card title tracking uses `--track-display` and `--track-title` instead of
  raw em values.
- Docs. `kit/README.md` states that a consumer copying `kit/src/` keeps `fonts/` (the woff2 files
  and the licence) next to `styles/kit.css`.

## 2026-10-16 (v0.34.0, surfaces, art mark, bundled fonts)

- Tokens. The surface ladder is re-cut as a blue-dark luminance ladder at one hue (canvas, then
  five steps, with `--surface-inset` moving the other way) and the light set mirrors it. Card over
  canvas is 1.135 in dark and 1.231 in light, and the borders step up so `--border-default` and
  `--border-strong` read on every surface. The four text inks are re-fitted and the elevation
  steps gain a hairline ring and a top light. Danger and urgent inks and the danger border are
  re-fitted so status text keeps 4.5:1 on every surface including hover and pressed. New tokens:
  `--card-sheen`, `--header-wash`, `--canvas-wash`. Certification: the quaternary ink is now gated
  at 4.5:1 on the canvas, the card and the raised panel (set `ground`), up from the disabled-only
  rule. Consumers that pin an old surface hex in a test or a screenshot update it.
- Kit CSS. The shell root paints `--canvas-wash`, the page header becomes a tinted block with a
  full hairline ring, the card face takes `--card-sheen`, card and page titles move to weights 650
  and 700, card head icons take the accent ink, and a generic `.hue-chip` (hue dot on a hue tint,
  text stays primary ink) is added.
- Kit. `ArtMark` (a picture with a glow and a layered effect on top, `ART_EFFECTS`, `artAnchorVars`,
  `useArtPaused`) with seven recipes: `beacon`, `glint`, `signal`, `ring`, `scan`, and the new
  generic `lightning` and `fire`. Durations come from `--dur-pulse`, colours from kit hue tokens,
  nothing animates except transform, opacity and filter, and it is static under reduced motion.
  Effects only run inside an element with `data-art-host`. Gallery specimens `surfaces` and
  `art-mark` (neutral sample picture) and tests with axe.
- Fonts. Geist and Geist Mono ship as variable woff2 files in `kit/src/fonts/` with `@font-face`
  (weights 100 to 900, `font-display: swap`) in `kit.css`, so the first face in the type tokens
  renders without a network fetch. The licence (SIL Open Font License 1.1) is in the same folder.
  `standards/web-ui.md` section 4 now says fonts ship with the kit when tokens name them. An app
  that loaded these faces from a third-party host drops that link.

## 2026-10-16 (v0.33.5, changelog guard)

- CI. `check-changelog.py` fails a pull request that changes shipped content while leaving
  `CHANGELOG.md` untouched. The rule was prose in CONTRIBUTING.md and PR 78 broke it with CI
  green, so the release history went incomplete silently. `CONTRIBUTING.md` now also states the
  release step: tag the merge commit after each shipped change.

## 2026-10-16 (v0.33.4, shared nightly sync)

- Tooling. `hermes/nightly_sync.sh` makes the updater itself a shared artifact: it pulls this
  repo, runs `hermes/sync_skills.py`, and reports only when something changed or failed, so
  every consuming Hermes instance can run the same nightly schedule entry instead of a
  hand-rolled per-instance script. The consuming section of `hermes/README.md` names it as the
  standard schedule entry with a cron example.

## 2026-10-16 (v0.33.3, plan-limit failover)

- Documentation only. hermes/configurations.md section 3 gains two entries. A plan-limit 429
  (reset more than 30 seconds away) rotates the credential pool at once and no rate-limit wait
  exceeds 30 seconds. Before this, a seat plan hitting its usage window parked every turn for
  10 minutes before failover, because the agent retries the same credential first and honours
  Retry-After up to 600 seconds. Adding a pool account can clear the provider's suppression list
  and re-seed removed credentials, so the pool is re-checked after every add.

## 2026-10-16 (v0.33.2, README restoration and clobber guards)

- The README was restored in full. A pull request on 2026-10-14 had replaced its body with a
  placeholder line, silently dropping every section from "What lives here" to the FAQ; the two
  sections that pull request added (Hermes sharing rules, consumer vendoring exclusions) are kept
  and folded into their proper places.
- New check `check-placeholders.py`: markdown may not carry placeholder prose standing in for
  removed content. It runs in CI after the ASCII check.
- `check-authors.py` now also fails a commit whose `Co-authored-by` trailer names an assistant or
  tool, enforcing the standing "no attribution" rule mechanically.

## 2026-10-16 (v0.33.1, consumer vendoring notes)

- Documentation only. The overlay README gained a section on keeping vendored copies intact:
  consumers must exclude the vendored directories and `targets.map` destinations from formatters
  and secret scanners, or pre-commit fixers break the drift hash and gitleaks trips on WPF
  `Key="..."` attributes. Found while syncing a consumer to v0.33.0.

## 2026-10-15 (v0.33.0, step through the presenter)

- web-ui.md section 20: the presenter gains previous and next controls next to the dots. Items keep
  rotating on their own. Previous, next and a dot jump straight to an item and restart the rotation
  timer, so an operator can step through faster without the next tick cutting the chosen item short.
  Before this, the dots were the only way to move, they are hidden on narrow screens, and a dot
  click left the old timer running.
- Kit: `FeedStrip` renders the two step buttons (ghost, icon only, `Previous item` and `Next item`)
  when it holds more than one item, wrapping at both ends. New icon `IconChevronLeft`. Unit tests
  cover stepping, wrapping, the timer restart and the single-item case.
- New optional behaviour on an existing component, a minor bump while the core is below 1.0.

## 2026-10-15 (v0.32.0, content stays inside its box)

- web-ui.md 0.10 (new): text never escapes, or is cut off by, the control, chip or card that holds
  it, at any supported width. Controls size with `min-height`, a single-line control holds one line
  (or truncates with an ellipsis and a tooltip), a title with a description is an option card and
  not a button, and no element borrows a kit control class and restyles its box inline. A console
  had reused `className="btn"` on its own card-style option buttons as a hover hook. Once the kit
  arrived, the kit button recipe (fixed 34px height, `nowrap`, `line-height: 1`, centring) applied
  under the inline styles, and every two-line option rendered centred with its description hanging
  out of the bottom.
- Kit: `.btn`, `.hub-btn`, `.badge` and `.tab` size with `min-height` instead of a fixed `height`,
  so taller content grows the control instead of spilling out. Single-line controls render exactly
  as before.
- UI lint UI009 (new): flags an element that carries a kit control class (`btn`, `hub-btn`,
  `badge`, `tab`, `seg-btn`, `input`, `select`, `kbd`) and restyles its box in an inline style.
  Containers such as `.card` size to content and are not flagged. Fixtures cover the template
  literal, braced string and plain string forms and the false-positive cases.
- `kit/visual/overflow.ts` (new): the in-page detector for text that escapes the nearest painted
  box or is clipped without an ellipsis. The visual gate runs it over the gallery in both themes
  at full width and at 720 pixels. `kit/scripts/overflow-probe.mjs` (new) runs the same detector
  over any app's routes through an already running browser's DevTools endpoint and exits 1 on a
  finding. web-ui.md section 9 adds it to the verification gate.
- New rule and lint check, a minor bump while the core is below 1.0.

## 2026-10-14 (v0.31.0, shareable Hermes skills and plugins)

- `standards/hermes.md` (new): which Hermes content is shared through the core (skills named
  `core-*`, plugin source and non-secret configuration) and what always stays local (MCP and
  gateway configuration, boards, secrets, anything naming an instance).
- An example shared skill and its overlay copy show the shape. The heading for this release was
  missing until v0.53.0 restored it.

## 2026-10-14 (v0.30.0, idempotent doc publishing and routing as data)

- docs-and-changelog.md 1.8 (new): the publisher that writes approved pages to the docs home runs
  single-flight under a lock, records each page as it publishes, refuses a create whose title already
  exists and checks the created title came back unchanged. Section 4 adds a duplicate title gap to
  the coverage audit. A scheduled and a manual publisher run had published the same approved set
  twice, so the docs home carried "(2)" copies that readers found instead of the record.
- local-ops-app.md 16 (new): what reaches the action queue is routing data. Collectors emit one
  candidate shape, ordered data rules route candidates and analyzer items, a person who addressed
  the operator directly is considered when no rule names them, every must-consider candidate ends as
  an item or a recorded drop reason, and a route-elsewhere click writes the rule. Our analyzer prompt
  had grown a dated rule per missed input and still missed the next one.
- Two new rules, a minor bump while the core is below 1.0.

## 2026-10-14 (v0.29.0, web API and client runtime practice)

- New `standards/web-api-runtime.md` with 20 rules: per-user group cache (short TTL, single-flight,
  bounded LRU, failures never cached, writes read groups live), the directory token cached and
  dropped on a 401, Access-Control-Max-Age 7200 with an origin guard, Server-Timing for listed
  origins and one personal-data-free log line per request, telemetry named from declared route
  templates only, keyless ingestion, per-API caps, flush on SIGTERM, the lightweight exporter, and
  one shared runtime package with no runtime dependencies.
- New `standards/web-client-runtime.md` with 23 rules: one auth boot that routes the return target
  in-app, renewal by refresh token only where framing is denied, interaction required only for real
  session expiry, loop guard before redirect, single-flight redirect, errors matched by name and
  code, the API client (bearer only to the API base, GET dedupe, stale-while-revalidate, identity
  reads persisted as stale, invalidate drops in-flight GETs, polls that never navigate and pause
  while hidden), lazy routes with idle prefetch and vendor chunks, one shared client package and
  token cache per origin, and the live feed strip from one endpoint.
- README: both docs in the standards table, vendoring for a consumer that carries no record of the
  core, and the per-app rollout practice (package first, one pull request per app, every route in
  both themes, `appId` on a shared origin).
- hermes/configurations.md 1.1: parallel workers on one repo, shell portability on macOS, and
  proving work before reporting it.
- Rules registry: 43 new rules (223 in total), `core-practices` regenerated.

## 2026-10-14 (v0.28.0, triage markers name the findings they answer)

- pr-review-and-merge.md 1.8: the triage marker names the finding ids it answers and the merge lane
  clears only those. A reply that answered one high finding had cleared every high on the head, so a
  real finding merged. Stricter rule, a minor bump while the core is below 1.0.

## 2026-10-14 (v0.27.2, visible light hover and modal keys)

- Tokens: in light mode `--surface-2` to `--surface-5` step a little deeper (`#f4f6fa`, `#e4e9f1`,
  `#d9dfea`, `#ccd4e2`). `--surface-3` had landed on the canvas value, so a ghost button or chip
  hover on the canvas (header, toolbars) was invisible. Hover now clears the canvas at 1.077 and a
  white card at 1.219. Cards, canvas, inset and dark are unchanged, every certification passes.
- Kit: `Modal` skips its own keys (Cmd or Ctrl and Enter submit) only when the caller's
  `onKeyDown` prevents the event, never because a child (an editor, a combobox) already did.
- Tests for both. The visual gate passes on the existing baselines (the step change sits inside
  its colour threshold).

## 2026-10-14 (v0.27.1, review fixes for the console gap release)

- Kit: `CategoricalHue` and `isCategoricalHue` keep their meaning (the six series hues), so
  existing consumer types and guards are unchanged. The wider set is the new `MarkHue` and
  `isMarkHue`, which every `hue` prop (Badge, Pill, Tone, HueTile, Card, StatTile, Stat, Modal,
  dialogs, EmptyState, Avatar, nav icons) now takes. `SeriesHue` and `isSeriesHue` stay as aliases.
- Kit: `Modal` keeps a caller `aria-labelledby` (it wins over the generated name) and merges a
  caller `aria-describedby` with the subtitle. `size="full"` uses the dynamic viewport height.
- Kit: toasts keep caller ids and generated ids apart internally, so a generated `toast-N` can
  never replace or dismiss a caller toast that happens to use the same id.
- Kit: `RadioGroup` relies on the native fieldset and legend for its name (no explicit role).
  `Radio` ignores `defaultChecked` inside a group. `Switch` keeps a caller `aria-labelledby` and a
  disabled switch never submits its hidden input. `Checkbox` draws the dash and the check from the
  native state and re-applies `indeterminate` on every render, so a click never leaves a stale dash.
- Docs: web-ui.md 17 and the kit README name `MarkHue`. Three new tests and updated ones.

## 2026-10-14 (v0.27.0, light cards, status buttons, choice controls and console gaps)

- Tokens: the light surface ladder puts white cards on a light grey canvas. `--surface-1` is
  `#ffffff` in light (the canvas is a cool light grey), the steps above it descend from white for
  states on a card (table heads, hover, chips, pressed), and the inset well stays white with the
  field border. Borders and `--elev-1` carry the separation, so apps no longer override the card
  colour per theme. Dark is unchanged. Every certification still passes (named accents
  regenerate their light chip tint from the new surface), and the light descriptions quote the
  new luminance and border ratios.
- Tokens: two extra categorical hues taken by name only, `--hue-yellow` and `--hue-ink` (the
  solid neutral, near black in light and a light slate in dark), each with a deep stop. They are
  certified as marks on every content surface and with white text at the gloss peak, are listed
  in `categorical_extra` (`extraHues` in tokens.ts, Tailwind `hue-yellow` and `hue-ink`) and never
  enter the series rotation, the avatar hash or the accent withholding. New certify rules cover
  white on the solid success, warning and danger buttons and the subtle button inks on their tints.
- Kit: `Button` variants `success` and `warning` (solid deep fill, white text) and
  `success-subtle`, `warning-subtle` and `danger-subtle` (status tint, hairline and ink).
- Kit: new `Checkbox`, `Radio`, `RadioGroup` and `Switch`. Native checkbox and radio inputs with a
  drawn box, visible label, optional description, `hideLabel`, `disabled`, `size` sm or md and
  `indeterminate`, a fieldset radio group (`options` or children, controlled or not, orientation,
  hint and error), and a `role="switch"` button with an optional hidden form input.
- Kit: `Modal` takes `hideHead` (the title still names the dialog: a string becomes aria-label,
  any other title a hidden heading, the close button floats), sizes `wide` and `full`, and passes
  `data-*` and other HTML attributes through to the panel (a passed `onKeyDown` runs first).
- Kit: `Segmented` options take an `icon`, and `iconOnly` shows only the icon with the label kept
  as the accessible name and the tooltip.
- Kit: `Select` takes a typed `labelledBy` (aria-labelledby) for a select outside a Field.
- Kit: new `Stat` and `StatRow`, the light KPI card (label, value with an optional status ink,
  hint, hue icon tile, optional click and selected ring) in a wrapping, labelled row. `StatTile`
  stays the deep-fill hero tile.
- Kit: `ThemeProvider` stores a System pick as `system`, so an app default other than system no
  longer overrides it on the next visit. `themeInitScript(key, defaultChoice)` applies the same
  default before first paint and leaves a stored `system` to the OS.
- Kit: `Rail` builds a standard status line from `environment` (an accent badge), `v<version>`
  and `statusText`, with `showVersion={false}` when the footer already shows the version. An app
  `status` is rendered as given, so the version never shows twice.
- Kit: toasts dedupe by `id` only. `toast(..., { id })` replaces the toast with that id in place
  and restarts its timer, and calls without an id always stack, so the same text twice and JSX
  messages show.
- Kit: `CATEGORICAL_HUES` stays the six series hues (`SeriesHue`), `EXTRA_HUES` and `isSeriesHue`
  are new, and `CategoricalHue` (every `hue` prop) now accepts the extra hues.
- Docs: web-ui.md sections 2, 7, 17 and 19 and the kit README describe all of the above. Gallery:
  new Stats and Choices specimens, status buttons, extra hue tiles, Segmented icons, a labelled
  Select, headless and wide dialogs and an in-place toast. Visual baselines refreshed.

## 2026-10-13 (v0.26.0, merge lane preflight and decision handoffs)

- PR review and merge 1.1: five new rules in section 1, registered with check kind test.
  `pr-review-and-merge.1.13` preflight runs every gate (tests, hygiene, conflicts, a policy dry
  run listing the owner sign-offs, open-change overlap) before the push and fails closed.
  `pr-review-and-merge.1.14` self-review against the reviewers' own prompts, recorded in a file
  bound to a hash of the diff. `pr-review-and-merge.1.15` infrastructure noise is re-run only
  when every failed job matches a named pattern, capped per head (refines 1.12).
  `pr-review-and-merge.1.16` deletes owned by another open change wait on it and re-arm after
  it merges, never offered as a sign-off. `pr-review-and-merge.1.17` a fixer that needs the
  owner returns a structured decision with head-pinned option buttons, and missed findings are
  appended to the finding catalog. Checklist lines added.

## 2026-10-13 (v0.25.0, owner apply guard)

- IaC governance 1.1: new rule 1.11, owner applies never delete open work's objects. An owner
  apply of a root that an open branch already applied from is checked against the resources open
  pull requests declare in that root, and refused on a match unless the owner names the pull
  request. Checklist line added. Registered as `iac-governance.1.11` (check kind test).

## 2026-10-13 (v0.24.0, shared Hermes practice and local ops performance)

- New `hermes/` area: `configurations.md` (chat display, scheduled jobs behind pre-run gates,
  credential pools, plugin middleware versus hooks, service-manager pitfalls, skill descriptions,
  interpreter floor), the `core-` naming rule for shared skills, `build_skills.py` (generates the
  `core-practices` skill from the rules registry) and `sync_skills.py` (installs `core-*` skills
  into a consumer with hashes, reports and keeps hand edits, removes skills that left the core).
- New check `checks/check-hermes-skills.py` (in CI): shared skills are `core-` named with a valid
  front matter, and `core-practices` is current.
- Local ops app 1.2: new section 15, performance and polling budget (stale-while-revalidate with
  single flight, background live checks, per-upstream rate budgets, one poller per dataset and a
  badges endpoint, hidden-tab pauses, lazy routes with idle prefetch, gzip with ETag revalidation,
  keep-alive). Section 6 now marks only people data `no-store`, section 7 caches serve stale while
  refreshing. Registry: `local-ops-app.15`, statements of `.6` and `.7` updated.
- README: layout row, the Hermes section, the new check.

## 2026-10-13 (v0.23.0, actionable state is server truth)

- Live actions 1.1: four new rules. Rule 11, an object shows action buttons only when the server
  marks it `needs_action` from the same live preconditions its handler checks (no disabled buttons
  standing in for that). Rule 12, upstream drift (a moved base, a new run attempt) starts the
  refresh automatically once per new version. Rule 13, every needs-action object carries at least
  one action that moves it, and records that can never apply are dropped. Rule 14, a failed live
  read never hides an object, and live reads refresh in the background.
- Rules registry: `live-actions.1.11` to `live-actions.1.14`, checklist and test list updated.

## 2026-10-13 (v0.22.2, third round of kit review fixes)

- Kit: new `safeHref(url)`. `NavItem`, the `Header` home link and `DefaultLink` pass their href
  through it, so a javascript, data, vbscript or any other non web scheme (after trimming, control
  character stripping and case folding) renders a plain anchor without an href and never reaches
  the router adapter. Relative paths, fragments and http, https, mailto and tel URLs pass.
  Development builds warn once.
- Kit: `openCommandPalette()` obeys the same guard as Cmd or Ctrl and K, so the palette never
  stacks on another open dialog.
- Kit: `useNow` raises an interval under one second to one second and falls back to the default
  for one that is not a finite number, like `FeedStrip`.
- Kit: popovers and menus portal into a body-level layer root (`layerRoot()`) instead of
  `<main>`, so an animated transform on `<main>` cannot misplace them. Focus return and the
  `--z-popover` layer are unchanged.
- Kit: `sideEffects` is `**/*.css`, and the README tells consuming packages to declare the same,
  so bundlers never tree-shake the style sheets.

## 2026-10-13 (v0.22.1, second round of kit review fixes)

- Kit: the open mobile drawer registers as a modal layer, so global shortcuts and Cmd or Ctrl and K
  pause while it is open. A prevented `NavItem` click (an unsaved changes guard) keeps the drawer
  open.
- Kit: `Menu` keeps the trigger's own ref, `onClick` and `onKeyDown` (they run first, and
  `preventDefault` in them stops the menu), under React 18 and React 19.
- Kit: `appId` must match `APP_ID_PATTERN` (letters, digits, `-`, `_`, at most 64), otherwise
  `storageKeys` throws, so ids with separators can never build overlapping keys.
- Kit: `AccentProvider` puts the previous root accent back on unmount. `FeedStrip` falls back to the
  default rotation for an interval under one second or not a number. A pending two-key shortcut no
  longer completes from inside a text field.

## 2026-10-13 (v0.22.0, per-app storage, banner dismissals, row activation)

- Kit: optional `AppShell appId` (and `StorageScope`, `useStorageKeys`, `storageKeys`) scopes the
  build card and announcement keys per app, as `shell.<appId>.build.seen` and
  `shell.<appId>.announce.dismissed`, for apps that share one origin. Theme and rail pin stay
  global. Without `appId` the keys are unchanged, so existing apps are unaffected.
- Kit: dismissing one announcement no longer erases another. `useDismissed` re-reads storage and
  merges on every dismiss (newest 200 ids kept), banners on one page share the list, and the
  `storage` event syncs other tabs. `readDismissed`, `addDismissed` and `DISMISSED_CAP` are exported.
- Kit: `AnnouncementStack` owns the dismissed list and hides dismissed banners before it sorts and
  caps to five (`visibleAnnouncements`), so a dismissal lets the sixth banner in. New optional
  `onDismiss` on the stack. `AnnouncementBanner` still works on its own.
- Kit: `Table` rows no longer activate from clicks or keys on interactive content inside a cell
  (buttons, links, fields, labels, menuitem, checkbox and button roles, contenteditable,
  `[data-no-row-activate]`) or from an event a handler already prevented. Helpers
  `isFromInteractiveDescendant` and `ROW_INTERACTIVE_SELECTOR` are exported. The table body is no
  longer remounted on every filter change, so a focused row keeps focus.
- Kit: opening a `Menu` with Enter, Space, ArrowDown or a click focuses the first enabled item
  (ArrowUp the last).
- Kit: the open mobile drawer traps Tab and locks page scroll. Cmd or Ctrl and K no longer opens
  the palette over another open dialog. `themeInitScript` escapes `<` in the storage key. Media
  query listeners fall back to `addListener` where `addEventListener` is missing (`onMediaChange`).
- `hub-layer.css`: the row entrance animation is scoped to the kit table (`.table tbody tr`), so
  app tables that do not use the kit are no longer animated. An audit of both sheets found no
  other bare element selector (`fieldset.seg` and `div.tone` are class qualified).

## 2026-10-13 (v0.21.1, kit types under React 18)

- Kit: the shell context types `menuButtonRef` as `Ref<HTMLButtonElement>` instead of
  `RefObject<HTMLButtonElement | null>`. With React 18 types the old shape is not assignable to a
  button `ref`, so a consumer pinned to React 18 failed its typecheck on `Header`. The new type
  compiles under React 18 and React 19 types. Found on the first consumer that pins React 18.

## 2026-10-13 (v0.21.0, element rules below the core layer)

- web-ui.md section 7 and kit/README.md: since v0.17.0 the core sits in `@layer core`, so an app's
  bare element rules (`a`, headings, `table`, `th`, `td`) beat kit classes and restyle kit tables and
  links. New recipe: declare `@layer base, core;` in a first stylesheet and put element defaults in
  `base`. Found on the first consumer upgrade, where scheduled-job table rows lost their height.

## 2026-10-13 (v0.20.0, visual gate)

- Kit visual gate: Playwright screenshots of every gallery specimen in dark and light against
  committed linux baselines, and axe in a real browser with color-contrast on (both themes, with
  the dialog and the sheet open, zero violations). New `visual` workflow in the pinned Playwright
  image, `npm run visual` and `npm run visual:update` (regenerates the baselines in CI and
  downloads them, or `-- --docker` locally). The `visual` job runs on every pull request and is
  required next to `ci` (three consecutive green runs, and a CI regenerated set matched the
  committed baselines byte for byte).
- Gate determinism: the clock is installed and paused before load, reduced motion is forced, the
  theme comes from the `gallery.theme` storage key, and `?gate` shows fixed sample release notes.
- Finding: the feed strip pager dots are 8 by 20 pixel targets and fail axe `target-size` (WCAG
  2.2, 24 by 24). The gate turns that one rule off until the kit component grows the dots. Colour
  contrast passes everywhere in both themes.
- Gallery: the stick figure card is an even three by two grid with pose names, and the Hues for
  data card is a legend (name, bar at the chart value, value) that keeps its own height.
- Releases attach `kit-gallery-<tag>.zip` (new `gallery-release` workflow) and every pull request
  uploads the built gallery as the `kit-gallery` artifact.

## 2026-10-13 (v0.19.0, docs restructure and rule scopes)

- `web-ui.md` 4.0: every token it names is a current token from `tokens.json`, `hub-layer.css` or
  the kit (the retired `--c-*` palette and the `ds-*` class map are gone), source-app file paths
  replaced by kit components, and sections 15 to 24 state each rule once and link to the section
  that owns it. Section numbers and rule ids are unchanged. The stat tile class is settled:
  `StatTile` renders `.kpi-tile`, which `hub-layer.css` styles, and `.stat-tile` is kept on the same
  element for older markup only. Section 14 describes the entrance cascade and the route entrance in
  token names, and behaviour timings by their kit constants. Facts aligned with the kit: rail
  `--rail-w` (58px), `--sidebar-w`, the 900px drawer breakpoint, announcement body 500 characters.
- New check `checks/check-token-names.py`, in the README Checks block and core CI: fails when a
  standards doc names a `--token` that is not in `tokens.json`, not declared by `hub-layer.css` and
  not declared by `kit/src/**/*.css`.
- `checks/check-links.py` now also checks heading anchors (`doc.md#anchor` and `#anchor`).
- Fixed the broken anchor in `rbac.md` to `web-build.md#4-auth-platform-level-auth`.
- Rules registry: 64 new rules for `rbac.md`, `data-safety-sqlite.md`, `ci-cd-release.md`,
  `local-ops-app.md`, `wpf-design-system.md` and `wpf-powershell-gui.md` (169 in total). Check
  kinds are `overlay-ci`, `test` or `review`. `wpf-powershell-gui.md` sections are now numbered so
  rules can name them (anchors in `cmtrace-logging.md` updated).
- `applies_to` gains `powershell`, `python` and `iac` (with `web`, `wpf`, `local-ops`, `all`). The
  scripting and IaC rules move from `all` to their stack.
- Consumer-visible: `scripts/core-status.py` reads an optional `Stacks` row in
  `standards-local/parameters.md`. When it lists the overlay's stacks, rules for other stacks are
  left out of the report and listed under `out_of_scope`, and new or changed rules upstream are
  filtered the same way. With no row, or an empty one, every rule is reported as before. Nothing to
  do on upgrade.
- README groups the standards as foundations, components, patterns, app types and engineering,
  with each doc's scope.

## 2026-10-13 (v0.18.0, lint for layout edge bars, hook dialogs and scripts)

- UI001 also reports an edge bar built from layout: a first or last `grid-template-columns` (or
  `grid-template` columns) track of 6px or less in a file where a painted cell stretches or takes
  full height, and a non-pseudo element 6px or less wide with a painted background. Dots (height
  at most twice the width) are not bars. Same `edge-ok` escape, reported on the line of the narrow
  track or the narrow width.
- UI002 no longer flags `confirm(...)` or `prompt(...)` when the file binds the name itself, for
  example `const { confirm, dialog } = useConfirm()` or `const { prompt } = usePrompt()`.
  `window.confirm`, `window.alert`, `window.prompt` and a bare call the file never binds are still
  flagged, and so is a bare `confirm(` next to an alias such as `const { confirm: ask }`.
- New `lint/script_lint.py`: PS001 non-ASCII PowerShell, PS002 section 5 header fields and
  approved Verb-Noun function names (verb list embedded, no `pwsh` needed), PS003 empty catch,
  PY001 shell command lines (`shell=True`, `os.system`, `os.popen`, `subprocess.getoutput`), PY002
  ruff `target-version` equal to the floor. Same `core-exception` suppression and ratchet baseline
  as the UI lint. It runs only when the overlay adds `standards-local/script-lint.json`, otherwise
  it prints one skip line and passes. Fixtures in `lint/script-fixtures`, `--self-test` in core CI.
- Rules registry: `scripting-powershell.1.4`, `scripting-powershell.1.6` and `scripting-python.1.8`
  are now `lint` rules (PS003, PS002, PY001). `scripting-powershell.1.7` and `scripting-python.1.10`
  stay `overlay-ci`, with PS001 and PY002 as supporting checks. `check-rules.py` knows the script
  lint, and `core-status.py` fails a rule on supporting findings but never passes it on them.
- Overlay template: `core-drift.yml` runs the script lint (a skip until configured) and the README
  lists `standards-local/script-lint.json`. `check-exceptions.py` skips markers inside the synced
  core copies, so the lint fixtures in `lint-core/` never need rows in an overlay's table. Nothing
  to do on upgrade.

## 2026-10-13 (v0.17.0, kit gaps from the first full adoptions)

- Kit `Spinner` (xs, sm, md, lg, hidden from screen readers unless labelled, still under reduced
  motion) on the new `--dur-spin` token, and `live` on `Pill` and `Badge` for rows that are still
  working.
- New status token `urgent` (with `-dim` and `-border`), the orange high-priority step between
  warning and danger, in both themes and certified by `tokens/build.py` (ink on every content
  surface and on its tint). Badge, Pill, StatusDot and Segmented take the `urgent` tone. The
  Tailwind preset maps it too.
- `Table`: `rowClassName(row)`, `rowProps(row)`, and an optional controlled `sort` with
  `onSortChange`. Uncontrolled stays the default.
- `Segmented`: per-option `tone` (a dot and a tinted badge) and `badge` count.
- `Modal`: `onClose(reason)` gets `'escape'`, `'backdrop'` or `'close'`. Handlers without an
  argument keep working. Focus returns to the panel when the focused node inside unmounts.
- `hub-layer.css` and `kit.css` now sit in one cascade layer, `@layer core`, so unlayered app CSS
  wins by default. The gallery renders pixel for pixel the same in both themes.
- `Input size="sm"` matches the Segmented height. `SearchTrigger compact` (`true` or `"auto"`
  below 640px) is icon-only with the shortcut kept in the accessible name. `CommandPalette`
  `onQueryChange`. `AnnouncementBanner` `action` slot, and `dismissible: false` from the stack.
- `Rail status` line under the build card, and `NavItem` `softBadge` with an optional `working`
  spinner.
- `gen-changelog.mjs`: `--path <dir>` reads only the commits touching a folder, and `--allow-empty`
  (or `CHANGELOG_ALLOW_EMPTY=1`) now also covers an empty or missing history for compile-only
  builds. Default behaviour is unchanged.
- Gallery: a Working and live states specimen, urgent marks, Segmented tone and badge, banner
  actions, the compact input, a controlled table sort, the rail status and a soft nav badge.

## 2026-10-13 (v0.16.0, engineering practice standards)

- Eight new docs, each with a section 1 of numbered rules (the failure each prevents and its
  acceptance line), detail sections and a checklist: `scripting-powershell.md`,
  `scripting-python.md`, `secrets-and-credentials.md`, `automation-safety.md`,
  `pr-review-and-merge.md`, `live-actions.md`, `docs-and-changelog.md` and `iac-governance.md`.
- Rules registry: 80 new rules (`<doc>.1.<n>`, `applies_to: all`), 105 in total. Check kinds are
  `overlay-ci`, `test` or `review`, so they report as unverified in `core-status.py` until an
  overlay wires a check or records an exception.
- Overlay parameters sheet: optional rows for the Python floor, the secret store, the docs home,
  the live-action tombstone TTL, the change freeze calendar and the IaC back-port window.
- Cross-links only in existing docs: `cmtrace-logging.md` section 8 points at the PowerShell
  standard, `ci-cd-release.md` section 9 at the secrets and PR flow docs, `local-ops-app.md`
  section 13 at live actions. No existing rule changed.
- README lists the new docs. New ingest record `ingest/source-2-operating-practice.md`.

## 2026-10-13 (v0.15.0, private-core CI recipe)

- README: "CI that builds the app" walks a consumer through restoring the synced copies in CI from a
  private core with a read-only deploy key: key pair, secret, the admin step on the core, the workflow
  steps, verification, rotation. Step 5 no longer says CI never needs the core, the mirrors item and a
  new FAQ entry for `Permission denied (publickey)` point at it.

## 2026-10-13 (v0.14.0, sync from a checkout)

- Overlay sync: `CORE_CHECKOUT=<path>` makes `sync-core.py` clone from an existing checkout of the core
  instead of `gh`, so CI can sync with a read-only deploy key and a restore can run offline. README
  shows the CI recipe.

## 2026-10-13 (v0.13.0, consumer update practices)

- README: the local updater pattern from the first consumer without remote CI (test the release on
  the committed code in a copy, hold when the current pin already fails, gate before and after
  applying with rollback, commit by name, one work item per problem set), the `tsc -b` pitfall with
  a linked `node_modules`, and why mirrors and backups should leave the synced copies out (plus the
  gitleaks false positive on the WPF token dictionaries).
- README: the sync section names every synced folder, the release notes generator, the sync
  handover with its one-time double sync from v0.11.0, and the Python 3.9 floor. The `git add`
  example now stages all synced paths.

## 2026-10-13 (v0.12.0, the shared React kit)

- New `kit/`: the shared React kit for React 18 and 19, plain TSX with no runtime dependencies,
  styled only with tokens on the hub-layer recipes. Theme (light, dark, system, circle reveal) and
  accent, the shell (AppShell, hover rail with pin, Header, PageHeader, Toolbar), primitives
  (Button, Card, Badge, StatTile with count-up, Tabs, Segmented, fields, sortable Table,
  EmptyState, Tooltip), overlays (Modal with focus trap and layered Escape, useConfirm,
  usePrompt, Toaster with Undo, Popover, Menu), the required chrome (CommandPalette, BuildCard
  with release notes, FeedStrip, announcements, ShortcutLayer) and the chart theme with the
  withheld-hue palette. A gallery with theme and accent switchers, 55 unit tests, axe on the
  gallery in both themes (14 scans, zero violations), and a kit CI job. The kit passes the UI
  lint with zero findings.
- Overlays: sync copies `kit/src/` to `kit-core/` and the release notes generator to
  `scripts/gen-changelog.mjs`. The sync now refreshes its own tooling first and hands over to the
  new copy when it changed, so a tooling change applies in one run. Upgrading from v0.11.0 or
  earlier: run `sync-core.py` twice this once (the first run installs the handover).
- web-ui sections 6, 7, 8, 14 and 18 point at the kit instead of files in the source app. Section
  18 and the stat tile recipe now use the v0.10 tokens (gloss, shade, key shadow, on-fill inks,
  `--dur-chart`), and section 14 names where behaviour timings live.
- `check-links.py` scans the git file set like the other checks, so installed dependencies never
  count. The overlay parameters sheet names the accent model instead of a raw rgb value.

## 2026-10-12 (v0.11.0, rules registry and overlay status)

- New `standards/rules.json`: 25 enforceable rules with a stable id, the section an exception names,
  statement, acceptance and check kind. All 8 UI lint rules, the contrast gate, the web-ui
  non-negotiables and the behavioural-layer acceptance lines are registered. `checks/check-rules.py`
  validates it against the docs and the lint and prints coverage per doc (the other docs register
  their rules in the docs restructure).
- New overlay `scripts/core-status.py`: one JSON report of the pin, every registered rule's status
  (pass, excepted, fail, unverified), expiring exceptions and, with `--latest`, rules new or changed
  upstream. It is what a nightly job reads to raise work items.
- UI lint, breaking for anyone using v0.9 baselines: exceptions are rule-scoped. A
  `core-exception` marker suppresses only findings of the rule its row names, and a ratchet baseline
  ties each rule's counts to the exception naming that rule (`--write-baseline` no longer takes
  `--exception` and refuses when a rule with findings has no row). The self-test now covers the whole
  ratchet: write, hold, a new finding, a missing exception and expiry.
- UI006 points at web-ui section 4, which now states the ASCII punctuation rule. Rules 0.1 and 0.7,
  section 17 acceptance and the section 9 gate table name the UI lint instead of scripts that only
  existed in the source app. A leftover phrase in section 1 now names the app accent.
- `check-exceptions.py` warns when an exception names a rule that is not registered.

## 2026-10-12 (v0.10.0, the core passes its own rules)

- `tokens/hub-layer.css` now passes the UI lint with zero findings, and core CI lints it with no
  baseline: 101 raw durations, 31 colour literals, 6 raw z-indexes and one theme-branching selector
  moved onto tokens. Durations snap to the scale (within 25 percent). The two live pulses (1.8s and
  2.4s) are one heartbeat, `--dur-pulse`.
- New tokens: `--dur-travel`, `--dur-enter`, `--dur-page`, `--dur-chart`, `--dur-pulse`,
  `--stagger-step`, `--shadow-xs`, `--shadow-key`, `--shadow-lift`, `--shadow-pop`, `--backdrop`,
  `--sheen` and the `--on-fill-*` group. Light mode shadows in the recipes follow the elevation light
  formula (navy tinted, lighter) instead of reusing the dark values.
- Contrast is certified at the gloss peak of every deep tile (`base+overlay` references in
  `certify`). That found tile hint text at 3.80:1 on amber and 4.23:1 on teal. Fixed by lowering the
  tile gloss from 12 to 8 percent and moving `--hue-amber-d` to OKLCH L 0.47 like the other deep
  stops. White text on the accent fill now also certifies `--accent-fill` and `--accent-fill-d`.
  293 of 293 checks pass, and every named accent passes the new rule.
- Decorative assets (the presenter figure, the build card) declare their own timing variables once
  at the asset root instead of adding 36 art timings to the global token set.
- New `checks/check-css-vars.py`: every `var()` without a fallback in the core CSS must resolve.
- UI lint: UI008 now also catches `@media (prefers-color-scheme)` in app CSS, and skips token files
  and certified accent blocks, where theme branching belongs.
- web-ui section 14 lists the duration scale, dialogs exit on `--dur-base` (the old 170ms and the
  0.8x rule disagreed), and a corrupted heading ("Entrance cascade") is restored.

## 2026-10-12 (v0.9.0, UI lint and overlay tooling)

- New `lint/ui_lint.py`: the static web-ui rules as one stdlib linter (UI001 edge bars, UI002 native
  dialogs, UI003 colour literals, UI004 raw z-index, UI005 raw durations, UI006 typographic
  characters, UI007 accent set outside the root, UI008 theme branching). Suppression only through
  `edge-ok` (data marks) or an active `core-exception: EXC-NNN`. An adoption ratchet: a baseline
  tied to one active exception, CI fails only on new findings, and an expired exception ends it.
  Core CI runs `--self-test` against fixtures (27 seeded findings, zero on the clean fixtures).
- Overlays: sync now copies `lint/` to `lint-core/` and `kit/src/` to `kit-core/` (when present),
  refreshes the overlay scripts from the template on every sync, and `core-drift.yml` runs the UI
  lint with `standards-local/ui-lint.json`.
- Known gap: `tokens/hub-layer.css` itself still carries 101 raw durations, 31 colour literals and 6
  raw z-indexes. Moving it onto motion and colour tokens is the next core change.

## 2026-10-12 (v0.9.0, single token source)

- `tokens/tokens.json` is now the one token source and `tokens/build.py` generates `tokens.css`,
  `tokens.ts`, `tailwind.preset.cjs`, WPF dictionaries (`tokens/wpf/`) and `tokens/CONTRAST.md`.
  CI runs `build.py --check`, which fails on a stale output or any failed contrast rule (259 checks).
  The hand-kept mode blocks had drifted, now they are generated from one declaration. Verified
  identical to the previous sheet in all 12 OS, theme and print combinations, apart from the fixes below.
- Contrast fixes, measured: `--danger` was 4.15:1 (dark) and 4.19:1 (light) on hover rows, now
  `#f46067` and `#ba0517`, 4.55:1 or better on every content surface. Light categorical marks
  green, amber and teal now clear 3:1 on every content surface (`0 137 65`, `168 104 0`, `0 133 122`).
- Named accents are generated and certified from a seed: cobalt (default), blue, indigo, violet,
  fuchsia, rose, red, orange, hub, amber, gold, green, teal, cyan. They replace the alpha-derived
  accent blocks in `hub-layer.css`, whose chips and borders shifted contrast per surface. New
  tokens: `--accent-seed` (exact brand colour, identity marks only), `--accent-withheld-hue`,
  `--accent-rgb-d`, `--accent-fill`, `--accent-fill-d`. Custom accents: `build.py --accent NAME=#hex`
  in an overlay prints a certified block.
- Accent discipline (web-ui rule 2, sections 12 and 16): an accent may share a categorical hue's
  family, and that hue is then withheld from data in that app. Replaces the ban on accents near a
  categorical hue and the per-app accent tables.
- web-ui section 2 now describes the token architecture over `tokens.json` instead of a second
  palette. The `--c-*` table it carried disagreed with `tokens.css` on every surface and ink.
  Tailwind builds take `tailwind.preset.cjs`.
- `hub-layer.css` defines no tokens of its own. The brand nav icon uses the certified ink.
- local-ops-app section 14 uses the `indigo` named accent.

## 2026-10-12 (v0.9.0, sanitisation hardening)

- `check-sanitised.py` also reads private denylists kept outside the repo
  (`~/.config/build-standards-core/denylist.txt`, or `CORE_PRIVATE_DENYLIST`) without printing their
  terms, and fails on any real email address.
- New `check-authors.py` in CI: every commit must use a GitHub noreply email.
- New `checks/hooks/pre-commit` runs all checks locally, private terms included.
- Removed source residue: the KB provenance lines in web-ui and web-build, a product name in
  `tokens.css`, and the business-initial wordmark class (now `.brand-wordmark`, web-ui section 6).

## 2026-10-12 (v0.8.0)

- Source of truth: the standards in this repo outrank every implementation, including the app a
  rule came from. The "code is ground truth" lines in web-ui, web-build, rbac, local-ops-app and
  cmtrace-logging now point to the README section.
- Explicit exceptions: overlays record a time-boxed exception per app in
  `standards-local/exceptions.md` (ID, rule, scope, deviation, reason, owner, approved, review by,
  at most 180 days) and mark deviating lines with `core-exception: EXC-NNN`. The overlay template
  ships `scripts/check-exceptions.py`, and `core-drift.yml` runs it.

## 2026-10-12 (v0.7.1)

- Wording: README now names `sync-core.py latest` in the upgrade steps.

## 2026-10-12 (v0.7.0, lockstep)

- Overlay: `check-core-sync.py --latest`, `sync-core.py latest`, `update-core.py`, optional `targets.map`, and a `core-update.yml` workflow that opens an auto-merging pull request on a new release.
- README: Upgrading, Staying in lockstep, and What is and is not shared.

## 2026-10-11 (v0.1.0)

- Editing pass on ten standards (ci-cd-release, cmtrace-logging, data-safety-sqlite, identity-and-people-data, local-ops-app, notifications, rbac, web-build, wpf-design-system, wpf-powershell-gui): neutral voice, generic references, placeholder tidy-up, one PR per doc.
- Folded `standards/web-ui-hub-layer.md` into `standards/web-ui.md` as sections 15 to 24 and removed the separate doc. Retitled the doc "Web UI Design System".

## 2026-10-10 (v0.1.0, first import)

- Initial import of the first source repo's build standards, sanitised: web UI, web build, CI/CD
  and release, RBAC, data safety, identity and people data, local ops apps, notifications,
  logging and the two WPF docs. See `ingest/source-1-device-standards.md`.
- Added the sanitisation, ASCII and link checks and the CI workflow that runs them.

## 2026-10-10 (v0.1.0, hub layer)

- Added `standards/web-ui-hub-layer.md`: per-app accent token, categorical hues, tone and selection surfaces, no edge bars, stat tile and glow, count-up, desktop icon rail, announcements and pulse feed, request analytics, build card, Undo versus confirm, shell chrome. Linked from `web-ui.md`.

## 2026-10-10 (v0.1.0, overlay template)

- Added `templates/overlay/`: pin file, sync script and local parameters sheet for a business overlay repo.

## 2026-10-11 (v0.1.0, consumption docs and nav icons)

- Rewrote `README.md`: contents, what lives in the core versus an overlay, the flow diagram, step by step consumption, the tighten-only rule, contribution flow, versioning, checks, adding a source repo, FAQ.
- `standards/web-ui.md` section 6: nav icons are one neutral colour in every state.

## 2026-10-11 (v0.1.1, nav icon hues)

- `standards/web-ui.md` section 6: nav icons are colour-coded per destination, replacing the same-day uniform-colour rule.

## 2026-10-11 (v0.2.0, overlay template v2)

- `templates/overlay/scripts/sync-core.py` resolves paths from its own location, so it works from any directory and from an overlay in a subfolder. Found by following the README in a fresh repo.
- Added `scripts/check-core-sync.py` and `.github/workflows/core-drift.yml` to the template, with README steps for the read-only `CORE_READ_TOKEN` secret the private core requires.

## 2026-10-11 (v0.2.1, consistency pass)

- `standards/web-ui.md`: font fallbacks are an overlay choice; sections 12 and 16 now say they are one accent rule in two spellings; added a table of which hub gates are enforced, recommended or review-only.

## 2026-10-11 (v0.3.0, core-drift action)

- Added the composite action `.github/actions/core-drift`: a same-organization consumer needs no secret. The template workflow uses it; the token workflow stays as `core-drift-token.yml.example` for other owners. README step 5 documents both modes.

## 2026-10-11 (v0.4.0, required chrome and day one)

- `standards/web-ui.md` section 25: required chrome for every app with a sidebar (rail, icon hues, build card with a working what's-new, live feed strip, banners, palette, theme toggle) with acceptance lines, and the deploy pitfall that empties a git-built changelog.
- README: day-one checklist for accounts that own their own repos, with a troubleshooting table. Token mode is the path for any owner other than the core's.

## 2026-10-12 (v0.4.0, portable tokens)

- Added `tokens/` (`tokens.css`, `hub-layer.css`) so an app on any stack can match the look. `sync-core.py` copies it to `tokens-core/` and the drift check and action compare it.

## 2026-10-12 (v0.5.0, offline drift check)

- The overlay template's default `core-drift.yml` is now an offline check: `sync-core.py` records `content_sha256` in `standards.lock` and `check-core-sync.py` recomputes it. No secret, no `gh`, no access to the core is needed, so it works for any GitHub owner. Token and organization modes remain as optional examples. Older locks without the field are tolerated.
- Scripts print one plain message when the core cannot be read (which account `gh` is signed in as, and what to check) instead of a stack trace.
- README step 5, the day-one list and the troubleshooting table are rewritten for this.

## 2026-10-12 (v0.6.0, personal owner)

- The core moved to a personal GitHub account so accounts outside the original organization can be invited. Removed what only worked inside an organization: the composite action, the organization and remote workflow examples, and the fleet files. CI in an overlay uses the offline hash check only.
- Token and hub-layer stylesheet headers no longer name a business.
- Note: on a free personal private repo, collaborators have write access and branch protection is not enforced; changes still go by pull request by convention.

