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

// Two channels, so the shim routes by host and each can be failed on its own.
// A phone that was wiped and never re-registered shows up as a Pushover
// rejection -- the kind the Worker used to ignore, which is the whole bug.
let pushCalls = [], emailCalls = [];
let pushReply = () => new Response('{"status":1,"request":"abc"}', { status: 200 });
let emailReply = () => new Response('{"id":"e1"}', { status: 200 });
globalThis.fetch = async (url, opts) => {
  const u = String(url);
  const body = opts && opts.body && opts.body.toString();
  if (u.includes('pushover')) { pushCalls.push({ u, body }); return pushReply(); }
  if (u.includes('resend')) { emailCalls.push({ u, body }); return emailReply(); }
  throw new Error('unexpected outbound fetch: ' + u);
};

const env = {
  DB,
  GATE_PASSWORD: 'the-real-gate-password',
  PUSHOVER_TOKEN: 'ptoken',
  PUSHOVER_USER: 'puser',
  RESEND_TOKEN: 're_test',
  NOTIFY_EMAIL_TO: 'me@example.com',
  NOTIFY_EMAIL_FROM: 'Access <access@example.com>',
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
  check('pushover notified once', pushCalls.length === 1, pushCalls.length);
  check('no email while pushover works', emailCalls.length === 0, emailCalls.length);
  check('notification carries approve link', (pushCalls[0].body || '').includes(reqId));
  check('notification names the requester', (pushCalls[0].body || '').includes('jane%40acme.com'));
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
  const before = pushCalls.length;
  const j = await (await postJson('/request-access', { email: 'jane@acme.com' }, { 'CF-Connecting-IP': '1.1.1.1' })).json();
  check('approved email short-circuits', j.status === 'approved' && j.secret === env.GATE_PASSWORD, j);
  check('no new notification sent', pushCalls.length === before, pushCalls.length);
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

console.log('\n== Pushover dies -> email fallback carries it, and says so ==');
{
  // A wiped phone that was never re-registered, from the Worker's point of view.
  pushReply = () => new Response(
    '{"status":0,"errors":["user identifier is not a valid user, group, or subscribed user key"]}',
    { status: 400 });
  const before = emailCalls.length;

  const r = await postJson('/request-access', { email: 'fallback@x.com' }, { 'CF-Connecting-IP': '10.10.10.1' });
  const j = await r.json();
  check('visitor still gets 200 pending', r.status === 200 && j.status === 'pending', j);
  check('email fallback fired', emailCalls.length === before + 1, emailCalls.length - before);
  check('fallback email names the requester', (emailCalls[before].body || '').includes('fallback@x.com'));

  const row = db.prepare('SELECT notified_at, notified_via, notify_error FROM requests WHERE id = ?1').get(j.requestId);
  check('recorded as delivered', !!row.notified_at, row);
  check('recorded as delivered by email', row.notified_via === 'email', row);
  // The point of the fallback: it must not hide that the phone stopped working.
  check('primary failure kept anyway', /not a valid user/.test(row.notify_error || ''), row.notify_error);

  const body = await (await call('/admin?key=super-secret-admin-key')).text();
  check('banner is amber, not green', /only by the fallback/.test(body));
  check('banner is not a false all-clear', !/Notifications are working/.test(body));
  check('banner shows the Pushover reason', /not a valid user/.test(body));
  check('banner tells you how to fix it', /PUSHOVER_USER/.test(body));
}

console.log('\n== both channels dead: recorded, surfaced, still non-fatal ==');
{
  pushReply = () => new Response('{"status":0,"errors":["no active devices"]}', { status: 400 });
  emailReply = () => new Response('{"message":"domain not verified"}', { status: 403 });

  const r = await postJson('/request-access', { email: 'nochannel@x.com' }, { 'CF-Connecting-IP': '10.10.10.2' });
  const j = await r.json();
  check('visitor still gets 200 pending', r.status === 200 && j.status === 'pending', j);
  const row = db.prepare('SELECT notified_at, notified_via, notify_error FROM requests WHERE id = ?1').get(j.requestId);
  check('recorded as undelivered', row.notified_at === null && row.notified_via === null, row);
  check('both reasons kept', /no active devices/.test(row.notify_error) && /domain not verified/.test(row.notify_error), row.notify_error);

  const body = await (await call('/admin?key=super-secret-admin-key')).text();
  check('banner is red', /NOT being delivered/.test(body));
  check('pending row marked undelivered', /not delivered/.test(body));
}
{
  // An unreachable network must not 500 the visitor either.
  pushReply = () => { throw new Error('connection reset'); };
  const r = await postJson('/request-access', { email: 'netfail@x.com' }, { 'CF-Connecting-IP': '10.10.10.3' });
  check('network failure -> still 200 pending', r.status === 200, r.status);
  const j = await r.json();
  const row = db.prepare('SELECT notify_error FROM requests WHERE id = ?1').get(j.requestId);
  check('network failure recorded', /could not reach/.test(row.notify_error || ''), row);
}

console.log('\n== /admin/notify-test tests each channel separately ==');
{
  const locked = await call('/admin/notify-test');
  check('no key -> 404', locked.status === 404, locked.status);

  pushReply = () => new Response('{"status":0,"errors":["no active devices"]}', { status: 400 });
  emailReply = () => new Response('{"id":"e1"}', { status: 200 });
  const partial = await call('/admin/notify-test?key=super-secret-admin-key');
  const pBody = await partial.text();
  check('a working fallback keeps it a 200', partial.status === 200, partial.status);
  check('names the failing channel', /Pushover \(your phone\): failed/.test(pBody));
  check('names the working one', /Email fallback: sent/.test(pBody));
  check('shows the reason', /no active devices/.test(pBody));

  pushReply = () => new Response('{"status":1}', { status: 200 });
  const pBefore = pushCalls.length, eBefore = emailCalls.length;
  const good = await call('/admin/notify-test?key=super-secret-admin-key');
  const gBody = await good.text();
  check('both channels really sent', pushCalls.length === pBefore + 1 && emailCalls.length === eBefore + 1);
  check('200', good.status === 200, good.status);
  check('both reported sent', /Pushover \(your phone\): sent/.test(gBody) && /Email fallback: sent/.test(gBody));
  check('test leaks no gate password', !gBody.includes(env.GATE_PASSWORD));
  check('test notification carries no approve link', !/approve%3Ftoken/.test(pushCalls[pBefore].body || ''));
}

console.log('\n== a healthy channel reads as healthy ==');
{
  const j = await (await postJson('/request-access', { email: 'healthy@x.com' }, { 'CF-Connecting-IP': '10.10.10.4' })).json();
  const row = db.prepare('SELECT notified_at, notified_via, notify_error FROM requests WHERE id = ?1').get(j.requestId);
  check('success recorded via pushover', !!row.notified_at && row.notified_via === 'pushover' && row.notify_error === null, row);
  const body = await (await call('/admin?key=super-secret-admin-key')).text();
  check('banner reads healthy', /Notifications are working/.test(body));
  check('no false alarm', !/NOT being delivered/.test(body) && !/only by the fallback/.test(body));

  const h = await (await call('/health')).json();
  check('health lists both channels', JSON.stringify(h.notifyChannels) === '["pushover","email"]', h);
  const bare = await worker.fetch(new Request(BASE + '/health'), { ...env, PUSHOVER_USER: undefined, RESEND_TOKEN: undefined });
  check('health lists none when unset', JSON.stringify((await bare.json()).notifyChannels) === '[]');
}

console.log('\n== a green test counts as evidence (banner stops saying "not verified") ==');
{
  // Wipe every trace of a delivery so the banner starts from "unknown".
  db.prepare('DELETE FROM notify_status').run();
  const fresh = await (await call('/admin?key=super-secret-admin-key')).text();
  check('starts as not verified', /Notifications: not verified/.test(fresh));

  pushReply = () => new Response('{"status":1}', { status: 200 });
  await call('/admin/notify-test?key=super-secret-admin-key');

  const after = await (await call('/admin?key=super-secret-admin-key')).text();
  check('a passing test turns it green', /Notifications are working/.test(after));
  check('and says it was a test, not a real request', /Last test delivered/.test(after));
  check('no longer claims unverified', !/Notifications: not verified/.test(after));
}
{
  // A failing test must equally turn it red, not leave a stale green.
  pushReply = () => new Response('{"status":0,"errors":["no active devices"]}', { status: 400 });
  emailReply = () => new Response('{"message":"nope"}', { status: 403 });
  await call('/admin/notify-test?key=super-secret-admin-key');
  const body = await (await call('/admin?key=super-secret-admin-key')).text();
  check('a failing test turns it red', /NOT being delivered/.test(body));
  check('shows the reason', /no active devices/.test(body));
}

console.log('\n== inviting someone whose request never reached you ==');
{
  emailReply = () => new Response('{"id":"inv1"}', { status: 200 });
  const before = emailCalls.length;
  const r = await call('/admin/invite?key=super-secret-admin-key&email=praneeth@example.com');
  const body = await r.text();
  check('200', r.status === 200, r.status);
  check('confirms it went out', /Invite sent/.test(body));

  const sent = JSON.parse(emailCalls[before].body);
  check('addressed to the visitor, not the owner', sent.to[0] === 'praneeth@example.com', sent.to);
  check('replies come back to the owner', sent.reply_to === env.NOTIFY_EMAIL_TO, sent.reply_to);
  check('apologises', /never heard back|Sorry/i.test(sent.html));
  check('tells them to use that same address', sent.html.includes('praneeth@example.com'));
  check('does NOT leak the gate password', !sent.html.includes(env.GATE_PASSWORD));

  // The point of the whole thing: they can now get in without asking again.
  const g = await (await call('/check-email?email=praneeth@example.com')).json();
  check('they can now unlock', g.status === 'approved' && g.secret === env.GATE_PASSWORD, g.status);
  const days = (g.expiresAt - Date.now()) / 86400000;
  check('window is ~7 days, not 4 hours', days > 6.9 && days <= 7.01, days);
}
{
  // If the mail cannot be sent, granting access would make the admin list claim
  // someone can get in who was never told. Neither should happen.
  emailReply = () => new Response('{"message":"domain not verified"}', { status: 403 });
  const r = await call('/admin/invite?key=super-secret-admin-key&email=nomail@example.com');
  const body = await r.text();
  check('reports the failure', r.status === 502 && /Invite not sent/.test(body), r.status);
  check('names the reason', /domain not verified/.test(body));
  const g = await (await call('/check-email?email=nomail@example.com')).json();
  check('no access granted when the mail failed', g.status === 'none', g);
}
{
  const bad = await call('/admin/invite?key=super-secret-admin-key&email=notanemail');
  check('rejects a malformed address', bad.status === 400, bad.status);
  const locked = await call('/admin/invite?email=x@y.com');
  check('needs the admin key', locked.status === 404, locked.status);
}
{
  const linkFor = (body, email) =>
    new RegExp('admin/invite\\?key=[^"]*' + encodeURIComponent(email).replace('.', '\\.')).test(body);

  const before = await (await call('/admin?key=super-secret-admin-key')).text();
  check('offers Invite to a contact with no access', linkFor(before, 'spam@x.com'));

  emailReply = () => new Response('{"id":"inv2"}', { status: 200 });
  await call('/admin/invite?key=super-secret-admin-key&email=spam@x.com');

  const after = await (await call('/admin?key=super-secret-admin-key')).text();
  check('button gone once they have access', !linkFor(after, 'spam@x.com'));
  check('and they now show as having access', /7d left|168h left|\d+h left/.test(after));
}

console.log('\n== a missing setting names itself ==');
{
  const partial = { ...env, NOTIFY_EMAIL_FROM: undefined };
  const r = await worker.fetch(new Request(BASE + '/admin/notify-test?key=super-secret-admin-key'), partial);
  const body = await r.text();
  check('names the one that is missing', /not set on this Worker: NOTIFY_EMAIL_FROM/.test(body));
  check('does not blame the ones that are set', !/RESEND_TOKEN, NOTIFY_EMAIL_TO/.test(body));

  const blank = { ...env, RESEND_TOKEN: '   ' };
  const r2 = await worker.fetch(new Request(BASE + '/admin/notify-test?key=super-secret-admin-key'), blank);
  check('whitespace counts as missing', /not set on this Worker: RESEND_TOKEN/.test(await r2.text()));

  const noPush = { ...env, PUSHOVER_USER: undefined };
  const r3 = await worker.fetch(new Request(BASE + '/admin/notify-test?key=super-secret-admin-key'), noPush);
  check('same for Pushover', /not set on this Worker: PUSHOVER_USER/.test(await r3.text()));
}

console.log('\n== removing an address erases it everywhere ==');
{
  // Give someone live access first, so we can prove the grant dies with them.
  emailReply = () => new Response('{"id":"inv3"}', { status: 200 });
  await call('/admin/invite?key=super-secret-admin-key&email=deleteme@x.com');
  const had = await (await call('/check-email?email=deleteme@x.com')).json();
  check('has access before removal', had.status === 'approved', had.status);
  db.prepare("INSERT INTO requests (id, email, status, created_at) VALUES ('r-del', 'deleteme@x.com', 'pending', ?1)")
    .run(Date.now());

  const r = await call('/admin/delete?key=super-secret-admin-key&email=deleteme@x.com');
  check('redirects back to the list', r.status === 302, r.status);
  check('goes to the admin page', (r.headers.get('location') || '').includes('/admin?key='));

  check('gone from contacts',
    !db.prepare("SELECT 1 FROM contacts WHERE email='deleteme@x.com'").get());
  check('gone from requests',
    !db.prepare("SELECT 1 FROM requests WHERE email='deleteme@x.com'").get());
  // The one that matters: a surviving grant would let a now-invisible address
  // keep unlocking everything.
  check('grant revoked too',
    !db.prepare("SELECT 1 FROM approved WHERE email='deleteme@x.com'").get());
  const after = await (await call('/check-email?email=deleteme@x.com')).json();
  check('really cannot get in any more', after.status === 'none', after);

  const body = await (await call('/admin?key=super-secret-admin-key')).text();
  check('no longer listed', !body.includes('deleteme@x.com'));
}
{
  check('needs the admin key', (await call('/admin/delete?email=x@y.com')).status === 404);
  check('rejects a malformed address',
    (await call('/admin/delete?key=super-secret-admin-key&email=notanemail')).status === 400);
  const body = await (await call('/admin?key=super-secret-admin-key')).text();
  check('every contact row offers Remove', /admin\/delete\?key=/.test(body));
  check('Remove asks before erasing', /confirm\('Delete /.test(body));
}

console.log(failures === 0 ? '\nALL PASSED\n' : `\n${failures} FAILURE(S)\n`);
process.exit(failures === 0 ? 0 : 1);
