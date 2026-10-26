---
name: core-consumer-report
description: "Use when asked to produce, refresh or file this account's consumer report on the core: collects machine, design, design diff, functionality, practice and gap data from real state, sanitises it, and updates the account's single consumer-report issue."
---

# Core consumer report

The report is how a consumer's improvements reach the core. The owner approves every item one by
one, then the core changes and every consumer gets it. Where this machine's design is ahead of the
core, the report must let the core be raised to it; where its functionality depends on local parts,
the report must show what adopting a core part would break. The outline and the sanitising rules
are in the core's `CONTRIBUTING.md` ("Reporting from a consumer") and the template
`.github/ISSUE_TEMPLATE/consumer-report.md`. This skill is the procedure.

## Hard rules

- **Never invent data.** Every row comes from a command you ran, code you read or a screen you
  captured. When something cannot be collected, write `not collected: <reason>` in its place.
- **Names never leave the machine.** Repos and apps are named by role (product app, local ops
  center, multi-module shell, hub, agent home), numbered when there are several (`repo-1`). No
  repo, app, host, employer, person, account, tenant, plan or path. Numbers go in as ratios,
  deltas or before-and-after pairs; the core-status rule counts are the core's own rules and go
  in as they are.
- **Plain ASCII.** No em or en dashes, curly quotes, NBSP or arrows.
- **One issue per account.** Update the open `consumer-report` issue this account authored; create
  it only when none is open, in the private intake. Never file it on the core, and never open a pull
  request on the core.
- **The nightly owns its markers.** Keep `<!-- nightly:changes:start -->` to
  `<!-- nightly:changes:end -->` and `<!-- nightly:candidates:start -->` to
  `<!-- nightly:candidates:end -->` byte for byte as they are in the current issue body.
- **Item ids are stable.** `D-nnn` design, `P-nnn` practice and CI, `G-nnn` gaps. Read the current
  issue first; keep every existing id with its number, continue numbering after the highest, never
  reuse a rejected id.
- **A v1 report's ids carry over by number.** A report in the older v1 shape numbered its gaps
  `D1`, `D2` and so on, which would now read as design ids. Carry each one over as the `G` item
  with the same number (`D1` is `G-001`), say so in one line at the top of section f, keep each
  carried item's state (open, closed by a release, rejected), and continue new gaps after the
  highest carried number. Any other v1 id prefix carries over the same way to the item kind it
  meant.
- **Fit the body in 65,536 characters.** GitHub refuses an issue body over that limit. Draft the
  body first and measure it (`wc -c`). When it is over about 60,000 characters, move whole tables,
  largest first (the per-part design diff of section c, then the functionality tables of section
  d), into a markdown file in the report's secret gist (step 7.2), and leave in the body the
  section heading, one line per moved table with its row count and the raw link
  (`https://gist.githubusercontent.com/<login>/<gist id>/raw/<file>.md`, the same form both checks
  accept for screenshots), and every item
  (`D`, `P`, `G`) in full. Items and the nightly's marker sections always stay in the body.

## 0. Prepare

1. Core clone: the one the nightly pulls (the `core` key in
   `~/.config/build-standards-core/consumer.json`, else `~/GitHub/build-standards-core`). Read it,
   never edit it.
   The report goes to this account's PRIVATE intake, never the core: `report_repo` in
   `~/.config/build-standards-core/consumer.json` (or `$CORE_REPORT_REPO`). Call it `$INTAKE`. Stop
   and say so when it is unset, equals the core, or `gh repo view "$INTAKE" --json visibility --jq .visibility`
   is not `PRIVATE`: a report holds this account's design inventory and must never be public.
2. Scratch directory outside every repo, for example `mktemp -d` under the user's cache. The draft
   (`report.md`) and the screenshots go there.
3. Current issue:
   `gh issue list -R "$INTAKE" --label consumer-report --author @me --state open --json number,body,url -L 5`.
   Save the body; you will update it in place.

## 1. Section a: machine and ways in

1. `cat ~/.config/build-standards-core/consumer.json`. Rewrite it with every repo slug, path, host
   and account replaced by its role label; keep the keys, modes, overlay names and `apply` flags.
2. Nightly jobs: `hermes cron list` (name, schedule, last result). Without Hermes: the machine's
   scheduler entry that runs `hermes/nightly.py`, or `not collected: no scheduler found`.
