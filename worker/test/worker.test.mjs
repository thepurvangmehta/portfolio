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
    async all() { return { results: db.prepare(sql).all(...params) }; },
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
  ADMIN_KEY: 'super-secret-admin-key',
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

console.log('\n== access is time-limited (4h), not permanent ==');
{
  const j = await (await postJson('/request-access', { email: 'ttl@x.com' }, { 'CF-Connecting-IP': '7.7.7.7' })).json();
  await call(`/approve?token=${j.requestId}`);

  const ok = await (await call('/check-email?email=ttl@x.com')).json();
  check('approved -> has access', ok.status === 'approved', ok);
  const hours = (ok.expiresAt - Date.now()) / 3600000;
  check('window is ~4 hours', hours > 3.9 && hours <= 4.01, hours);

  // Wind the grant back so it has lapsed.
  db.prepare('UPDATE approved SET expires_at = ?1 WHERE email = ?2')
    .run(Date.now() - 1000, 'ttl@x.com');

  const gone = await (await call('/check-email?email=ttl@x.com')).json();
  check('lapsed grant -> no access', gone.status === 'none', gone);
  check('no secret handed out after expiry', gone.secret === undefined, gone);

  const poll = await (await call(`/check-access?requestId=${j.requestId}`)).json();
  check('old approved request reads as expired', poll.status === 'expired', poll);

  // Asking again after expiry must start a fresh request, not auto-approve.
  const again = await (await postJson('/request-access', { email: 'ttl@x.com' }, { 'CF-Connecting-IP': '7.7.7.8' })).json();
  check('must request again after expiry', again.status === 'pending', again);

  // Re-approving resets the window rather than erroring on the PK.
  await call(`/approve?token=${again.requestId}`);
  const renewed = await (await call('/check-email?email=ttl@x.com')).json();
  check('re-approval restores access', renewed.status === 'approved', renewed);
  check('window reset to ~4h', (renewed.expiresAt - Date.now()) / 3600000 > 3.9, renewed.expiresAt);
}

console.log('\n== legacy permanent grants are not honoured ==');
{
  db.prepare('INSERT INTO approved (email, created_at, expires_at) VALUES (?1, ?2, NULL)')
    .run('legacy@old.com', Date.now());
  const j = await (await call('/check-email?email=legacy@old.com')).json();
  check('null expiry != access', j.status === 'none', j);
}

console.log('\n== stale pending request expires ==');
{
  const j = await (await postJson('/request-access', { email: 'old@x.com' }, { 'CF-Connecting-IP': '6.6.6.6' })).json();
  db.prepare('UPDATE requests SET created_at = ?1 WHERE id = ?2')
    .run(Date.now() - 25 * 60 * 60 * 1000, j.requestId);
  const p = await (await call(`/check-access?requestId=${j.requestId}`)).json();
  check('24h-old pending reads as expired', p.status === 'expired', p);
}

console.log('\n== admin page is locked down ==');
{
  const noKey = await call('/admin');
  check('no key -> 404', noKey.status === 404, noKey.status);
  const wrong = await call('/admin?key=nope');
  check('wrong key -> 404', wrong.status === 404, wrong.status);
  const unset = await worker.fetch(new Request(BASE + '/admin?key=x'), { ...env, ADMIN_KEY: undefined });
  check('no ADMIN_KEY configured -> 503', unset.status === 503, unset.status);
  const body = await noKey.text();
  check('404 page leaks no addresses', !/jane@acme\.com/.test(body));
}

console.log('\n== admin page lists the collected emails ==');
{
  const r = await call('/admin?key=super-secret-admin-key');
  const body = await r.text();
  check('200', r.status === 200, r.status);
  check('noindex header', r.headers.get('x-robots-tag') === 'noindex');
  check('shows a known contact', body.includes('jane@acme.com'));
  check('shows the denied contact too', body.includes('spam@x.com'));
  check('has a pending section', /Waiting for approval/.test(body));
  check('has a copy-all box', /<textarea/.test(body));
  check('links the CSV', /\/admin\/emails\.csv/.test(body));
}

console.log('\n== an email containing HTML cannot inject (stored XSS) ==');
{
  const nasty = '<img/src=x/onerror=alert(1)>@evil.co';
  check('regex would have accepted it', /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(nasty));
  const rq = await postJson('/request-access', { email: nasty }, { 'CF-Connecting-IP': '9.9.9.9' });
  const j = await rq.json();
  check('accepted as a request', j.status === 'pending', j);

  const adminBody = await (await call('/admin?key=super-secret-admin-key')).text();
  check('admin page escapes it', !adminBody.includes('<img/src=x'), 'raw tag present');
  check('admin page shows it escaped', adminBody.includes('&lt;img/src=x'), 'not escaped');

  const decided = await call(`/approve?token=${j.requestId}`);
  const decidedBody = await decided.text();
  check('approve page escapes it', !decidedBody.includes('<img/src=x'), 'raw tag present');
}

console.log('\n== CSV export ==');
{
  const r = await call('/admin/emails.csv?key=super-secret-admin-key');
  const body = await r.text();
  check('csv content-type', /text\/csv/.test(r.headers.get('content-type')), r.headers.get('content-type'));
  check('is an attachment', /attachment/.test(r.headers.get('content-disposition')));
  check('has a header row', body.startsWith('email,first_seen,last_seen'), body.slice(0, 40));
  check('contains a contact', body.includes('jane@acme.com'));
  check('quotes fields (injection-safe)', body.includes('"jane@acme.com"'));
}

console.log('\n== contacts survive the 7-day purge of requests ==');
{
  const before = (await (await call('/admin?key=super-secret-admin-key')).text()).includes('jane@acme.com');
  db.prepare('DELETE FROM requests').run();   // simulate the purge
  const after = (await (await call('/admin?key=super-secret-admin-key')).text()).includes('jane@acme.com');
  check('contact still listed after requests are gone', before && after);
}

console.log(failures === 0 ? '\nALL PASSED\n' : `\n${failures} FAILURE(S)\n`);
process.exit(failures === 0 ? 0 : 1);
