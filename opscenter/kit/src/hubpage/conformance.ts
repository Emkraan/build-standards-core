/* Conformance of a hub page, as a pure function over a DOM subtree, so an app's own test (jsdom or a
   real browser) can assert the hub rules without a second copy of them. Each finding is one plain
   sentence. An empty list means the page conforms. */

export interface HubPageExpectation {
  /** The rail label of the hub the page belongs to. The page title must equal it. */
  railLabel: string;
}

/** Findings for the hub header inside `root`. */
export function hubPageViolations(root: ParentNode, expect: HubPageExpectation): string[] {
  const found: string[] = [];
  const heads = Array.from(root.querySelectorAll('.hp-head'));
  if (heads.length !== 1) {
    found.push(`expected one hub header, found ${heads.length}`);
    return found;
  }
  const head = heads[0] as Element;
  const titles = Array.from(root.querySelectorAll('h1'));
  if (titles.length !== 1) found.push(`expected one h1 on the page, found ${titles.length}`);
  const title = head.querySelector('.hp-head-title')?.textContent?.trim() ?? '';
  if (title !== expect.railLabel) found.push(`title "${title}" is not the rail label "${expect.railLabel}"`);
  if (!(head.querySelector('.hp-head-sub')?.textContent ?? '').trim()) found.push('the header has no subtitle');
  if (!head.getAttribute('data-hub')) found.push('the header has no hub accent key');
  const tablists = head.querySelectorAll('[role="tablist"]').length;
  if (tablists > 1) found.push(`the header holds ${tablists} tab rows, a hub has one`);
  const segmented = head.querySelectorAll('.hp-seg').length;
  if (segmented > 1) found.push(`the header holds ${segmented} segmented switches, a hub has at most one`);
  if (head.querySelector('.hp-seg .hp-seg, .hp-seg [role="tablist"]')) found.push('a switch is nested inside a switch, a third level is a filter menu');
  for (const el of Array.from(root.querySelectorAll('.hp-section-title'))) {
    const text = el.textContent?.trim() ?? '';
    if (text.length > 3 && text === text.toUpperCase() && /[A-Z]/.test(text)) found.push(`section title "${text}" is upper case, headings are title case`);
  }
  return found;
}
