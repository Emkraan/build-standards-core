# Chat Message Standard

Version: 1.0 | Last reviewed: 2026-10-08 | Status: current | Scope: all

Every chat message that reaches the owner follows this standard. The shared formatter is
`<agent-home>/scripts/tgfmt.py` (stdlib only, importable, with a CLI for shell wrappers). Scheduled
scripts are wrapped by `tgfmt_guard.py`. Do not hand-write chat text in a script.

## 1. Principles

- Pure signal. Send only failures and things that need action. Silent when clear.
- Plain language. Say what stopped working for the owner and what it affects. No job, scheduler,
  daemon or LaunchAgent names in the headline.
- First person where the message speaks for the owner. No AI or tool attribution.
- No PHI, patient identifiers, credentials, or meeting content beyond a one-line signal.
- Draft only. The standard changes how alerts look, never what is sent to other people.

## 2. Format

HTML parse mode. HTML and MarkdownV2 render identically in chat; HTML needs only `<`, `>` and
`&` escaped, MarkdownV2 needs 18 characters escaped and rejects the whole message on a miss.
Never use em or en dashes, curly quotes or other banned characters in message text; the formatter
strips them.

## 3. Layout

1. Severity icon and bold headline (what stopped, in plain words).
2. Italic time line (source name only when it adds signal).
3. One plain sentence on the impact.
4. Arrow line, bold: the next step. Omit when none.
5. Collapsed (expandable) quote with facts (job, exit code) and a log excerpt. The excerpt is the
   last 12 lines, at most 1200 characters, with a pointer to the full log path.
6. Optional URL buttons, read only (open a page or log). Never a button that changes anything.

Messages are capped at 4096 characters; the formatter truncates and closes open blocks.

## 4. Severity

| Level | Icon (code point) | Sound | Use |
|---|---|---|---|
| critical | U+1F6A8 | yes | Automation or access is down and did not self-heal |
| failure | U+274C | yes | A job failed and needs a look |
| warning | U+26A0 U+FE0F | silent | Degrading, not yet broken |
| recovered | U+2705 | silent | Only after an earlier alert for the same key |
| info | U+2139 U+FE0F | silent | Rare, only when it carries signal |

## 5. Dedupe and recovery

State lives in `<agent-home>/state/tgfmt-state.json`, keyed per source. The same severity for the same
key is suppressed for 15 min (critical), 1 h (failure) or 6 h (warning, info). A recovered message
is sent only if an alert was open for the key; otherwise it is dropped.

## 6. Delivery and fallback

Direct Bot API send to the owner's chat only. The bot token is read at runtime from the environment
or `<agent-home>/.env` and never printed. Send order: rich with buttons, rich, plain text. A delivery
failure never raises into the calling job.

## 7. Scheduled jobs

`tgfmt_guard.py --title T --key K -- <command>` runs the job. On success the output passes through
and a recovered alert goes out if one was open. On failure the output is written to
`<agent-home>/logs/guard/K.log`, one formatted alert is sent, and the exit code is preserved so the job
still shows failed. Set `failure_deliver` to `local` on guarded jobs so the plain failure notice is
not sent twice.

## 8. Testing

`python3 -m unittest tests/test_tgfmt.py tests/test_tgfmt_guard.py` in `<agent-home>/scripts`.
`tgfmt.py --samples --dry-run` prints the review set; without `--dry-run` it sends the set to
the owner only.

**Author:** the owner
**Scope:** the owning team

## 9. Email

Chat is not the only channel. Every email a tool sends goes through one block renderer: header,
heading, text, detail row, highlight, button, divider, spacer and footer.

- **Layout.** A fixed-width card. Detail rows sit together in one bordered card. A status callout
  is a tinted fill with a full hairline border and a dot, never an edge bar. One accent-coloured
  primary button.
- **Subject** names the change and the item. A list is capped at 12 with an "and N more" row.
- **Links** use the public hostname, never the platform host.
- **Self-tests** go only to the sender, with a `[TEST]` subject prefix.
- **CI guard.** A check fails the build on hand-built email HTML (markup outside the renderer) and
  on a link to a platform host. **Acceptance (test):** a fixture with a raw `<table>` in an email
  module and one with a platform-host link each fail the guard.