3. Per registered repo, from its clone:
   - the way, written with its neutral label, never the mode value: `workflow`, `apply-at-once`
     (the `direct` mode), `vendored` or `agent-home`. A mode value can equal a private repo
     name on someone's denylist, so the label keeps the draft passing the checks;
   - pinned release: `standards.lock` in the overlay (`ref`);
   - `python3 scripts/core-status.py --json --latest` (the overlay's copy of the script). Take
     `core.pinned_ref`, `core.latest`, `core.behind`, `summary.pass`, `summary.proved`,
     `summary.fail`, `summary.unverified`, `ui_adoption.status`. A repo without the script:
     `not collected: core-status not installed`. A vendored repo has no overlay: take its line
     from `python3 <core clone>/templates/overlay/scripts/core-status.py --vendored OWNER/REPO --json`
     (`release`, `latest`, `behind`).
   - **A key the pinned script lacks.** An overlay pinned before a key existed (for example
     `summary.proved`, added after some pins) prints no value for it. Fill it by running the core
     clone's copy against the overlay: from the repo,
     `python3 <core clone>/templates/overlay/scripts/core-status.py --json --latest` reads the same
     overlay files and has every current key; copy the core clone's `corehash.py` beside it into a
     scratch folder first if the import fails. When that cannot run, write
     `not collected: key added after the pin` in that cell. Never leave a cell blank and never
     write 0 for a key that was not printed.
4. Fill the table in section a, one row per repo.

## 2. Section b: design inventory per app

For each UI repo, read the code (do not guess from names):

1. **Tokens.** Search the app's CSS and TS for `var(--` and list which core token families it reads
   (colour, space, radius, type, motion, z). List every file that defines a custom property or sets
   the accent, and what it sets. `python3 lint-core/ui_lint.py --json` in the overlay lists UI007,
   UI008, UI009 and UI010 findings: include their counts per rule.
2. **Shell.** Find the root layout component and describe: the grid (columns and rows), the rail
   (width, collapsed state, grouping), the header (search, actions), any status strip, the home or
   hub page, and how a user switches module (routes, tabs, palette).
3. **Parts.** List every UI component the app renders. Source is `kit` when imported from
   `kit-core`, `adapter` when a local component wraps a kit part (name the kit part), `local`
   otherwise. Record the file of each local part.
4. **Interaction.** Command palette (trigger key, what it searches), keyboard shortcuts, toasts
   (placement, duration), dialogs (modal or sheet, focus handling), motion (which duration and
   easing tokens, any literal).
5. **Typography and density.** Font families, the size steps in use, weights, table row height,
   the spacing steps in use.
6. **Light and dark.** How the theme is chosen and stored; any screen that differs between themes
   beyond the token swap.
7. **Screenshots.** Start each app the way its repo documents (its README or `package.json`
   scripts). With whatever browser automation the machine has (a headless browser, Playwright, a
   browser tool of the agent), capture every main screen in light and in dark at one desktop
   width. Scrub each page with `checks/redact_page.js` from a fresh `origin/main` archive of the core
   (read it, never copy it into a consumer). Bring each page to its final state first (route, theme,
   data loaded, panel open), then evaluate the file's text as one expression in that page: with a
   browser tool, pass the file contents to its evaluate call (for example `js(open(path).read())`),
   with Playwright `page.evaluate(text)`. Capture straight after and do not touch the page again, a
   live framework tree would paint real text back. The script does the whole scrub:
   1. **Freeze.** It swaps `document.body` for a static clone, so a re-render cannot reach what the
      capture sees.
   2. **Letters and digits.** Letters become `x` and digits `0` in text nodes, input and textarea
      values, `placeholder`, `title`, `aria-label` and `alt`.
   3. **Blur.** Images, canvases, iframes, video, icons wider than 26 px and every text-bearing
      element.
   4. **Report.** It returns `{count, leftover, cssGenerated}`. Nothing back means it did not run.
   Read the result before each capture. Refuse to capture or post a page while `count` is above 0,
   and run the script again after fixing what `leftover` shows. `cssGenerated` lists stylesheet
   rules that draw text with `attr()` or `counter()`, which no text-node scrub reaches. For each
   one, blank the attribute it reads or add an inline `content: none` to the elements it matches,
   evaluate the script again, and check those spots in the capture by eye. Capture only when
   `count` is 0 and every `cssGenerated` rule was handled.
   Check each image by eye: no name, hostname, plan, count or face. A screen you cannot start or
   capture is `not collected: <reason>`.

## 3. Section c: design diff against the kit

1. Pinned kit: `kit-core/src` in the overlay is the kit at the pinned release. List its parts
   (capitalised exports).
2. One row per kit part and per local part. Compare by reading both sources and, where both render,
   the screenshots: structure, states (hover, focus, disabled, loading, empty, error), density,
   motion, keyboard behaviour, light and dark.
3. Verdict per row: `same`, `local is better`, `core is better`, `missing in core`,
   `missing locally`. A verdict needs a reason you can point to (a state the other lacks, a
   measured spacing, a screenshot); otherwise write `not compared: <reason>`.
4. Each `local is better` or `missing in core` row is a `D` item. Under the table write each item:
   id, title, ready or settling (settling names the open question), evidence (file reference by
   role and relative path, screenshot link, measured ratio), and what changes in the core if it is
   approved (which kit file, token or doc).

## 4. Section d: functionality and adoption risk

1. Per app, list the features (routes, screens, actions) and the parts each uses, from the code.
2. For every `local` and `adapter` part: compare its props and behaviour with the kit part that has
   the same role. Write what would break or change if the local part were replaced: props the kit
   part lacks, events it does not raise, behaviour it does not have, styling that differs. Risk is
   `none`, `low` (visual only), `medium` (behaviour changes, no data loss) or `high` (a feature
   stops working). No kit part with that role: `no kit equivalent`.

## 5. Sections e and f: practice, CI and gaps

1. **Practice and CI.** List each repo's workflows (`.github/workflows/`), required checks, local
   scripts and conventions. A `P` item for each one that does something the core lacks or does
   better, with the evidence it worked (runs, before-and-after ratios). Then each difference from
   a core rule (core-status `fail` and `excepted` rules, exceptions in `standards-local/`) with a
   verdict: which side should change and why.
2. **Gaps.** A `G` item for each place the core's instructions contradicted themselves, asked for
   something this machine cannot do, or left you to guess while producing this report.

## 6. Section g and the draft

1. Section g is the nightly's: copy the current issue's `nightly:changes` block unchanged (both
   markers included). If the issue has none, put the two empty markers in.
2. Keep the `nightly:candidates` block unchanged the same way.
3. Write the full body to `report.md` in the scratch directory, in the template's section order.

## 7. Check, then file

1. From the core clone:
   - `python3 checks/check-sanitised.py --file <scratch>/report.md`
   - `python3 checks/check-consumer-neutral.py --file <scratch>/report.md`
   - plain ASCII: `python3 -c "import sys; d=open(sys.argv[1],'rb').read(); sys.exit(any(b>127 for b in d))" <scratch>/report.md`
   Fix every hit and run all three again. Do not post until all three pass. The checks see only the
   files you pass them: they check the body file, not the issue. Every other text you post (a
   comment, a markdown file moved to the gist) is written to a file and passed through the same
   three checks first.
2. Screenshots. `gh gist create` refuses PNGs ("binary file not supported"), so push them with git
   into a secret gist made from a text file:

   ```bash
   echo "consumer report screenshots" > <scratch>/README.md
   url=$(gh gist create <scratch>/README.md --desc "consumer report screenshots" | tail -1)  # secret by default
   id=${url##*/}; login=$(gh api user --jq .login)
   git clone -q "https://gist.github.com/$id.git" <scratch>/gist
   cp <scratch>/*.png <scratch>/gist/ && git -C <scratch>/gist add -- '*.png'
   git -C <scratch>/gist commit -qm "screenshots" && git -C <scratch>/gist push -q
   curl -sfL -o /dev/null "https://gist.githubusercontent.com/$login/$id/raw/<file>.png" && echo ok
   ```

   Commit with the account's noreply identity if git has none configured. Link each image in
   section b by that raw URL and describe it in one line (screen, theme, what the layout shows).
   The account login in a raw gist URL of an image or a moved `.md` table is the one account name
   allowed in a report: it is the
   login that posts the issue, already public as its author, and both checks accept that URL form
   in file mode while still checking everything else on the line. When the screenshot table would
   push the body over the size budget, post it as a comment on the issue instead (checked the same
   way) and link the comment from section b.
   Check `gh api gists/$id --jq .public` is `false`. Never upload an image you have not checked by
   eye. A gist from an earlier report run that is no longer linked is deleted with
   `gh gist delete <id> --yes`.
3. File:
   - issue open: `gh issue edit <n> -R "$INTAKE" --body-file <scratch>/report.md`;
   - none open: `gh issue create -R "$INTAKE" --label consumer-report --title "consumer report: <role summary>" --body-file <scratch>/report.md`.
4. Verify: `gh issue view <n> -R "$INTAKE" --json body` and confirm both marker pairs are
   present and section a has one row per registered repo.
5. Answer with the issue URL, the item ids added or changed, and every `not collected` line.
