# Ops center items not lifted, and the optional module contract

The hub log intake and hub reports plans were retired by owner decision on 2026-11-10 (the hub no longer consumes the core). The log intake
and reports modules that were already built stay, optional and never mandatory; plan items that were not built were dropped. The one note
left here records the ops center and shell items the core did not lift and what each needs.

| Note | Group | Entries |
|---|---|---|
| [inventory-items-not-lifted.md](inventory-items-not-lifted.md) | Ops center and shell items the core did not lift, and why | OC-7, OC-10, OC-18, OC-20, OC-22, SH-24, SH-25, SH-26, SH-31 |

## The opt-in contract (both built modules)

1. **Off by default and absent when off.** A module registers nothing until a consumer turns it on with one setting: no routes, no
   background task, no table or file created, no import at startup, no navigation entry, no bytes in the client bundle (the kit side
   is a separate entry point a consumer imports or does not).
2. **Slots, not estates.** Every integration (a directory, a workspace sink, a catalog, a time zone) is a provider slot with a null
   default, like the other ops center slots. Nothing names an estate.
3. **A consumer pays only for what it enables.** Enabling log intake does not enable reports, and the reverse, except that reports
   read streams: a consumer with reports and no log intake supplies its own stream source through the data-source slot.
4. **Tests prove the off state.** Each module has a test that, with the setting absent, the route table, the background task list and
   the file system are exactly what they were without the module.
