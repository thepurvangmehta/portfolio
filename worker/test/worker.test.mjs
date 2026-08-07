// End-to-end logic test for the access-request Worker, run against a REAL
// SQLite database via node:sqlite with a thin D1-compatible shim. This
// exercises the actual SQL and the actual handlers -- the previous round of
// "tests" mocked fetch and never touched the real code paths, which is how a
// 500-on-preflight bug shipped.
import { DatabaseSync } from 'node:sqlite';
// Run with:  node worker/test/worker.test.mjs
import worker from '../src/index.js';

const db = new DatabaseSync(':memory:');

function makeStmt(sql, params = []) {
  return {
    bind(...args) { return makeStmt(sql, args); },
    async first(col) {
      const row = db.prepare(sql).get(...params);
      if (!row) return null;
      return col === undefined ? row : row[col];
    },
    async run() { return db.prepare(sql).run(...params); },
    _exec() { return db.prepare(sql).run(...params); },
  };
}
const DB = {
  prepare: (sql) => makeStmt(sql),
  async batch(stmts) { return stmts.map((s) => s._exec()); },
};

let pushoverCalls = [];
globalThis.fetch = async (url, opts) => {
  pushoverCalls.push({ url, body: opts && opts.body && opts.body.toString() });
  return new Response('{"status":1}', { status: 200 });
};

const env = {
  DB,
  GATE_PASSWORD: 'the-real-gate-password',
  PUSHOVER_TOKEN: 'ptoken',
  PUSHOVER_USER: 'puser',
  ALLOWED_ORIGIN: 'https://thepurvangmehta.com',
};

const BASE = 'https://case-study-access.example.workers.dev';
const call = (path, init) => worker.fetch(new Request(BASE + path, init), env);
const postJson = (path, obj, headers = {}) =>
  call(path, { method: 'POST', body: JSON.stringify(obj), headers: { 'content-type': 'application/json', ...headers } });

let failures = 0;
function check(name, cond, extra) {
  if (cond) { console.log(`  PASS  ${name}`); }
  else { failures++; console.log(`  FAIL  ${name}${extra !== undefined ? ' -> ' + JSON.stringify(extra) : ''}`); }
}

console.log('\n== CORS preflight (regression: must be 204 with NO body) ==');
{
  const r = await call('/request-access', { method: 'OPTIONS' });
  check('status is 204', r.status === 204, r.status);
  check('body is empty', (await r.text()) === '');
  check('allow-origin echoed', r.headers.get('access-control-allow-origin') === env.ALLOWED_ORIGIN);
}

console.log('\n== missing D1 binding surfaces clearly ==');
{
  const r = await worker.fetch(new Request(BASE + '/check-email?email=a@b.com'), { ...env, DB: undefined });
  const j = await r.json();
  check('503 misconfigured', r.status === 503 && j.error === 'misconfigured', j);
}

console.log('\n== health ==');
{
  const j = await (await call('/health')).json();
  check('reports d1 storage', j.ok === true && j.storage === 'd1', j);
}

