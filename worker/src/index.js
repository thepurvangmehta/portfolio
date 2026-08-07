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
         decided_at INTEGER
       )`
    ),
    env.DB.prepare(
      `CREATE TABLE IF NOT EXISTS approved (
         email TEXT PRIMARY KEY,
         created_at INTEGER NOT NULL,
         expires_at INTEGER
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

async function sendPushover(env, selfOrigin, email, requestId) {
  const approveUrl = `${selfOrigin}/approve?token=${requestId}`;
  const denyUrl = `${selfOrigin}/deny?token=${requestId}`;
  const body = new URLSearchParams({
    token: env.PUSHOVER_TOKEN,
    user: env.PUSHOVER_USER,
    title: "Case study access request",
    message:
      `<b>${email}</b> wants access to your gated case studies.<br><br>` +
      `<a href="${approveUrl}">Approve</a>  |  <a href="${denyUrl}">Deny</a>`,
    html: "1",
    url: approveUrl,
    url_title: "Approve",
  });
  await fetch("https://api.pushover.net/1/messages.json", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body,
  });
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

  await sendPushover(env, new URL(req.url).origin, email, requestId);
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
  const token = new URL(req.url).searchParams.get("token") || "";
  const row = await env.DB.prepare(
    "SELECT email, status FROM requests WHERE id = ?1"
  ).bind(token).first();

  if (!row) {
    return html(`<h1>Nothing to do</h1><p>This request has expired or was already cleaned up.</p>`, 410);
  }
  if (row.status !== "pending") {
    return html(`<h1>Already ${row.status}</h1><p><b>${row.email}</b> was already ${row.status}.</p>`, 409);
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

  if (decision === "approved") {
    const hours = Math.round(ACCESS_TTL_MS / 3600000);
    return html(`<h1>Approved</h1><p><b>${row.email}</b> can now open every gated case study for the next ${hours} hours. Their browser unlocks within a second.</p>`);
  }
  return html(`<h1>Denied</h1><p>Request from <b>${row.email}</b> was denied.</p>`);
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
      return json({ ok: true, storage: "d1", accessTtlHours: ACCESS_TTL_MS / 3600000 }, 200, origin);
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
    } catch (err) {
      return json({ error: "server_error", detail: String(err && err.message || err) }, 500, origin);
    }
    return new Response("Not found", { status: 404 });
  },
};
