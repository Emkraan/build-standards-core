/*
 * Redact the current page for a screenshot that leaves the machine (an issue, a pull request, a comment).
 * Evaluate it only AFTER the page is in its final state (route, theme, data loaded, panel open), capture
 * straight after, and never interact with the page again before the shot: a live framework tree re-renders
 * from state and would paint real text back. It swaps the body for a static clone, so the app keeps
 * rendering into the detached original and never into what the capture sees.
 *
 * Returns {count, leftover, cssGenerated}:
 *   count         text nodes that still hold a real letter or digit. Must be 0, else do not post the capture.
 *   leftover      up to 5 truncated samples of those nodes.
 *   cssGenerated  up to 12 stylesheet rules that draw text with attr() or counter(). No text-node scrub
 *                 reaches them, so the list must be empty or those spots get checked by eye.
 * Getting nothing back means the script did not run.
 *
 * Load it with whatever drives the page: read this file and evaluate its text as one expression in the page
 * (a browser tool's evaluate call, Playwright page.evaluate, a devtools console paste).
 * Covered by kit/tests/redact-page.test.ts.
 */
(() => {
  const cssGenerated = []
  const walkRules = list => {
    for (const rule of list) {
      if (rule.cssRules) walkRules(rule.cssRules)
      if (rule.style && rule.style.content && /attr\(|counter\(/.test(rule.style.content)) {
        cssGenerated.push(rule.selectorText + ' => ' + rule.style.content)
      }
    }
  }
  for (const sheet of document.styleSheets) {
    let rules = null
    try { rules = sheet.cssRules } catch (e) { rules = null }
    if (rules) walkRules(rules)
  }

  /* Freeze first: the app keeps rendering into the detached original body, never into this static clone.
     A cloned canvas has no bitmap (charts come out blank) and a cloned iframe reloads, so both get blurred. */
  const frozen = document.body.cloneNode(true)
  document.body.parentNode.replaceChild(frozen, document.body)

  const scrub = s => s.replace(/\p{L}/gu, 'x').replace(/\p{N}/gu, '0')
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  const textNodes = []
  while (walker.nextNode()) textNodes.push(walker.currentNode)
  for (const node of textNodes) {
    if (node.nodeValue.trim()) node.nodeValue = scrub(node.nodeValue)
  }
  document.querySelectorAll('input, textarea').forEach(el => {
    el.value = scrub(el.getAttribute('value') || '')
    if (el.placeholder) el.placeholder = scrub(el.placeholder)
  })
  document.querySelectorAll('[title], [aria-label], [alt]').forEach(el => {
    for (const name of ['title', 'aria-label', 'alt']) {
      if (el.hasAttribute(name)) el.setAttribute(name, scrub(el.getAttribute(name)))
    }
  })

  const style = document.createElement('style')
  style.textContent = 'img, canvas, video, picture, iframe { filter: blur(8px) !important }'
  document.head.appendChild(style)
  document.querySelectorAll('svg').forEach(svg => {
    const box = svg.getBoundingClientRect()
    if (box.width > 26 || box.height > 26) svg.style.setProperty('filter', 'blur(6px)', 'important')
  })
  document.querySelectorAll('body *').forEach(el => {
    for (const child of el.childNodes) {
      if (child.nodeType === 3 && child.nodeValue.trim()) {
        el.style.setProperty('filter', 'blur(3.5px)', 'important')
        break
      }
    }
    if ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') && el.placeholder) {
      el.style.setProperty('filter', 'blur(3.5px)', 'important')
    }
  })

  const leftover = []
  const check = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  while (check.nextNode()) {
    const rest = check.currentNode.nodeValue.replace(/[x0]/g, '')
    if (/[\p{L}\p{N}]/u.test(rest)) leftover.push(check.currentNode.nodeValue.slice(0, 40))
  }
  return { count: leftover.length, leftover: leftover.slice(0, 5), cssGenerated: cssGenerated.slice(0, 12) }
})()
