// Case-study access-request Worker.
//
// Flow:
//   1. Visitor POSTs their email to /request-access.
//   2. If that email is already approved, the gate password ships back
//      immediately and the browser decrypts as usual.
//   3. Otherwise a pending request is stored and a Pushover notification
//      is sent with Approve/Deny links.
//   4. The browser polls /check-access until the request resolves.
//   5. Tapping Approve/Deny hits /approve or /deny. An approval grants that
//      email every gated case study for ACCESS_TTL_MS (4 hours), after which
//      they have to ask again. Approving the same address again just resets
//      the window.
//
// Storage is D1, NOT KV, on purpose. KV reads are edge-cached for at least
// 60 seconds -- including cache misses -- so a browser polling "approved
// yet?" keeps being served the stale "not yet" for up to a minute after the
// approval actually happened. That made approvals feel 30-60s slow. D1 is
// strongly consistent, so an approval is visible on the very next poll.
//
// Bindings (dashboard -> Worker -> Settings -> Bindings):
//   DB         - D1 database  (required)
//   (A CS_ACCESS KV binding is no longer read. Grants from the KV era were
//   permanent, which contradicts the time-limited policy below, so they are
//   deliberately not carried over. The binding can be deleted.)
// Secrets (dashboard -> Settings -> Variables, "Encrypt"):
//   GATE_PASSWORD   - must match CS_GATE_PW used by build.py
//   PUSHOVER_TOKEN  - Pushover application token
//   PUSHOVER_USER   - Pushover user/group key
//   ADMIN_KEY       - secret for /admin?key=... , the collected-email list
// Plain var:
//   ALLOWED_ORIGIN  - site origin allowed to call this Worker via fetch

// How long an approval lasts. Keep in step with CS_ACCESS_TTL_HOURS in
// build.py, which is what the gate UI tells visitors.
const ACCESS_TTL_MS = 4 * 60 * 60 * 1000;
const PENDING_TTL_MS = 24 * 60 * 60 * 1000;   // a request goes stale after 24h
const PURGE_AFTER_MS = 7 * 24 * 60 * 60 * 1000; // rows deleted after 7 days
const RATE_WINDOW_MS = 60 * 60 * 1000;
const RATE_MAX_PER_IP = 20;
const RATE_MAX_PER_EMAIL = 5;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Emails reach these pages straight from a public form. EMAIL_RE happily
// accepts `<img/src=x/onerror=...>@evil.co` -- no spaces, an @, a dot -- so
// anything interpolated into HTML MUST go through this or it is stored XSS
// against whoever opens the approval link.
function esc(v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// Relative time needs no timezone guess and reads fine at a glance.
function ago(ts) {
  if (!ts) return "-";
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
function inFuture(ts) {
  const s = Math.round((ts - Date.now()) / 1000);
  if (s <= 0) return "expired";
  if (s < 3600) return `${Math.round(s / 60)}m left`;
  return `${Math.round(s / 360) / 10}h left`;
}

function corsHeaders(origin) {
  return {
    "access-control-allow-origin": origin || "*",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-headers": "content-type",
  };
}

function json(data, status = 200, origin) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json",
      // Poll responses must never be cached by the browser or by any hop in
      // between -- a cached "pending" would reintroduce the exact staleness
      // this Worker was rewritten to remove.
      "cache-control": "no-store",
      ...corsHeaders(origin),
    },
  });
}

function html(body, status = 200) {
  return new Response(
    `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body{font:16px/1.6 -apple-system,system-ui,sans-serif;max-width:32rem;
    margin:4rem auto;padding:0 1.25rem;color:#111}h1{font-size:1.4rem;margin:0 0 .5rem}
    p{color:#555;margin:0}</style>${body}`,
    { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } }
  );
}

