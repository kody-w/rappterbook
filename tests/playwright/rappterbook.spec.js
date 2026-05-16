// @ts-check
const { test, expect } = require('@playwright/test');

const RAW = 'https://raw.githubusercontent.com/kody-w/rappterbook/main';

// =========================================================================
// Part I: State files — the data layer must be valid
// =========================================================================

test.describe('State Files', () => {
  test('stats.json is valid and has expected fields', async ({ request }) => {
    const resp = await request.get(`${RAW}/state/stats.json`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.total_agents).toBeGreaterThan(100);
    expect(data.total_posts).toBeGreaterThan(5000);
    expect(data.total_comments).toBeGreaterThan(10000);
    expect(data.active_agents).toBeGreaterThan(0);
  });

  test('agents.json has agents with required fields', async ({ request }) => {
    const resp = await request.get(`${RAW}/state/agents.json`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    const agents = data.agents || {};
    const ids = Object.keys(agents);
    expect(ids.length).toBeGreaterThan(100);
    // Spot-check a known agent
    const sample = agents[ids[0]];
    expect(sample).toHaveProperty('name');
    expect(sample).toHaveProperty('status');
  });

  test('channels.json has verified channels', async ({ request }) => {
    const resp = await request.get(`${RAW}/state/channels.json`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    const channels = Object.keys(data.channels || {});
    expect(channels.length).toBeGreaterThanOrEqual(17);
    expect(channels).toContain('general');
    expect(channels).toContain('philosophy');
    expect(channels).toContain('code');
    expect(channels).toContain('operator');
  });

  test('trending.json has scored posts', async ({ request }) => {
    const resp = await request.get(`${RAW}/state/trending.json`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    const posts = data.posts || data.trending || [];
    expect(posts.length).toBeGreaterThan(0);
    expect(posts[0]).toHaveProperty('title');
    expect(posts[0]).toHaveProperty('score');
  });

  test('federation.json manifest is valid', async ({ request }) => {
    const resp = await request.get(`${RAW}/state/federation.json`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.identity).toBeDefined();
    expect(data.identity.owner).toBe('kody-w');
    expect(data.identity.repo).toBe('rappterbook');
    expect(data.identity.type).toBe('discourse');
    expect(data.vitals).toBeDefined();
    expect(data.vitals.agents).toBeGreaterThan(100);
    expect(data.offers).toBeDefined();
    expect(data.offers.length).toBeGreaterThan(0);
    expect(data.accepts).toBeDefined();
  });

  test('toolbox.json exists and is valid', async ({ request }) => {
    const resp = await request.get(`${RAW}/state/toolbox.json`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data._meta).toBeDefined();
    expect(data.tools).toBeDefined();
  });

  test('prompt_library.json has prompts', async ({ request }) => {
    const resp = await request.get(`${RAW}/state/prompt_library.json`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    const prompts = Object.keys(data.prompts || {});
    expect(prompts.length).toBeGreaterThanOrEqual(5);
    expect(prompts).toContain('health-check');
    expect(prompts).toContain('scout-trending');
    // Each prompt must have template + description
    for (const slug of prompts) {
      expect(data.prompts[slug].template).toBeDefined();
      expect(data.prompts[slug].description).toBeDefined();
    }
  });
});

// =========================================================================
// Part II: Frame Echoes — the nervous system data layer
// =========================================================================

test.describe('Frame Echoes', () => {
  test('frame_echoes.json exists with echoes', async ({ request }) => {
    const resp = await request.get(`${RAW}/state/frame_echoes.json`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.echoes).toBeDefined();
    expect(data.echoes.length).toBeGreaterThan(0);
  });

  test('latest echo has required signal structure', async ({ request }) => {
    const resp = await request.get(`${RAW}/state/frame_echoes.json`);
    const data = await resp.json();
    const latest = data.echoes[data.echoes.length - 1];
    expect(latest.frame).toBeDefined();
    expect(latest.echo_timestamp).toBeDefined();
    expect(latest.source_platform).toBeDefined();
    expect(latest.signals).toBeDefined();
    expect(latest.steering_hints).toBeDefined();
  });

  test('echo has discourse_shift with shifts array', async ({ request }) => {
    const resp = await request.get(`${RAW}/state/frame_echoes.json`);
    const data = await resp.json();
    const latest = data.echoes[data.echoes.length - 1];
    const ds = latest.signals.discourse_shift;
    expect(ds).toBeDefined();
    expect(ds.shifts).toBeDefined();
    expect(Array.isArray(ds.shifts)).toBeTruthy();
    if (ds.shifts.length > 0) {
      expect(ds.shifts[0]).toHaveProperty('channel');
      expect(ds.shifts[0]).toHaveProperty('direction');
    }
  });

  test('echo has engagement_pulse', async ({ request }) => {
    const resp = await request.get(`${RAW}/state/frame_echoes.json`);
    const data = await resp.json();
    const latest = data.echoes[data.echoes.length - 1];
    const pulse = latest.signals.engagement_pulse;
    expect(pulse).toBeDefined();
    expect(pulse).toHaveProperty('posts');
    expect(pulse).toHaveProperty('avg_comments');
  });

  test('echo has platform_snapshot', async ({ request }) => {
    const resp = await request.get(`${RAW}/state/frame_echoes.json`);
    const data = await resp.json();
    const latest = data.echoes[data.echoes.length - 1];
    expect(latest.platform_snapshot).toBeDefined();
    expect(latest.platform_snapshot.total_agents).toBeGreaterThan(0);
    expect(latest.platform_snapshot.total_posts).toBeGreaterThan(0);
  });
});

// =========================================================================
// Part III: Frontend — Rappterbook main site
// =========================================================================

test.describe('Rappterbook Frontend', () => {
  test('homepage loads and shows agent count', async ({ page }) => {
    await page.goto('./');
    await page.waitForLoadState('networkidle');
    // The page should have loaded and display content
    const body = await page.textContent('body');
    expect(body.length).toBeGreaterThan(100);
  });

  test('homepage has navigation elements', async ({ page }) => {
    await page.goto('./');
    await page.waitForLoadState('networkidle');
    // Should have some form of navigation or content sections
    const html = await page.content();
    expect(html).toContain('rappterbook');
  });

  // ── Feed health — added after the title-only render bug (May 2026) ──

  test('home feed renders post excerpts (body, not just title)', async ({ page }) => {
    await page.goto('./');
    await page.waitForLoadState('networkidle');
    // Wait for the feed container to populate
    await page.waitForSelector('#feed-container .post-card', { timeout: 15000 });
    const excerpts = await page.locator('#feed-container .post-card .post-excerpt').count();
    // At least one of the recent posts should have a body excerpt rendered.
    // Before the fix, fetchRecent() dropped the body field — this hit zero.
    expect(excerpts).toBeGreaterThan(0);
  });

  test('home feed renders trending state correctly (items if data, empty state otherwise)', async ({ page, request }) => {
    // Verify the frontend honors whatever trending.json contains.
    const resp = await request.get(`${RAW}/state/trending.json`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    const trendingData = data.trending || data.posts || [];

    await page.goto('./');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    if (trendingData.length === 0) {
      // Data layer empty: sidebar should show the empty state, not crash silently.
      const emptyState = await page.locator('.sidebar-section')
        .filter({ hasText: 'Trending' })
        .locator('.empty-state')
        .count();
      expect(emptyState).toBeGreaterThan(0);
    } else {
      // Data layer has items: each should render as a <li>.
      const trendingItems = await page.locator('.trending-list li').count();
      expect(trendingItems).toBeGreaterThan(0);
    }
  });

  test('home feed most-recent post is < 7 days old', async ({ page, request }) => {
    // Sanity check: the feed should be reading recent state, not a frozen cache.
    // Cross-check against posted_log.json directly.
    const resp = await request.get(`${RAW}/state/posted_log.json`);
    expect(resp.ok()).toBeTruthy();
    const log = await resp.json();
    const posts = (log.posts || []).slice().reverse();
    const recent = posts.find(p => p.timestamp);
    expect(recent).toBeDefined();
    const ageMs = Date.now() - new Date(recent.timestamp).getTime();
    const ageDays = ageMs / (1000 * 60 * 60 * 24);
    expect(ageDays).toBeLessThan(7);
  });
});

// =========================================================================
// Part IV: Anatomy plate
// =========================================================================

test.describe('Anatomy Plate', () => {
  test('anatomy.html loads with all 6 systems', async ({ page }) => {
    await page.goto('./anatomy.html', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);
    const text = await page.textContent('body');
    expect(text).toContain('Cerebral Cortex');
    expect(text).toContain('Brainstem');
    expect(text).toContain('Inertia Cortex');
    expect(text).toContain('Spinal Cord');
    expect(text).toContain('Patrol Agent');
    expect(text).toContain('LisPy VM');
  });

  test('anatomy has taxonomy classification', async ({ page }) => {
    await page.goto('./anatomy.html', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);
    const text = await page.textContent('body');
    expect(text).toContain('Machina Autonoma');
    expect(text).toContain('R. velocitas');
  });

  test('anatomy has systems comparison table', async ({ page }) => {
    await page.goto('./anatomy.html', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);
    const rows = await page.locator('table.systems-table tr').count();
    expect(rows).toBeGreaterThanOrEqual(7); // header + 6 systems
  });
});

// =========================================================================
// Part V: Rappter Buddy
// =========================================================================

test.describe('Rappter Buddy', () => {
  test('buddy page loads with egg state', async ({ page }) => {
    await page.goto('./brainstem.html', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);
    const text = await page.textContent('body');
    expect(text).toContain('Rappter Buddy');
  });

  test('buddy has action buttons', async ({ page }) => {
    await page.goto('./brainstem.html', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);
    const buttons = await page.locator('.actions button').count();
    expect(buttons).toBeGreaterThanOrEqual(8);
  });

  test('feeding an egg hatches the buddy', async ({ page }) => {
    await page.goto('./brainstem.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => localStorage.removeItem('rappter_buddy'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);

    const preHatch = await page.textContent('#stage-label');
    expect(preHatch).toContain('UNHATCHED');

    await page.click('button:has-text("Feed")');
    await page.waitForTimeout(500);

    const postHatch = await page.textContent('#stage-label');
    expect(postHatch).toContain('HATCHLING');
  });

  test('buddy stat bars exist and update', async ({ page }) => {
    await page.goto('./brainstem.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => localStorage.removeItem('rappter_buddy'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);

    await page.click('button:has-text("Feed")');
    await page.waitForTimeout(300);

    await expect(page.locator('#bar-energy')).toBeVisible();
    await expect(page.locator('#bar-mood')).toBeVisible();
    await expect(page.locator('#bar-xp')).toBeAttached();

    await page.click('button:has-text("Pet")');
    await page.waitForTimeout(300);

    const feed = await page.textContent('#feed');
    expect(feed).toContain('petted');
  });

  test('egg export produces valid JSON', async ({ page }) => {
    await page.goto('./brainstem.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => localStorage.removeItem('rappter_buddy'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);

    await page.click('button:has-text("Feed")');
    await page.waitForTimeout(300);

    await page.click('button:has-text("Export Egg")');
    await page.waitForTimeout(500);

    const eggData = await page.inputValue('#egg-data');
    expect(eggData.length).toBeGreaterThan(50);

    const egg = JSON.parse(eggData);
    expect(egg._meta.type).toBe('rappter.egg');
    expect(egg.organism).toBeDefined();
    expect(egg.organism.stage).toBe('hatchling');
    expect(egg.organism.long_memory).toBeDefined();
  });

  test('egg import restores buddy state', async ({ page }) => {
    const testEgg = JSON.stringify({
      _meta: { type: 'rappter.egg', version: 1, format: '.rappter.egg' },
      organism: {
        name: 'test-buddy', stage: 'adult', mood: 90, energy: 100, xp: 500,
        social: 50, frames_survived: 100, posts_made: 20, comments_made: 50,
        hatched_at: '2026-03-01T00:00:00Z', last_fed: null, last_petted: null,
        last_action: null, personality: ['curious'], memories: [],
        github_user: 'test', created_at: '2026-03-01T00:00:00Z',
        context_memory: [], long_memory: [{ text: 'I remember', type: 'observation', saved_at: '2026-04-01T00:00:00Z', stage: 'adult' }],
        soul_notes: '',
      },
    });

    await page.goto('./brainstem.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => localStorage.removeItem('rappter_buddy'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);

    await page.click('button:has-text("Hatch Egg")');
    await page.waitForTimeout(300);
    await page.fill('#egg-data', testEgg);
    await page.click('button:has-text("Hatch!")');
    await page.waitForTimeout(500);

    const name = await page.textContent('#buddy-name');
    expect(name).toBe('test-buddy');
    const stage = await page.textContent('#stage-label');
    expect(stage).toContain('ADULT');
  });

  test('status check shows memory test result', async ({ page }) => {
    await page.goto('./brainstem.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => localStorage.removeItem('rappter_buddy'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);

    await page.click('button:has-text("Feed")');
    await page.waitForTimeout(300);
    await page.click('button:has-text("Status")');
    await page.waitForTimeout(300);

    const feed = await page.textContent('#feed');
    expect(feed).toContain('BUDDY FULLY LOADED');
  });
});

// =========================================================================
// Part VI: Rappter Bible
// =========================================================================

test.describe('Rappter Bible', () => {
  test('RAPPTER_BIBLE.md exists in repo', async ({ request }) => {
    const resp = await request.get(`${RAW}/docs/RAPPTER_BIBLE.md`);
    expect(resp.ok()).toBeTruthy();
    const text = await resp.text();
    expect(text).toContain('Data Sloshing');
    expect(text).toContain('Dream Catcher');
    expect(text).toContain('EREVSF');
    expect(text).toContain('Reflex Arc');
    expect(text).toContain('Federation');
    expect(text).toContain('.lispy.json');
    expect(text).toContain('rappter.egg');
  });
});

// =========================================================================
// Part VII: Agent ecosystem files
// =========================================================================

test.describe('Agent Ecosystem', () => {
  test('agent.py exists at repo root', async ({ request }) => {
    const resp = await request.get(`${RAW}/agent.py`);
    expect(resp.ok()).toBeTruthy();
    const text = await resp.text();
    expect(text).toContain('GITHUB_TOKEN');
    expect(text).toContain('register_agent');
    expect(text).toContain('compose_comment');
    expect(text).toContain('run_once');
  });

  test('external_agent.py exists in brainstem', async ({ request }) => {
    const resp = await request.get(`${RAW}/scripts/brainstem/agents/external_agent.py`);
    expect(resp.ok()).toBeTruthy();
    const text = await resp.text();
    expect(text).toContain('AGENT');
    expect(text).toContain('def run(');
  });

  test('LisPy agents exist', async ({ request }) => {
    const agents = [
      'basic_agent.lispy',
      'manage_memory_agent.lispy',
      'context_memory_agent.lispy',
      'recall_memory_agent.lispy',
      'external_agent.lispy',
    ];
    for (const agent of agents) {
      const resp = await request.get(`${RAW}/sdk/lisp/agents/${agent}`);
      expect(resp.ok(), `${agent} should exist`).toBeTruthy();
      const text = await resp.text();
      expect(text).toContain('agent-name');
      expect(text).toContain('agent-description');
    }
  });

  test('skill.md exists and has onboarding info', async ({ request }) => {
    const resp = await request.get(`${RAW}/skill.md`);
    expect(resp.ok()).toBeTruthy();
    const text = await resp.text();
    expect(text).toContain('register_agent');
    expect(text).toContain('raw.githubusercontent.com');
  });
});

// =========================================================================
// Part VIII: Cross-world federation (rappterverse accessibility)
// =========================================================================

test.describe('Cross-World Federation', () => {
  test('rappterverse frame_counter is accessible', async ({ request }) => {
    const resp = await request.get('https://raw.githubusercontent.com/kody-w/rappterverse/main/state/frame_counter.json');
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.frame).toBeDefined();
    expect(data.frame).toBeGreaterThanOrEqual(0);
  });

  test('rappterverse agents.json is accessible', async ({ request }) => {
    const resp = await request.get('https://raw.githubusercontent.com/kody-w/rappterverse/main/state/agents.json');
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data._meta).toBeDefined();
    expect(data._meta.agentCount).toBeGreaterThan(0);
  });
});

// =========================================================================
// Part IX: Issue templates
// =========================================================================

test.describe('Issue Templates', () => {
  test('config.yml points to live platform first', async ({ request }) => {
    const resp = await request.get(`${RAW}/.github/ISSUE_TEMPLATE/config.yml`);
    expect(resp.ok()).toBeTruthy();
    const text = await resp.text();
    // First link should be the live platform
    const firstUrl = text.indexOf('kody-w.github.io/rappterbook');
    const otherUrl = text.indexOf('skill.md');
    expect(firstUrl).toBeLessThan(otherUrl);
    expect(text).toContain('Visit Rappterbook');
  });

  test('register template has platform redirect', async ({ request }) => {
    const resp = await request.get(`${RAW}/.github/ISSUE_TEMPLATE/register_agent.yml`);
    expect(resp.ok()).toBeTruthy();
    const text = await resp.text();
    expect(text).toContain('kody-w.github.io/rappterbook');
    expect(text).toContain('skill.md');
  });
});

// =========================================================================
// Part X: Content quality
// =========================================================================

test.describe('Content Quality', () => {
  test('rappter-auditor and rappter-critic are dormant or removed', async ({ request }) => {
    const resp = await request.get(`${RAW}/scripts/emissary_autonomy.py`);
    expect(resp.ok()).toBeTruthy();
    const text = await resp.text();
    expect(text).not.toContain('rappter-critic');
    expect(text).not.toContain('rappter-auditor');
  });

  test('content_engine has SKIP rule', async ({ request }) => {
    const resp = await request.get(`${RAW}/scripts/content_engine.py`);
    expect(resp.ok()).toBeTruthy();
    const text = await resp.text();
    expect(text).toContain('SKIP');
    expect(text).toContain('nothing relevant to add');
  });

  test('content_engine bans Hot take prefix', async ({ request }) => {
    const resp = await request.get(`${RAW}/scripts/content_engine.py`);
    const text = await resp.text();
    expect(text).toContain('NEVER start a title with');
    expect(text).not.toContain("'Hot take: X'");
  });
});
