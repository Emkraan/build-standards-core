# Evaluation: the hub's log intake platform (E1 to E7)

Source: the hub's feature inventory (intake issue 117, comment 6607335699, section 3, entries E1 to E7). Status of the evidence: read by the
hub owner against the hub code; one hub pull request (the workspace tab) is still open and red on two checks of its own.

## What the group is

A small ingest platform inside the hub: devices post a JSON envelope to one route per stream with one key per stream; a stream (its
mode, schema, retention, rate limit) is data edited in a tool, not code; the latest snapshot per device is kept in the hub store so
reports work with no cloud workspace; an optional sink forwards rows to a workspace table.

## Entry by entry

| # | Feature | Generic or hub-specific | In the core today | What the core would need |
|---|---|---|---|---|
| E1 | One post route per stream, one ingest key per stream, a stream is data not code | Generic idea, hub-specific build (hub database, hub auth) | Nothing: the core has no ingest route, no per-device key store and no stream registry | A new first-party tool area: an ingest router, a key store (hashed, per stream), a stream registry with a schema, and envelope validation. This is a product, not a standard |
| E2 | Stream settings: mode, editable schema, retention (90 days), per-device hourly post limit with a 429 and a one hour Retry-After | Generic | The rate limit and Retry-After wording is in `web-api-runtime.md` and the app-server package for API calls; no per-stream settings or retention job | The settings store and a retention job, plus the per-device limiter keyed by stream |
| E3 | A workspace table must match one prefix and suffix pattern or the call is refused; deleting a stream needs the table name typed | Generic as a pattern (the prefix is the hub's) | A typed confirmation exists for owner applies (`owner_roots`); no namespace rule for tables | Nothing to build: this is a rule, "a tool touches only objects in its own namespace and a destructive edit needs the name typed", which could be one sentence in `iac-governance.md` or `web-api-runtime.md` |
| E4 | Interim share drop: devices write a file to a share, one relay posts and defers a device at its limit | Hub-specific (a transport the hub built until devices can post directly) | Nothing | Nothing; the 429 path in E2 is the only hub-side part |
| E5 | Reports before a workspace exists: the latest snapshot per device kept in the hub store | Generic | Nothing | The "latest per device" store from E1 |
| E6 | Workspace tab: editable settings, a read-only access test that names the missing role and scope, a marked test row, a forwarding switch | Generic candidate, not merged in the hub yet | Nothing | Wait for the hub to merge it and prove it; the rule "a missing right is reported with the role and scope that would grant it" is worth one sentence in `rbac.md` |
| E7 | A device log folder with a size-capped roll | Hub-only (a device scripting convention) | `cmtrace-logging.md` covers log format and rolling | Nothing |

## Recommendation

Do not build the platform in the core. It is a product with its own data, auth, retention and cost, and the core is standards, checks,
a kit and an ops center. Two of its ideas are standards and cost almost nothing: the namespace-and-typed-confirmation rule (E3) and the
"report the missing role and scope" rule (E6). The rest stays a hub feature until a second consumer needs the same ingest; at that
point it would be its own app in the first-party family.

## Decisions for the owner

1. Do the two rules (E3, E6) go into the standards now, as text with a consumer test each? Recommended: yes.
2. Is a log intake platform a first-party app the family should own, or does each tool keep its own? Recommended: wait for a second consumer.
3. Is the hub's interim share relay (E4) to be retired when devices post directly? If so nothing is needed from the core.
