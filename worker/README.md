# Case-study access-request Worker

Backs the "request access" flow on gated case studies: a visitor submits
their email, you get a push notification with Approve/Deny, and approval is
global — that email can open every gated case study from then on.

The gate itself is unchanged (AES-256-GCM, decrypted client-side); this
Worker only decides who is handed the gate password.

## One-time setup

1. **Install wrangler** (if you don't have it): `npm install -g wrangler`
2. **Log in**: `wrangler login`
3. **Create the KV namespace**:
   ```
   wrangler kv:namespace create CS_ACCESS
   ```
   Copy the returned `id` into `wrangler.toml` (`REPLACE_WITH_KV_NAMESPACE_ID`).
4. **Set secrets** (from `worker/`):
   ```
   wrangler secret put GATE_PASSWORD   # must exactly match CS_GATE_PW used by build.py
   wrangler secret put PUSHOVER_TOKEN  # Pushover application token
   wrangler secret put PUSHOVER_USER   # Pushover user/group key
   ```
5. **Set `ALLOWED_ORIGIN`** in `wrangler.toml` to your live site origin
   (already set to `https://thepurvangmehta.com`).
6. **Deploy**: `wrangler deploy`
7. Note the deployed Worker URL (e.g. `https://case-study-access.<subdomain>.workers.dev`).

## Wiring it into the site build

Set `CS_ACCESS_API_URL` to the Worker URL when building, alongside `CS_GATE_PW`:

```
CS_GATE_PW='your-password' CS_ACCESS_API_URL='https://case-study-access.<subdomain>.workers.dev' python3 build.py
```

If `CS_ACCESS_API_URL` is unset, the build falls back to the password-only
gate (no email-request UI is rendered) — safe default before the Worker
exists or if it's ever taken down.

`GATE_PASSWORD` (the Worker secret) and `CS_GATE_PW` (the build-time env var)
**must be the same string** — the Worker hands this password back to
approved browsers, which then run the exact same client-side decrypt path
as someone who typed it manually.

## Pushover setup

1. Create a free account at pushover.net, install the app on your phone.
2. Create an "Application/API Token" in the Pushover dashboard — that's `PUSHOVER_TOKEN`.
3. Your user key (shown on the Pushover dashboard homepage) is `PUSHOVER_USER`.
4. One-time ~$5 purchase for the mobile app (Pushover's own pricing, not Cloudflare's).

## Notes / operational tradeoffs

- **Global + permanent grant.** Approving one email grants access to every
  gated case study, forever. There's no revoke UI yet — to revoke, delete
  the `approved:<email>` key from KV manually (`wrangler kv:key delete
  --namespace-id=<id> "approved:someone@example.com"`).
- **Rate limits**: 20 requests/hour per IP, 5/hour per email address, to
  keep this from becoming a notification-spam vector. Tune in `src/index.js`.
- **No CI/CD wired up** — redeploy manually with `wrangler deploy` after any
  change to `src/index.js`.
