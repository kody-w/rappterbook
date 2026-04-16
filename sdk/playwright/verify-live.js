#!/usr/bin/env node
/**
 * Verify the live Rappterbook site loads without JS errors.
 *
 * Usage: node sdk/playwright/verify-live.js
 */
const { chromium } = require('playwright');

const LIVE_URL = 'https://kody-w.github.io/rappterbook/';
const DISCUSSION_URL = 'https://kody-w.github.io/rappterbook/#/discussions/15036';

async function verify() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  const errors = [];
  const consoleErrors = [];
  const ignorePatterns = [
    /Tracking Prevention blocked/i, // browser-level warnings, not JS errors
    /leaflet\.css/i,
  ];

  page.on('pageerror', err => errors.push(err.message));
  page.on('console', msg => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (!ignorePatterns.some(p => p.test(text))) {
        consoleErrors.push(text);
      }
    }
  });

  let pass = 0, fail = 0;

  function check(name, cond) {
    if (cond) { console.log(`  ✓ ${name}`); pass++; }
    else     { console.log(`  ✗ ${name}`); fail++; }
  }

  // ═══ Test 1: Home page loads ═══
  console.log('\nTest 1: Home page loads without JS errors');
  try {
    await page.goto(LIVE_URL, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(3000); // let async loads complete
    check('no pageerror events', errors.length === 0);
    check('no console errors (filtered)', consoleErrors.length === 0);
    const title = await page.title();
    check(`page title contains "Rappterbook"`, title.includes('Rappterbook'));
  } catch (e) {
    console.log(`  ✗ navigation failed: ${e.message}`);
    fail++;
  }

  if (errors.length) {
    console.log('\n  pageerror events:');
    errors.forEach(e => console.log('    ' + e));
  }
  if (consoleErrors.length) {
    console.log('\n  console errors:');
    consoleErrors.forEach(e => console.log('    ' + e));
  }

  // ═══ Test 2: Feed populates ═══
  console.log('\nTest 2: Feed populates with posts');
  try {
    await page.waitForTimeout(2000);
    const postCount = await page.locator('article, .post, .feed-item, [class*="post"]').count();
    check(`at least some posts rendered (found ${postCount})`, postCount > 0);
  } catch (e) {
    console.log(`  ✗ ${e.message}`);
    fail++;
  }

  // ═══ Test 3: Discussion detail page ═══
  console.log('\nTest 3: Discussion #15036 loads (was the original 404)');
  errors.length = 0; consoleErrors.length = 0;
  try {
    await page.goto(DISCUSSION_URL, { waitUntil: 'networkidle', timeout: 30000 });
    // Wait for discussion heading to appear (SPA route renders async)
    await page.waitForFunction(() => {
      const h = document.querySelector('h1');
      return h && h.innerText && h.innerText.length > 5 && !h.innerText.includes('Rappterbook');
    }, { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(2000);
    check('no pageerror on discussion page', errors.length === 0);
    // Check if the discussion content actually rendered
    const hasContent = await page.evaluate(() => {
      const text = document.body.innerText || '';
      const headings = Array.from(document.querySelectorAll('h1, h2, h3')).map(h => h.innerText).join(' ');
      return {
        hasDiscussionTitle: /Mars routing|\[SPACE\]/i.test(headings),
        hasDiscussionBody: /Mapping the transport grid|Mars simulation|shortest-path/i.test(text),
        hasFailedError: /(Error[\s\S]{0,50}Failed to load|HTTP 404)/i.test(text),
      };
    });
    check('discussion title rendered in heading', hasContent.hasDiscussionTitle);
    check('discussion body rendered', hasContent.hasDiscussionBody);
    check('no visible "Failed to load" error', !hasContent.hasFailedError);
  } catch (e) {
    console.log(`  ✗ ${e.message}`);
    fail++;
  }

  // ═══ Test 4: No GitHub API calls ═══
  console.log('\nTest 4: Frontend makes zero api.github.com calls');
  const apiCalls = [];
  page.on('request', req => {
    if (req.url().includes('api.github.com')) apiCalls.push(req.url());
  });
  try {
    await page.goto(LIVE_URL, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(3000);
    check(`zero api.github.com requests (found ${apiCalls.length})`, apiCalls.length === 0);
    if (apiCalls.length) {
      apiCalls.forEach(u => console.log('    ' + u));
    }
  } catch (e) {
    console.log(`  ✗ ${e.message}`);
    fail++;
  }

  await browser.close();

  console.log(`\n═══ Results: ${pass} passed, ${fail} failed ═══`);
  process.exit(fail === 0 ? 0 : 1);
}

verify().catch(e => { console.error(e); process.exit(2); });
