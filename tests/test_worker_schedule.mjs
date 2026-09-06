import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
// Import the exact Worker source as ESM without changing its package/deployment type.
const source = fs.readFileSync(new URL('../cloudflare-worker/src/index.js', import.meta.url), 'utf8');
const { default: worker, scheduledProject, dispatchInputs } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const event = (cron, iso) => ({ cron, scheduledTime: Date.parse(iso) });

test('International manual and cron requests have no record cap', () => {
  for (const reason of ['telegram', 'cloudflare-cron']) {
    assert.deepEqual(dispatchInputs({ key: 'international' }, reason), {
      bootstrap_production: false, release_acceptance: false, send_telegram: false, max_jobs_per_source: 'all',
    });
  }
  assert.deepEqual(dispatchInputs({ key: 'spain' }, 'cloudflare-cron'), { trigger_source: 'cloudflare-cron' });
});

test('Exactly one 06:00 Madrid dispatch each day, including both DST transitions', () => {
  let date = new Date('2026-01-01T00:00:00Z');
  for (let day = 0; day < 365; day++, date.setUTCDate(date.getUTCDate() + 1)) {
    const prefix = date.toISOString().slice(0, 10);
    const keys = [4, 5].map(h => scheduledProject(event(`0 ${h} * * *`, `${prefix}T0${h}:00:00Z`)));
    assert.equal(keys.filter(x => x === 'international').length, 1, prefix);
    assert.equal(scheduledProject(event('17 3 * * *', `${prefix}T03:17:00Z`)), 'spain');
  }
  assert.equal(scheduledProject(event('0 4 * * *', '2026-09-07T04:00:00Z')), 'international');
  assert.equal(scheduledProject(event('0 5 * * *', '2026-12-07T05:00:00Z')), 'international');
  assert.equal(scheduledProject(event('0 9 * * *', '2026-09-07T09:00:00Z')), null);
});

const env = { INTERNATIONAL_GITHUB_OWNER: 'soccerwave', REPORTS_INTERNATIONAL: {}, GITHUB_TOKEN: 'test' };
test('Scheduled handler actually dispatches International with all and skips wrong seasonal hour', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url, init });
    return init.method === 'POST' ? new Response(null, { status: 204 }) : Response.json({ workflow_runs: [] });
  };
  try {
    const pending = [];
    await worker.scheduled(event('0 4 * * *', '2026-09-07T04:00:00Z'), env, { waitUntil: p => pending.push(p) });
    await Promise.all(pending);
    const post = calls.find(c => c.init.method === 'POST');
    assert.ok(post.url.includes('international-academic-job-search'));
    assert.equal(JSON.parse(post.init.body).inputs.max_jobs_per_source, 'all');
    calls.length = 0;
    await worker.scheduled(event('0 5 * * *', '2026-09-07T05:00:00Z'), env, { waitUntil: () => assert.fail() });
    assert.equal(calls.length, 0);
  } finally { globalThis.fetch = original; }
});

test('Existing active International run prevents another dispatch', async () => {
  const original = globalThis.fetch;
  let posts = 0;
  globalThis.fetch = async (url, init = {}) => {
    if (init.method === 'POST') posts++;
    return Response.json({ workflow_runs: [{ id: 123, status: 'in_progress' }] });
  };
  try {
    const pending = [];
    await worker.scheduled(event('0 4 * * *', '2026-09-07T04:00:00Z'), env, { waitUntil: p => pending.push(p) });
    await Promise.all(pending);
    assert.equal(posts, 0);
  } finally { globalThis.fetch = original; }
});

test('Dispatch failure rejects scheduled execution instead of pretending success', async () => {
  const original = globalThis.fetch;
  const originalError = console.error;
  console.error = () => {};
  globalThis.fetch = async (url, init = {}) => init.method === 'POST'
    ? new Response('denied', { status: 403 }) : Response.json({ workflow_runs: [] });
  try {
    const pending = [];
    await worker.scheduled(event('0 4 * * *', '2026-09-07T04:00:00Z'), env, { waitUntil: p => pending.push(p) });
    await assert.rejects(Promise.all(pending), /403/);
  } finally { globalThis.fetch = original; console.error = originalError; }
});
