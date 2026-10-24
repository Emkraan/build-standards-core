# Live Actions Standard

Version: 1.1 | Last reviewed: 2026-10-13 | Status: current | Scope: web (operator UIs, local tools)

How an operator UI performs actions (merge, approve, move, close, resolve) against backends that
are eventually consistent. The promise to the operator is simple: an action that succeeded makes
its object disappear at once and it stays gone. An action that failed says so, and an object only
comes back when the backend really disagrees. This doc is the source of truth. Where a reference
implementation differs, the implementation is fixed, or the consumer records an explicit exception
(README, "Source of truth and explicit exceptions").

Related: [Automation Safety](automation-safety.md) (re-verify before acting, idempotent retries),
[PR Review and Merge](pr-review-and-merge.md#4-holds-and-the-merge-button) (which rows get which
button), [Local Ops App](local-ops-app.md) (TTL caches, loopback server), [Web Design System](web-ui.md)
(toasts, undo, dialogs).

---

## 1. Rules

1. **Success removes the object at once, everywhere.** When the action endpoint returns success, the client removes the object from the shared store that every list, tab and badge reads, and shows a success flash. It does not refetch the list to decide what to show.
   - Prevents: the row the operator just merged still sitting on screen, and a sidebar badge that disagrees with the page.
   - Acceptance (test): a UI test resolves the action and asserts the row and its badge count are gone before any refetch.
2. **A server-side tombstone keeps it gone.** On success the server records a tombstone keyed by object and version (for example `pr:<repo>#<n>@<head sha>`) with the action, the expected end state and a TTL. Every list endpoint hides a tombstoned object until a read shows the expected state or the TTL passes.
   - Prevents: the object coming back on the next poll, after a reload or in another tab while the backend's list still shows the old state.
   - Acceptance (test): with a fake backend whose list keeps returning the old state, every list and count endpoint omits the object until the fake reports the end state.
3. **A tombstone that expires unconfirmed resurfaces the object, flagged.** When the TTL passes and the backend still shows the old state, the object returns with a note that the last action did not land, and the event is logged.
   - Prevents: a tombstone that hides a real failure forever.
   - Acceptance (test): advance the clock past the TTL with the fake still on the old state and assert the object returns with the flag.
4. **Every write invalidates every cache that holds the object.** The action handler clears the cached list, count and detail entries that include the object before it responds.
   - Prevents: a TTL cache serving the pre-action list for its whole lifetime.
   - Acceptance (test): after a successful action, the next GET of each affected endpoint misses the cache.
5. **"Already done" is an idempotent success.** When the backend answers already merged, already closed, already in that sprint, already in that status or gone after a delete, the server confirms with a direct read and returns success with `already: true`, records the tombstone and shows no error.
   - Prevents: a double click, a retry or a second tab producing a failure toast for work that is done.
   - Acceptance (test): replay each action against a fake in the end state and assert success with `already: true`.
6. **Confirm through the direct read, never the search or list API.** Verification after an action reads the object itself (a pull request by number, an issue by key). Search and list endpoints lag direct reads by seconds to minutes and are used only to build lists.
   - Prevents: deciding an action failed, or showing the object again, because a lagging index had not caught up.
   - Acceptance (review): the action handler and the tombstone check call only direct-read endpoints (section 5).
7. **Actions carry the version the operator saw.** The request names the object and the version on screen, the server re-reads live state, and a moved version returns 409 "Refresh first" with no write.
   - Prevents: an action applied to a state the operator never saw, such as a merge of commits pushed after the review.
   - Acceptance (test): tests change the live version between render and click and assert 409 and no write.
8. **In-flight polls never resurrect.** A poll response from a request that started before the latest successful write is dropped, or it passes through the same tombstone filter as the server.
   - Prevents: a poll that left before the click landing after it and putting the row back.
   - Acceptance (test): a test resolves a slow poll after the action and asserts the row stays gone.
9. **Asynchronous acceptance is a pending state, not a removal.** When the backend accepts the action for later (a merge queue, auto-merge, a dispatched workflow), the row moves to an in-flight state with a live indicator and no actions, and it disappears when a direct read shows the end state.
   - Prevents: a row removed for a merge that the queue later rejects, and a second click on work in flight.
   - Acceptance (test): a queued result renders the pending state, and the end state removes it.
10. **Badges and counts read the same filtered source as the page.** Every badge counts from the store the page treats as authority, after tombstones and the page's own filters.
    - Prevents: a badge that says 3 while the page shows 2.
    - Acceptance (test): page and badge counts agree in tests that add, act on and tombstone items.
11. **Actionable means the action would go through now.** The server decides, per object, a phase (`needs_action`, `in_flight` or done) from the same preconditions its action handler checks, read live (version on the source of truth, run still waiting, nothing running under the operation lock). The client renders action buttons only for `needs_action` and never derives actionability from a raw status field. A disabled button with a tooltip is not a substitute: the object moves to a locked in-flight list with the reason.
    - Prevents: a card that offers Apply or Approve and then answers 409 because the base moved, the run was already decided elsewhere or a plan is being redone.
    - Acceptance (test): for each precondition the handler enforces, a fixture that breaks it renders the object without buttons and outside the needs-action count.
12. **Upstream drift redoes the work by itself.** When a precondition is invalidated upstream (the base branch moved past a saved plan, a run started a new attempt), the server starts the refresh on its own, once per new upstream version, and the object stays in flight with a live indicator until the fresh result lands. It never waits for the operator to press Refresh or Re-plan.
    - Prevents: the operator being told "moved since this plan, re-plan first" for work the tool could have redone unprompted.
    - Acceptance (test): advance the fake upstream version and assert exactly one refresh starts and the object returns to `needs_action` (or leaves) when it completes.