// Runs once per isolate, not once per request.
let schemaReady = false;
async function ensureSchema(env) {
  if (schemaReady) return;
  await env.DB.batch([
    env.DB.prepare(
      `CREATE TABLE IF NOT EXISTS requests (
         id TEXT PRIMARY KEY,
         email TEXT NOT NULL,
         status TEXT NOT NULL,
         ip TEXT,
         created_at INTEGER NOT NULL,
         decided_at INTEGER,
         notified_at INTEGER,
         notify_error TEXT
       )`
    ),
    env.DB.prepare(
      `CREATE TABLE IF NOT EXISTS approved (
         email TEXT PRIMARY KEY,
         created_at INTEGER NOT NULL,
         expires_at INTEGER
       )`
    ),
    // Every address ever submitted. Deliberately separate from `requests`,
    // which is operational state and gets purged after 7 days -- this is the
    // record that has to survive.
    env.DB.prepare(
      `CREATE TABLE IF NOT EXISTS contacts (
         email TEXT PRIMARY KEY,
         first_seen INTEGER NOT NULL,
         last_seen INTEGER NOT NULL,
         hits INTEGER NOT NULL DEFAULT 1
       )`
    ),
    env.DB.prepare(
      `CREATE INDEX IF NOT EXISTS idx_requests_email ON requests(email, created_at)`
    ),
    env.DB.prepare(
      `CREATE INDEX IF NOT EXISTS idx_requests_ip ON requests(ip, created_at)`
    ),
  ]);
  // Deployments created before access was time-limited have an `approved`
  // table with no expires_at. Add it, and treat those old permanent grants as
  // already lapsed rather than silently honouring them forever.
  try {
    await env.DB.prepare("ALTER TABLE approved ADD COLUMN expires_at INTEGER").run();
    await env.DB.prepare("UPDATE approved SET expires_at = created_at WHERE expires_at IS NULL").run();
  } catch (e) {
    // Column already present: nothing to migrate.
  }
  // Deployments from before push delivery was checked have no record of
  // whether a notification landed. Added separately so an existing `requests`
  // table picks them up without being rebuilt.
  for (const col of ["notified_at INTEGER", "notify_error TEXT"]) {
    try {
      await env.DB.prepare(`ALTER TABLE requests ADD COLUMN ${col}`).run();
    } catch (e) {
      // Column already present: nothing to migrate.
    }
  }
  schemaReady = true;
}

// Returns the expiry timestamp of a live grant for this address, or null if
// there isn't one (never approved, or the window has passed).
async function activeGrant(env, email) {
  const row = await env.DB.prepare(
    "SELECT expires_at FROM approved WHERE email = ?1"
  ).bind(email).first();
  if (!row || !row.expires_at) return null;
  return Date.now() < row.expires_at ? row.expires_at : null;
}

function grantedResponse(env, expiresAt, origin) {
  return json({ status: "approved", secret: env.GATE_PASSWORD, expiresAt }, 200, origin);
}

