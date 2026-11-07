# Plans for optional modules and items not lifted

One note per group of consumer features. The owner decided that the hub's tool features (the log intake platform and the dashboards
and reports) are built into the core as optional modules: never mandatory, and a consumer that does not use them never loads, pays
for or sees them. The first two notes are the build plan for those modules, server side here and client side with the kit; the third
records the ops center and shell items the core did not lift and what each needs.

| Note | Group | Entries |
|---|---|---|
| [hub-log-intake-plan.md](hub-log-intake-plan.md) | Optional log intake module: streams as data, ingest, retention, local snapshot store, workspace sink | E1 to E7 |
| [hub-reports-plan.md](hub-reports-plan.md) | Optional reports module: dashboards, definitions as data, data-source layer, exports, directory lookups, roles | R1 to R9, P1 to P4, U1, U2 |
| [inventory-items-not-lifted.md](inventory-items-not-lifted.md) | Ops center and shell items the core did not lift, and why | OC-7, OC-10, OC-18, OC-20, OC-22, SH-24, SH-25, SH-26, SH-31 |

## The opt-in contract (both modules)

1. **Off by default and absent when off.** A module registers nothing until a consumer turns it on with one setting: no routes, no
   background task, no table or file created, no import at startup, no navigation entry, no bytes in the client bundle (the kit side
   is a separate entry point a consumer imports or does not).
2. **Slots, not estates.** Every integration (a directory, a workspace sink, a catalog, a time zone) is a provider slot with a null
   default, like the other ops center slots. Nothing names an estate.
3. **A consumer pays only for what it enables.** Enabling log intake does not enable reports, and the reverse, except that reports
   read streams: a consumer with reports and no log intake supplies its own stream source through the data-source slot.
4. **Tests prove the off state.** Each module has a test that, with the setting absent, the route table, the background task list and
   the file system are exactly what they were without the module.
5. **Nothing is built from prose alone.** The hub's source is not in the core. Parts fully specified by the hub's text and its named
   tests are built first; every other part waits for the source and is marked "needs source" below.