console.log('\n== approve flow ==');
let reqId;
{
  const r = await postJson('/request-access', { email: 'Jane@Acme.com ' }, { 'CF-Connecting-IP': '1.1.1.1' });
  const j = await r.json();
  reqId = j.requestId;
  check('returns pending + requestId', j.status === 'pending' && !!j.requestId, j);
  check('pushover notified once', pushoverCalls.length === 1, pushoverCalls.length);
  check('notification carries approve link', (pushoverCalls[0].body || '').includes(encodeURIComponent(`/approve?token=${reqId}`).replace(/%2F/g, '%2F')) || (pushoverCalls[0].body || '').includes(reqId), true);
  check('secret NOT leaked while pending', !JSON.stringify(j).includes(env.GATE_PASSWORD), j);
}
{
  const j = await (await call(`/check-access?requestId=${reqId}`)).json();
  check('poll says pending', j.status === 'pending', j);
  check('no secret while pending', j.secret === undefined, j);
}
{
  const r = await call(`/approve?token=${reqId}`);
  const body = await r.text();
  check('approve page 200', r.status === 200, r.status);
  check('approve page names the email', body.includes('jane@acme.com'), body.slice(0, 120));
}
{
  // THE critical assertion: immediately after approval, the very next poll
  // must return approved. This is what KV could not do.
  const j = await (await call(`/check-access?requestId=${reqId}`)).json();
  check('next poll is approved (no staleness)', j.status === 'approved', j);
  check('secret handed back', j.secret === env.GATE_PASSWORD, j);
}
{
  const j = await (await call('/check-email?email=jane@acme.com')).json();
  check('email now globally approved', j.status === 'approved' && j.secret === env.GATE_PASSWORD, j);
}
{
  const before = pushoverCalls.length;
  const j = await (await postJson('/request-access', { email: 'jane@acme.com' }, { 'CF-Connecting-IP': '1.1.1.1' })).json();
  check('approved email short-circuits', j.status === 'approved' && j.secret === env.GATE_PASSWORD, j);
  check('no new notification sent', pushoverCalls.length === before, pushoverCalls.length);
}
{
  const r = await call(`/approve?token=${reqId}`);
  check('re-approving same token is rejected', r.status === 409, r.status);
}

console.log('\n== deny flow ==');
{
  const j = await (await postJson('/request-access', { email: 'spam@x.com' }, { 'CF-Connecting-IP': '2.2.2.2' })).json();
  const r = await call(`/deny?token=${j.requestId}`);
  check('deny page 200', r.status === 200, r.status);
  const p = await (await call(`/check-access?requestId=${j.requestId}`)).json();
  check('poll says denied', p.status === 'denied', p);
  check('no secret on denial', p.secret === undefined, p);
  const e = await (await call('/check-email?email=spam@x.com')).json();
  check('denied email not approved', e.status === 'none', e);
}

console.log('\n== unknown / invalid input ==');
{
  const j = await (await call('/check-access?requestId=does-not-exist')).json();
  check('unknown request is expired', j.status === 'expired', j);
  const b = await call('/request-access', { method: 'POST', body: 'not json', headers: { 'content-type': 'application/json' } });
  check('malformed body -> 400', b.status === 400, b.status);
  const i = await postJson('/request-access', { email: 'nope' }, { 'CF-Connecting-IP': '3.3.3.3' });
  check('invalid email -> 400', i.status === 400, i.status);
  const nf = await call('/nope');
  check('unknown path -> 404', nf.status === 404, nf.status);
}

console.log('\n== rate limiting ==');
{
  let last;
  for (let i = 0; i < 6; i++) {
    last = await postJson('/request-access', { email: 'flood@x.com' }, { 'CF-Connecting-IP': '4.4.4.4' });
  }
  check('6th request for one email is 429', last.status === 429, last.status);
}
{
  let last;
  for (let i = 0; i < 25; i++) {
    last = await postJson('/request-access', { email: `u${i}@x.com` }, { 'CF-Connecting-IP': '5.5.5.5' });
  }
  check('per-IP flood eventually 429', last.status === 429, last.status);
}

console.log('\n== stale pending request expires ==');
{
  const j = await (await postJson('/request-access', { email: 'old@x.com' }, { 'CF-Connecting-IP': '6.6.6.6' })).json();
  db.prepare('UPDATE requests SET created_at = ?1 WHERE id = ?2')
    .run(Date.now() - 25 * 60 * 60 * 1000, j.requestId);
  const p = await (await call(`/check-access?requestId=${j.requestId}`)).json();
  check('24h-old pending reads as expired', p.status === 'expired', p);
}

console.log(failures === 0 ? '\nALL PASSED\n' : `\n${failures} FAILURE(S)\n`);
process.exit(failures === 0 ? 0 : 1);
