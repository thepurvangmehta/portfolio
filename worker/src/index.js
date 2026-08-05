// Case-study access-request Worker.
//
// Flow:
//   1. Visitor POSTs their email to /request-access.
//   2. If that email is already globally approved, the gate password ships
//      back immediately and the browser decrypts as usual.
//   3. Otherwise a pending request is stored in KV and a Pushover
//      notification is sent with Approve/Deny links.
//   4. The browser polls /check-access until the request is approved,
//      denied, or expires (24h).
//   5. Tapping Approve/Deny in the notification hits /approve or /deny,
//      which resolves the pending request. Approval is global and
//      permanent — that email can access every gated case study from then on.
//
// Required secrets (wrangler secret put <name>):
//   GATE_PASSWORD   - must match CS_GATE_PW used by build.py
//   PUSHOVER_TOKEN  - Pushover application token
//   PUSHOVER_USER   - Pushover user/group key
// Required vars (wrangler.toml [vars]):
//   ALLOWED_ORIGIN  - the site origin allowed to call /request-access via fetch

const PENDING_TTL = 60 * 60 * 24; // 24h
const DECISION_TTL = 60 * 60; // 1h to let a slow poller catch the result
const RATE_LIMIT_WINDOW = 60 * 60; // 1h
const RATE_LIMIT_MAX_PER_IP = 20;
const RATE_LIMIT_MAX_PER_EMAIL = 5;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function json(data, status = 200, origin) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json",
      "access-control-allow-origin": origin || "*",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-allow-headers": "content-type",
    },
  });
}

function html(body, status = 200) {
  return new Response(
    `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body{font:16px/1.5 -apple-system,system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1.25rem;color:#111}</style>
    ${body}`,
    { status, headers: { "content-type": "text/html; charset=utf-8" } }
  );
}

async function rateLimited(env, key, max) {
  const cur = parseInt((await env.CS_ACCESS.get(key)) || "0", 10);
  if (cur >= max) return true;
  await env.CS_ACCESS.put(key, String(cur + 1), { expirationTtl: RATE_LIMIT_WINDOW });
  return false;
}

async function sendPushover(env, origin, email, requestId) {
  const approveUrl = `${origin}/approve?token=${requestId}`;
  const denyUrl = `${origin}/deny?token=${requestId}`;
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

  const ip = req.headers.get("CF-Connecting-IP") || "unknown";
  if (await rateLimited(env, `rl:ip:${ip}`, RATE_LIMIT_MAX_PER_IP)) {
    return json({ error: "rate_limited" }, 429, origin);
  }
  if (await rateLimited(env, `rl:email:${email}`, RATE_LIMIT_MAX_PER_EMAIL)) {
    return json({ error: "rate_limited" }, 429, origin);
  }

  const already = await env.CS_ACCESS.get(`approved:${email}`);
  if (already) {
    return json({ status: "approved", secret: env.GATE_PASSWORD }, 200, origin);
  }

  const requestId = crypto.randomUUID();
  await env.CS_ACCESS.put(
    `pending:${requestId}`,
    JSON.stringify({ email, createdAt: Date.now() }),
    { expirationTtl: PENDING_TTL }
  );

  const selfOrigin = new URL(req.url).origin;
  await sendPushover(env, selfOrigin, email, requestId);

  return json({ status: "pending", requestId }, 200, origin);
}

async function handleCheckAccess(req, env) {
  const origin = env.ALLOWED_ORIGIN;
  const requestId = new URL(req.url).searchParams.get("requestId") || "";
  const decision = await env.CS_ACCESS.get(`decision:${requestId}`);
  if (decision) {
    const d = JSON.parse(decision);
    if (d.status === "approved") {
      return json({ status: "approved", secret: env.GATE_PASSWORD }, 200, origin);
    }
    return json({ status: "denied" }, 200, origin);
  }
  const pending = await env.CS_ACCESS.get(`pending:${requestId}`);
  if (pending) return json({ status: "pending" }, 200, origin);
  return json({ status: "expired" }, 200, origin);
}

async function handleCheckEmail(req, env) {
  const origin = env.ALLOWED_ORIGIN;
  const email = (new URL(req.url).searchParams.get("email") || "").trim().toLowerCase();
  if (!EMAIL_RE.test(email)) return json({ status: "none" }, 200, origin);
  const approved = await env.CS_ACCESS.get(`approved:${email}`);
  if (approved) return json({ status: "approved", secret: env.GATE_PASSWORD }, 200, origin);
  return json({ status: "none" }, 200, origin);
}

async function handleDecision(req, env, decisionStatus) {
  const token = new URL(req.url).searchParams.get("token") || "";
  const pendingRaw = await env.CS_ACCESS.get(`pending:${token}`);
  if (!pendingRaw) {
    return html(`<h1>Already handled</h1><p>This request has expired or was already resolved.</p>`, 410);
  }
  const { email } = JSON.parse(pendingRaw);
  await env.CS_ACCESS.delete(`pending:${token}`);
  await env.CS_ACCESS.put(
    `decision:${token}`,
    JSON.stringify({ status: decisionStatus }),
    { expirationTtl: DECISION_TTL }
  );
  if (decisionStatus === "approved") {
    await env.CS_ACCESS.put(`approved:${email}`, "1");
    return html(`<h1>Approved</h1><p><b>${email}</b> can now access every gated case study.</p>`);
  }
  return html(`<h1>Denied</h1><p>Request from <b>${email}</b> was denied.</p>`);
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const origin = env.ALLOWED_ORIGIN;

    if (req.method === "OPTIONS") {
      return json({}, 204, origin);
    }

    if (url.pathname === "/request-access" && req.method === "POST") {
      return handleRequestAccess(req, env);
    }
    if (url.pathname === "/check-access" && req.method === "GET") {
      return handleCheckAccess(req, env);
    }
    if (url.pathname === "/check-email" && req.method === "GET") {
      return handleCheckEmail(req, env);
    }
    if (url.pathname === "/approve" && req.method === "GET") {
      return handleDecision(req, env, "approved");
    }
    if (url.pathname === "/deny" && req.method === "GET") {
      return handleDecision(req, env, "denied");
    }
    return new Response("Not found", { status: 404 });
  },
};
