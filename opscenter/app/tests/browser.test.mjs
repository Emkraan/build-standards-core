// The four browser test files in ONE process, so they share ONE headless browser (tests/sharedBrowser.mjs): `npm run test:browser` runs this file.
// Each file also runs alone (node --test tests/axe.test.mjs) and then launches its own single instance.
import './axe.test.mjs'
import './liveActions.test.mjs'
import './ocTabs.test.mjs'
import './renderedTables.test.mjs'