13. **Every needs-action object carries a way forward.** An object counted as needing the operator has at least one action that moves it (act, reject, discuss, dismiss). An object nothing can act on is either in flight or not shown, and an object that turns out not to apply (for example a record whose trigger never happens) is dropped.
    - Prevents: an alarm card with no buttons that sits on the board forever.
    - Acceptance (test): every needs-action fixture renders at least one enabled action.
14. **Unknown never hides.** When the live read behind rule 11 fails or times out, the object shows as actionable and the handler's own re-verification (rule 7) is the safety net. Live reads are cached briefly and refreshed in the background so a list request never waits on them after the first read.
    - Prevents: an outage of the live read silently emptying the operator's queue, and slow pages from a live read on every request.
    - Acceptance (test): a failing live-read fake leaves the object in `needs_action`, and a warm list request makes no blocking backend call.

## 2. The failure this prevents

1. The operator clicks Approve and merge. The server merges and gets success.
2. The client refetches the list. The list endpoint serves its cached copy, or the cache was cleared
   but the backend list still says open, because list and search reads trail the direct read.
3. The row reappears. The poller keeps it there and the badge still counts it.
4. The operator clicks again. The backend says "already merged" and the UI shows an error.

Each step is fixed by one rule: the client removes the row (rule 1), the server hides it until the
backend agrees (rule 2), the cache is cleared (rule 4), the second click is a success (rule 5) and
the check reads the pull request directly (rule 6).

## 3. The action protocol

Client:

1. Send `{object, version, action, ...}`. Disable the button and show a working indicator.
2. On success (including `already: true`), call the store's `mutate()` to drop the object, bump the
   store's write generation, and flash the result.
3. On 409, show "Refresh first" and refetch. On any other error, keep the row, show the error and
   re-enable the button.

Server:

1. Re-read the object directly. Refuse 409 if the version moved or the object is no longer in a
   state the action applies to.
2. Perform the action, pinned to the version (for a merge, the head sha).
3. If the backend reports the work is already done, or the call errors, read the object directly.
   End state reached at the expected version: success with `already: true`. End state reached at a
   different version (someone else merged another head): a distinct result naming that version.
   Otherwise: the error.
4. If the backend queued the action: success with `pending: true`.
5. Record the tombstone, invalidate the caches, log the decision, respond with the direct-read state.

## 4. The tombstone store

```json
{
  "pr:example/repo#42@3f9c2e1": {
    "action": "merge",
    "expect": "merged",
    "at": "2026-10-13T14:02:11Z",
    "ttl_s": 600,
    "pending": false
  }
}
```

- Key: object kind, id and version. A tombstone for one version never hides a different version,
  so a new push or a later edit shows normally.
- Store it server-side with atomic writes so it survives a reload, another browser and a server
  restart. Prune entries that are confirmed or expired.
- Each list read applies the filter: hide when a live tombstone matches and the backend row still
  shows the pre-action state. Drop the tombstone when a read shows the expected state.
- TTL is a parameter (default 10 minutes), long enough to outlast the slowest index the backend
  uses and short enough that a failed action resurfaces the same session.

## 5. Direct reads versus lagging reads

| Backend | Lagging read (lists only) | Direct read (verification) |
|---|---|---|
| GitHub pull requests | `gh pr list`, `gh search prs`, the search API | `gh pr view <n> --json state,mergedAt,headRefOid`, REST `GET /repos/{owner}/{repo}/pulls/{n}` |
| Jira issues | JQL search | `GET /rest/api/3/issue/{key}` |
| Tenant and directory settings | Bulk list and report endpoints | Read the object with the same client the workload uses, repeated until stable (propagation flaps) |

The lag is observed in practice as seconds to minutes. It varies, so code never sleeps a fixed time
and re-lists. It either trusts the direct read or the tombstone.

## 6. Tests

- Fake backend whose list stays stale while the direct read shows the end state: the object stays
  hidden on every endpoint and every poll.
- Fake backend that never reaches the end state: the object returns after the TTL with the flag.
- Double click and second tab: one effect, two successes.
- Slow poll resolving after the action: no resurrection.
- Moved version between render and click: 409, no write.
- Queued acceptance: pending state, then removal on the end state.
- Badge equals page count through all of the above.
- Each handler precondition broken in a fixture: no buttons, not counted, reason shown.
- Upstream version advanced: one automatic refresh, then the object returns or leaves.
- Live read failing: object stays actionable, handler still refuses a moved version.

Run these against synthetic objects on a scratch server. Never prove an action on a real item
([Automation Safety rule 3](automation-safety.md#1-rules)).

## 7. Checklist

- [ ] Success drops the object from the shared store, including badges, with no refetch.
- [ ] Server tombstone keyed by object and version, persisted, filtered on every list.
- [ ] Unconfirmed tombstones expire and resurface the object with a flag.
- [ ] Every write clears every cache that holds the object.
- [ ] "Already done" confirmed by a direct read and returned as success.
- [ ] Verification reads the object directly, never a search or list endpoint.
- [ ] Requests carry the version on screen, 409 on a moved version.
- [ ] Stale polls dropped or filtered.
- [ ] Queued actions show a pending state with no buttons.
- [ ] Badges count from the same filtered source as the page.
- [ ] Buttons render only for objects the server marks `needs_action` from live preconditions.
- [ ] Upstream drift starts the refresh automatically, once per new version.
- [ ] Every needs-action object has at least one enabled action.
- [ ] A failed live read shows the object, it never hides it.
