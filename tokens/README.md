# Tokens

One source, every output. `tokens.json` is the only file a person edits. `build.py` (Python standard
library, no install) generates everything else and certifies the colour contrast.

| File | What it is | Edit? |
|---|---|---|
| `tokens.json` | The source: groups of tokens with `$type`, `$value`, `$light` (light-mode value when it differs), `$description`, plus the named accents and the contrast rules | Yes, by pull request |
| `build.py` | Generator and certifier | Yes, by pull request |
| `tokens.css` | CSS custom properties for every mode block and every named accent | Generated |
| `tokens.ts` | Resolved values for code outside the DOM (tests, canvas, charts) | Generated |
| `tailwind.preset.cjs` | The same tokens as a Tailwind preset | Generated |
| `wpf/Tokens.Dark.xaml`, `wpf/Tokens.Light.xaml` | WPF resource dictionaries | Generated |
| `CONTRAST.md` | Every certified ratio, both modes, plus a summary per named accent | Generated |
| `hub-layer.css` | The behavioural recipes (tone, selection, stat tile, rail, palette, build card) on top of the tokens. Defines no tokens | Yes, by pull request |

## Build

```bash
python3 tokens/build.py           # regenerate every output after editing tokens.json
python3 tokens/build.py --check   # what CI runs: fails on a stale output or a failed contrast rule
```

Commit `tokens.json` and the regenerated outputs together. CI fails the pull request if they differ.

## Modes

Dark is the base. Light is a token swap with the same names, so no component branches on theme.
`<html data-theme="light">` or `"dark"` is an explicit choice, no attribute follows the OS, and print
is always light. The generator writes the OS block, both explicit blocks and the print block from one
declaration, so they cannot drift (they had drifted while hand-maintained).

## Accents

An app sets one accent on the root: `<html data-app-accent="violet">`. No attribute is the default
(cobalt). Named accents: cobalt, blue, indigo, violet, fuchsia, rose, red, orange, hub, amber, gold,
green, teal, cyan.

Each named accent is generated from a seed colour: a nine-step ramp in the seed's hue on a shared
lightness and chroma profile, then nudged until it certifies in both modes. White on the fill, the
hover and both gradient stops clears 4.5:1, the accent text ink clears 4.5:1 on every content surface
and on the accent chip, and the focus ring clears 3:1 on every surface. The seed itself stays
available as `--accent-seed` for identity marks only.

When an accent sits within 30 degrees of hue of a categorical hue, `--accent-withheld-hue` names that
hue and apps drop it from data series (the kit palette helper does this), so brand and data never
share a colour.

A brand colour that is not on the list:

```bash
python3 tokens-core/build.py --accent brand=#RRGGBB   # in an overlay: prints a certified block
python3 tokens-core/build.py --wpf-accent violet --mode light   # a WPF dictionary for an accent
```

Inside an overlay the synced copy is read-only. `build.py` refuses to rewrite it and only offers
`--check`, `--accent` and `--wpf-accent`.

## Load order in an app

`tokens.css`, then `hub-layer.css`, then the kit stylesheet. Never edit the synced copies: change
them here by pull request.

## Layer order

`layers.css` declares `@layer base, core;` and nothing else. Import it first, before `tokens.css`
and the kit stylesheet, so an app's element defaults (in `base`) sit below the core and unlayered
app CSS still wins over both. Do not redeclare the order in an app.