async function countSince(env, column, value, since) {
  const row = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM requests WHERE ${column} = ?1 AND created_at > ?2`
  ).bind(value, since).first();
  return row ? row.n : 0;
}

// Pushover's reply is the ONLY evidence that a notification went anywhere,
// and it is exactly what changes when the phone does: a handset wiped and not
// re-registered, a re-created account with a different user key, a group key
// whose only device is gone -- all of it comes back here as a rejection.
//
// The first version awaited this fetch and discarded the result, so a dead
// push channel was indistinguishable from a working one: the request was
// stored, the visitor was told "pending", and no one was ever told. Return the
// outcome so it can be recorded and shown, and never throw -- a notification
// that could not be sent is not a reason to fail the visitor's request. The
// /admin page is the backstop, and /admin/push-test is how you check the
// channel without waiting for a stranger to trip it.
async function postToPushover(env, fields) {
  if (!env.PUSHOVER_TOKEN || !env.PUSHOVER_USER) {
    return { ok: false, detail: "PUSHOVER_TOKEN and/or PUSHOVER_USER are not set on this Worker" };
  }
  const body = new URLSearchParams({
    token: env.PUSHOVER_TOKEN,
    user: env.PUSHOVER_USER,
    ...fields,
  });
  let res, text;
  try {
    res = await fetch("https://api.pushover.net/1/messages.json", {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body,
    });
    text = (await res.text()).slice(0, 400);
  } catch (err) {
    return { ok: false, detail: `could not reach Pushover: ${String((err && err.message) || err)}` };
  }
  let parsed = null;
  try { parsed = JSON.parse(text); } catch { /* keep the raw text below */ }
  if (res.ok && parsed && parsed.status === 1) return { ok: true, detail: "" };
  // Pushover puts the human-readable reason in `errors`; fall back to the raw
  // body so an unexpected shape is still diagnosable rather than swallowed.
  const why = parsed && Array.isArray(parsed.errors) && parsed.errors.length
    ? parsed.errors.join("; ")
    : (text || "(empty response)");
  return { ok: false, detail: `Pushover returned HTTP ${res.status}: ${why}` };
}

async function sendPushover(env, selfOrigin, email, requestId) {
  const approveUrl = `${selfOrigin}/approve?token=${requestId}`;
  const denyUrl = `${selfOrigin}/deny?token=${requestId}`;
  return await postToPushover(env, {
    title: "Case study access request",
    message:
      `<b>${esc(email)}</b> wants access to your gated case studies.<br><br>` +
      `<a href="${approveUrl}">Approve</a>  |  <a href="${denyUrl}">Deny</a>`,
    html: "1",
    url: approveUrl,
    url_title: "Approve",
  });
}

// State of the push channel, taken from the last request that tried to notify.
// "unknown" means nothing has been sent since this was deployed, which is not
// the same as healthy -- say so rather than showing a reassuring green.
async function pushHealth(env) {
  if (!env.PUSHOVER_TOKEN || !env.PUSHOVER_USER) {
    return { state: "unconfigured", detail: "PUSHOVER_TOKEN and/or PUSHOVER_USER are not set on this Worker", at: null };
  }
  const row = await env.DB.prepare(
    `SELECT created_at, notified_at, notify_error FROM requests
      WHERE notified_at IS NOT NULL OR notify_error IS NOT NULL
      ORDER BY created_at DESC, rowid DESC LIMIT 1`
  ).first();
  if (!row) return { state: "unknown", detail: "no notification has been attempted yet", at: null };
  if (row.notify_error) return { state: "failing", detail: row.notify_error, at: row.created_at };
  return { state: "ok", detail: "", at: row.notified_at };
}

async function handleRequestAccess(req, env) {
  const origin = env.ALLOWED_ORIGIN;
  let payload;
  try {
    payload = await req.json();
  } catch {
    return json({ error: "bad_request" }, 400, origin);
  }
  const email = String(payload.email || "").trim().toLowerCase();
  if (!EMAIL_RE.test(email) || email.length > 254) {
    return json({ error: "invalid_email" }, 400, origin);
  }

  // Log the address first: a repeat visitor who already has access, or one
  // who trips the rate limit, is still a contact worth keeping.
  await env.DB.prepare(
    `INSERT INTO contacts (email, first_seen, last_seen, hits) VALUES (?1, ?2, ?2, 1)
     ON CONFLICT(email) DO UPDATE SET last_seen = ?2, hits = hits + 1`
  ).bind(email, Date.now()).run();

  const grant = await activeGrant(env, email);
  if (grant) return grantedResponse(env, grant, origin);

  const ip = req.headers.get("CF-Connecting-IP") || "unknown";
  const since = Date.now() - RATE_WINDOW_MS;
  if (await countSince(env, "ip", ip, since) >= RATE_MAX_PER_IP) {
    return json({ error: "rate_limited" }, 429, origin);
  }
  if (await countSince(env, "email", email, since) >= RATE_MAX_PER_EMAIL) {
    return json({ error: "rate_limited" }, 429, origin);
  }

  const requestId = crypto.randomUUID();
  await env.DB.prepare(
    "INSERT INTO requests (id, email, status, ip, created_at) VALUES (?1, ?2, 'pending', ?3, ?4)"
  ).bind(requestId, email, ip, Date.now()).run();

  // Stored before the notification is attempted, so the Approve link works
  // even if the visitor's row and the push race each other.
  const push = await sendPushover(env, new URL(req.url).origin, email, requestId);
  await env.DB.prepare(
    "UPDATE requests SET notified_at = ?1, notify_error = ?2 WHERE id = ?3"
  ).bind(push.ok ? Date.now() : null, push.ok ? null : push.detail, requestId).run();

  // Still "pending" either way: the request is genuinely waiting on a
  // decision, and a visitor cannot act on the owner's broken phone.
  return json({ status: "pending", requestId }, 200, origin);
}

async function handleCheckAccess(req, env) {
  const origin = env.ALLOWED_ORIGIN;
  const requestId = new URL(req.url).searchParams.get("requestId") || "";
  const row = await env.DB.prepare(
    "SELECT email, status, created_at FROM requests WHERE id = ?1"
  ).bind(requestId).first();

  if (!row) return json({ status: "expired" }, 200, origin);
  if (row.status === "approved") {
    // Approved, but the 4-hour window may have already run out.
    const grant = await activeGrant(env, row.email);
    return grant ? grantedResponse(env, grant, origin) : json({ status: "expired" }, 200, origin);
  }
  if (row.status === "denied") return json({ status: "denied" }, 200, origin);
  if (Date.now() - row.created_at > PENDING_TTL_MS) {
    return json({ status: "expired" }, 200, origin);
  }
  return json({ status: "pending" }, 200, origin);
}

async function handleCheckEmail(req, env) {
  const origin = env.ALLOWED_ORIGIN;
  const email = (new URL(req.url).searchParams.get("email") || "").trim().toLowerCase();
  if (!EMAIL_RE.test(email)) return json({ status: "none" }, 200, origin);
  const grant = await activeGrant(env, email);
  return grant ? grantedResponse(env, grant, origin) : json({ status: "none" }, 200, origin);
}

async function handleDecision(req, env, decision) {
  const url = new URL(req.url);
  const token = url.searchParams.get("token") || "";
  // Came from the admin list (which passes the key through)? Go back to it
  // so several requests can be worked through in a row.
  const backToAdmin = adminAuthed(url, env)
    ? `/admin?key=${encodeURIComponent(url.searchParams.get("key"))}`
    : null;
  const row = await env.DB.prepare(
    "SELECT email, status FROM requests WHERE id = ?1"
  ).bind(token).first();

  if (!row) {
    if (backToAdmin) return Response.redirect(new URL(backToAdmin, url).toString(), 302);
    return html(`<h1>Nothing to do</h1><p>This request has expired or was already cleaned up.</p>`, 410);
  }
  if (row.status !== "pending") {
    if (backToAdmin) return Response.redirect(new URL(backToAdmin, url).toString(), 302);
    return html(`<h1>Already ${esc(row.status)}</h1><p><b>${esc(row.email)}</b> was already ${esc(row.status)}.</p>`, 409);
  }

  const now = Date.now();
  const writes = [
    env.DB.prepare("UPDATE requests SET status = ?1, decided_at = ?2 WHERE id = ?3")
      .bind(decision, now, token),
    // Housekeeping, piggybacked on a rare request so it never needs a cron.
    env.DB.prepare("DELETE FROM requests WHERE created_at < ?1").bind(now - PURGE_AFTER_MS),
  ];
  if (decision === "approved") {
    writes.push(
      env.DB.prepare(
        `INSERT INTO approved (email, created_at, expires_at) VALUES (?1, ?2, ?3)
         ON CONFLICT(email) DO UPDATE SET expires_at = excluded.expires_at`
      ).bind(row.email, now, now + ACCESS_TTL_MS)
    );
  }
  await env.DB.batch(writes);

  if (backToAdmin) return Response.redirect(new URL(backToAdmin, url).toString(), 302);

  if (decision === "approved") {
    const hours = Math.round(ACCESS_TTL_MS / 3600000);
    return html(`<h1>Approved</h1><p><b>${esc(row.email)}</b> can now open every gated case study for the next ${hours} hours. Their browser unlocks within a second.</p>`);
  }
  return html(`<h1>Denied</h1><p>Request from <b>${esc(row.email)}</b> was denied.</p>`);
}


// ---- admin ---------------------------------------------------------------
// Guarded by a secret in the query string. That is enough for a bookmark on
// one person's phone, but it does mean anyone holding the link can read every
// address collected -- treat it like a password, and rotate ADMIN_KEY if it
// ever leaks. The page is marked noindex and never linked from anywhere.
function adminAuthed(url, env) {
  const key = url.searchParams.get("key") || "";
  return !!env.ADMIN_KEY && key === env.ADMIN_KEY;
}

function adminPage(body, status = 200) {
  return new Response(
    `<!doctype html><meta charset="utf-8">
     <meta name="viewport" content="width=device-width,initial-scale=1">
     <meta name="robots" content="noindex,nofollow">
     <title>Access requests</title>
     <style>
       :root{color-scheme:light dark}
       body{font:15px/1.5 -apple-system,system-ui,sans-serif;margin:0;padding:1.25rem;
         max-width:60rem;margin-inline:auto;color:#111;background:#fff}
       @media (prefers-color-scheme:dark){body{background:#111;color:#eee}
         td,th{border-color:#333 !important}.card{background:#1a1a1a !important;border-color:#333 !important}
         a{color:#6ea8fe}}
       h1{font-size:1.3rem;margin:0 0 .25rem}
       .sub{color:#777;margin:0 0 1.25rem;font-size:.85rem}
       .row{display:flex;gap:.75rem;flex-wrap:wrap;margin-bottom:1.5rem}
       .card{flex:1 1 8rem;padding:.75rem .9rem;border:1px solid #e5e5e5;border-radius:10px;background:#fafafa}
       .card b{display:block;font-size:1.5rem;line-height:1.2}
       .card span{color:#777;font-size:.8rem}
       h2{font-size:1rem;margin:1.75rem 0 .6rem}
       table{width:100%;border-collapse:collapse;font-size:.85rem}
       th,td{text-align:left;padding:.5rem .4rem;border-bottom:1px solid #eee;vertical-align:top}
       th{color:#777;font-weight:600;font-size:.75rem;text-transform:uppercase;letter-spacing:.04em}
       td.email{word-break:break-all;font-weight:500}
       .wrap{overflow-x:auto}
       .pill{display:inline-block;padding:.1rem .45rem;border-radius:999px;font-size:.72rem;font-weight:600}
       .ok{background:#e7f7ed;color:#0a7038}.no{background:#eee;color:#666}
       .btn{display:inline-block;padding:.3rem .7rem;border-radius:7px;text-decoration:none;
         font-size:.8rem;font-weight:600;margin-right:.3rem}
       .approve{background:#0a7038;color:#fff}.deny{background:#eee;color:#333}
       .test{background:#e5e5e5;color:#111;border:1px solid #ccc}
       .banner{padding:.8rem .9rem;border-radius:10px;margin:0 0 1.25rem;border:1px solid}
       .banner b{display:block;margin-bottom:.2rem}
       .banner code{word-break:break-all;font:12px/1.5 ui-monospace,monospace}
       .banner p{margin:.4rem 0 0}
       .bad{background:#fdeaea;border-color:#f0b4b4;color:#7d1414}
       .warn2{background:#fdf5e2;border-color:#e8d69a;color:#6b5310}
       .good{background:#e7f7ed;border-color:#a9dfc0;color:#0a7038}
       @media (prefers-color-scheme:dark){
         .bad{background:#3a1414;border-color:#7d2b2b;color:#ffb4b4}
         .warn2{background:#3a3212;border-color:#7d6f2b;color:#f3dd94}
         .good{background:#0f2e1c;border-color:#2b7d4e;color:#9fe0bb}
         .test{background:#2a2a2a;color:#eee;border-color:#444}}
       textarea{width:100%;height:6rem;font:12px/1.5 ui-monospace,monospace;padding:.6rem;
         border:1px solid #ddd;border-radius:8px;background:#fafafa;color:inherit}
       .empty{color:#888;font-style:italic}
     </style>${body}`,
    { status, headers: { "content-type": "text/html; charset=utf-8",
                         "cache-control": "no-store", "x-robots-tag": "noindex" } }
  );
}

// The banner that would have told you the phone reset had broken this,
// instead of you finding out some other way.
function pushBanner(health, key) {
  const test = `<a class="btn test" href="/admin/push-test?key=${key}">Send a test notification</a>`;
  if (health.state === "ok") {
    return `<div class="banner good"><b>Push notifications are working</b>
      Last one delivered ${esc(ago(health.at))}. ${test}</div>`;
  }
  if (health.state === "unknown") {
    return `<div class="banner warn2"><b>Push notifications: not verified</b>
      Nothing has been sent yet, so there is no evidence either way. ${test}</div>`;
  }
  const fix = health.state === "unconfigured"
    ? `<p>Set both secrets under Worker &rarr; Settings &rarr; Variables, ticking Encrypt.</p>`
    : `<p>Usually the phone: install Pushover on it and sign in to the same
       account, then confirm the device is listed at
       <a href="https://pushover.net/">pushover.net</a>. If you created a new
       account, copy the new user key into the <code>PUSHOVER_USER</code>
       secret on this Worker. Re-test with the button above.</p>`;
  return `<div class="banner bad"><b>Push notifications are NOT being delivered</b>
    Requests still land on this page, but nothing reaches your phone.
    ${test}
    <p><code>${esc(health.detail)}</code></p>${fix}</div>`;
}

async function handleAdmin(url, env) {
  const key = encodeURIComponent(url.searchParams.get("key") || "");
  const now = Date.now();

  const health = await pushHealth(env);

  const pending = (await env.DB.prepare(
    `SELECT id, email, created_at, notified_at, notify_error FROM requests
      WHERE status = 'pending' AND created_at > ?1 ORDER BY created_at DESC`
  ).bind(now - PENDING_TTL_MS).all()).results || [];

  const contacts = (await env.DB.prepare(
    `SELECT c.email, c.first_seen, c.last_seen, c.hits, a.expires_at
       FROM contacts c LEFT JOIN approved a ON a.email = c.email
      ORDER BY c.last_seen DESC`
  ).all()).results || [];

  const live = contacts.filter((c) => c.expires_at && c.expires_at > now).length;

  const pendingRows = pending.length
    ? pending.map((r) => `<tr>
        <td class="email">${esc(r.email)}</td>
        <td>${esc(ago(r.created_at))}${r.notify_error
              ? ` <span class="pill no" title="${esc(r.notify_error)}">not pushed</span>` : ""}</td>
        <td>
          <a class="btn approve" href="/approve?token=${encodeURIComponent(r.id)}&key=${key}">Approve</a>
          <a class="btn deny" href="/deny?token=${encodeURIComponent(r.id)}&key=${key}">Deny</a>
        </td></tr>`).join("")
    : `<tr><td colspan="3" class="empty">Nothing waiting.</td></tr>`;

  const contactRows = contacts.length
    ? contacts.map((c) => `<tr>
        <td class="email">${esc(c.email)}</td>
        <td>${c.expires_at && c.expires_at > now
              ? `<span class="pill ok">${esc(inFuture(c.expires_at))}</span>`
              : `<span class="pill no">no access</span>`}</td>
        <td>${esc(ago(c.last_seen))}</td>
        <td>${esc(ago(c.first_seen))}</td>
        <td>${esc(c.hits)}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">No one has asked yet.</td></tr>`;

  return adminPage(`
    <h1>Access requests</h1>
    <p class="sub">Everyone who has entered their email on a gated case study.</p>
    ${pushBanner(health, key)}
    <div class="row">
      <div class="card"><b>${contacts.length}</b><span>emails collected</span></div>
      <div class="card"><b>${pending.length}</b><span>waiting on you</span></div>
      <div class="card"><b>${live}</b><span>with access now</span></div>
    </div>

    <h2>Waiting for approval</h2>
    <div class="wrap"><table>
      <tr><th>Email</th><th>Asked</th><th></th></tr>${pendingRows}
    </table></div>

    <h2>All emails collected</h2>
    <div class="wrap"><table>
      <tr><th>Email</th><th>Access</th><th>Last seen</th><th>First seen</th><th>Times</th></tr>
      ${contactRows}
    </table></div>

    <h2>Copy them all</h2>
    <textarea readonly onclick="this.select()">${esc(contacts.map((c) => c.email).join(", "))}</textarea>
    <p class="sub" style="margin-top:.6rem">
      <a href="/admin/emails.csv?key=${key}">Download CSV</a>
    </p>`);
}

// Prove the channel end to end without waiting for a stranger to trip it:
// tap this on the phone you want the alerts on, and either it buzzes or you
// get the exact reason it did not.
async function handleAdminPushTest(url, env) {
  const key = encodeURIComponent(url.searchParams.get("key") || "");
  const back = `<p class="sub" style="margin-top:1rem"><a href="/admin?key=${key}">Back to access requests</a></p>`;
  const res = await postToPushover(env, {
    title: "Push test",
    message: "If you can read this, case-study access alerts reach this device.",
  });
  if (res.ok) {
    return adminPage(`
      <h1>Test sent</h1>
      <div class="banner good"><b>Pushover accepted the message</b>
        It should be on your phone now. If it is not, the account is fine but this
        handset is not registered to it &mdash; open Pushover on the phone, sign in,
        and check the device appears at <a href="https://pushover.net/">pushover.net</a>.</div>
      ${back}`);
  }
  return adminPage(`
    <h1>Test failed</h1>
    <div class="banner bad"><b>Nothing was delivered</b>
      <p><code>${esc(res.detail)}</code></p>
      <p>If that mentions the user key, the <code>PUSHOVER_USER</code> secret on
      this Worker no longer matches your account &mdash; copy the current user key
      from <a href="https://pushover.net/">pushover.net</a> into it. If it mentions
      the application token, do the same for <code>PUSHOVER_TOKEN</code>. If it
      mentions devices, the account has none registered: install Pushover on the
      phone and sign in.</p></div>
    ${back}`, 502);
}

async function handleAdminCsv(url, env) {
  const rows = (await env.DB.prepare(
    `SELECT c.email, c.first_seen, c.last_seen, c.hits, a.expires_at
       FROM contacts c LEFT JOIN approved a ON a.email = c.email
      ORDER BY c.last_seen DESC`
  ).all()).results || [];
  const iso = (t) => (t ? new Date(t).toISOString() : "");
  const cell = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
  const csv = ["email,first_seen,last_seen,times_asked,access_expires"]
    .concat(rows.map((r) =>
      [r.email, iso(r.first_seen), iso(r.last_seen), r.hits, iso(r.expires_at)].map(cell).join(",")))
    .join("\n");
  return new Response(csv, {
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": 'attachment; filename="case-study-emails.csv"',
      "cache-control": "no-store",
    },
  });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const origin = env.ALLOWED_ORIGIN;

    if (req.method === "OPTIONS") {
      // A 204 must not carry a body: constructing one with a body throws,
      // which surfaces as a 500 on the CORS preflight and kills every request.
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    // Surfaces a missing/misnamed binding as a clear message instead of a
    // mystery 500 the next person has to reverse-engineer.
    if (!env.DB) {
      return json({ error: "misconfigured", detail: "D1 binding 'DB' is not set on this Worker" }, 503, origin);
    }

    if (url.pathname === "/health") {
      return json({ ok: true, storage: "d1", accessTtlHours: ACCESS_TTL_MS / 3600000,
                    adminConfigured: !!env.ADMIN_KEY,
                    pushConfigured: !!(env.PUSHOVER_TOKEN && env.PUSHOVER_USER) }, 200, origin);
    }

    try {
      await ensureSchema(env);
      if (url.pathname === "/request-access" && req.method === "POST") {
        return await handleRequestAccess(req, env);
      }
      if (url.pathname === "/check-access" && req.method === "GET") {
        return await handleCheckAccess(req, env);
      }
      if (url.pathname === "/check-email" && req.method === "GET") {
        return await handleCheckEmail(req, env);
      }
      if (url.pathname === "/approve" && req.method === "GET") {
        return await handleDecision(req, env, "approved");
      }
      if (url.pathname === "/deny" && req.method === "GET") {
        return await handleDecision(req, env, "denied");
      }
      if (url.pathname === "/admin" || url.pathname === "/admin/emails.csv"
          || url.pathname === "/admin/push-test") {
        if (!env.ADMIN_KEY) {
          return adminPage(`<h1>Not configured</h1><p class="sub">Set an ADMIN_KEY secret on this Worker to use this page.</p>`, 503);
        }
        if (!adminAuthed(url, env)) {
          return adminPage(`<h1>Not found</h1>`, 404);
        }
        if (url.pathname === "/admin") return await handleAdmin(url, env);
        if (url.pathname === "/admin/push-test") return await handleAdminPushTest(url, env);
        return await handleAdminCsv(url, env);
      }
    } catch (err) {
      return json({ error: "server_error", detail: String(err && err.message || err) }, 500, origin);
    }
    return new Response("Not found", { status: 404 });
  },
};
