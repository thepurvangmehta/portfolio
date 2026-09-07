# Case-study access-request Worker

Backs the "request access" option on gated case studies: a visitor submits
their email, you get a push notification with Approve/Deny, and approval is
global, one tap unlocks every gated case study for that address from then on.

The gate itself is unchanged (AES-256-GCM, decrypted in the browser); this
Worker only decides who gets handed the gate password.

## Why D1 and not KV

The first version stored state in Workers KV and felt broken: approvals took
30-60 seconds to show up. KV edge-caches reads for a **minimum of 60 seconds,
including cache misses**, so the browser polling "approved yet?" kept being
served a stale "not yet" long after the approval had actually been written.

D1 is strongly consistent, so an approval is visible on the very next poll.
Measured end to end: ~800ms when the tab is focused, under 150ms when you
approve on your phone and switch back (the page re-checks on regaining focus).

**Do not move this state back to KV.** Polling for a flag to flip is exactly
the workload KV's caching model is wrong for.

## Setup

1. **Create the database.** Cloudflare dashboard, Storage & Databases, D1,
   Create database, name it `cs-access`.
2. **Bind it.** Worker, Settings, Bindings, add a **D1 database** binding with
   variable name `DB` pointing at `cs-access`. The variable name must be
   exactly `DB`.
3. **Set secrets** (Settings, Variables, tick Encrypt on all four):
   - `GATE_PASSWORD` - must exactly match `CS_GATE_PW` used by `build.py`
   - `PUSHOVER_TOKEN` - Pushover application token
   - `PUSHOVER_USER` - Pushover user/group key
   - `ADMIN_KEY` - any long random string; it is the password to the
     collected-email page below
4. **Set the plain var** `ALLOWED_ORIGIN` to `https://thepurvangmehta.com`.
5. **Deploy** the code in `src/index.js` (paste it into the dashboard editor,
   or `wrangler deploy` from this directory).

Tables are created automatically on first request, there is no migration step.

Check it worked by visiting `https://<your-worker>.workers.dev/health`, which
should return `{"ok":true,"storage":"d1",...}`. If `DB` is missing you get a
`503 misconfigured` with a message saying so, rather than a mystery 500.

## Wiring it into the site build

Set `CS_ACCESS_API_URL` alongside `CS_GATE_PW` when building. `deploy.sh`
prompts for it once and caches it in `.access_api_url`.

If `CS_ACCESS_API_URL` is unset the build falls back to a password-only gate
with no email-request UI, which is the safe default if the Worker is ever
taken down.

## Seeing who has asked

`https://<your-worker>.workers.dev/admin?key=<ADMIN_KEY>`

Every address ever entered on a gated case study, when it was first and last
seen, how many times, whether it currently has access, plus Approve/Deny
buttons for anything waiting and a CSV export. Bookmark it.

Two things to know:

- **The link is the password.** Anyone who has it can read every address
  collected. Don't paste it into a shared doc or a screenshot. If it leaks,
  change `ADMIN_KEY` in the dashboard and the old link dies.
- **Addresses are kept indefinitely**, in a `contacts` table separate from the
  operational `requests` rows (which are purged after 7 days). That is the
  point of the page, but it does mean you are holding personal data from
  visitors, so the privacy policy should say you collect it and why. Delete
  one with:
  `wrangler d1 execute cs-access --command "DELETE FROM contacts WHERE email='x@y.com'"`

## Endpoints

| Route | Purpose |
|---|---|
| `POST /request-access` | `{email}` -> `{status:"pending",requestId}` or `{status:"approved",secret}` |
| `GET /check-access?requestId=` | poll target: `pending` / `approved` / `denied` / `expired` |
| `GET /check-email?email=` | has this address already been approved |
| `GET /approve?token=` | the Approve link in the push notification |
| `GET /deny?token=` | the Deny link |
| `GET /admin?key=` | collected emails, pending approvals, push status, CSV link |
| `GET /admin/emails.csv?key=` | CSV export of every address |
| `GET /admin/push-test?key=` | sends a real notification and shows what Pushover said |
| `GET /health` | binding sanity check |

## When notifications stop (new phone, reinstalled app, new account)

Delivery depends on `PUSHOVER_USER` still naming an account that has at least
one registered device. Wiping a phone does not change the user key, but it does
un-register that handset, and signing up again rather than signing back in
gives you a **different** key while the Worker keeps sending to the old one.

Either way the symptom is the same and it used to be silent: requests kept
being accepted and stored, visitors kept being told "pending", and nothing
reached you. The Worker now records what Pushover said about every
notification, so:

1. Open `/admin?key=<ADMIN_KEY>`. The banner at the top says whether the last
   notification was delivered, and prints Pushover's own reason if it was not.
   Anything waiting is still listed with Approve/Deny, so nobody is stuck while
   push is down.
2. Tap **Send a test notification** on the phone you want the alerts on. Either
   it buzzes or you get the exact error.
3. Fix per the error:
   - *not a valid user / group key* -> the account behind `PUSHOVER_USER` is
     gone or was re-created. Copy the current user key from
     [pushover.net](https://pushover.net/) into the `PUSHOVER_USER` secret.
   - *no active devices* -> the account is right but no handset is registered.
     Install Pushover on the phone, sign in to that account, confirm the device
     appears on the site.
   - *application token is invalid* -> same, for `PUSHOVER_TOKEN`.
   - *could not reach Pushover* -> transient; re-test.
4. Re-test until the banner is green. `/health` also reports `pushConfigured`,
   which only tells you the secrets are set, not that they still work — the
   banner and the test are what actually prove delivery.

Changing a secret takes effect immediately; no redeploy is needed.

**The admin page is the fallback channel.** Push is a convenience, not the
system of record — every request is in D1 whether or not the notification
landed, which is why a dead phone can never lose one.

## Operational notes

- **An approval is global but time-limited**: it opens every gated case study
  for 4 hours (`ACCESS_TTL_MS`), then they have to ask again. Approving the
  same address again just resets the window. To revoke early:
  `wrangler d1 execute cs-access --command "DELETE FROM approved WHERE email='someone@example.com'"`
  Note this only stops them re-entering; a page already decrypted in someone's
  browser stays readable, which is inherent to a static site.
- **Rate limits**: 20 requests/hour per IP, 5/hour per email address, counted
  in SQL against the `requests` table. Tune the constants in `src/index.js`.
- **Housekeeping** is piggybacked onto approve/deny: rows older than 7 days are
  deleted, so no cron job is needed.
- **A failed notification never fails the request.** `sendPushover` returns its
  outcome instead of throwing it away, and the caller records it on the request
  row (`notified_at` / `notify_error`). Do not go back to ignoring that
  response: it is the only evidence the channel works, and without it a broken
  phone looks exactly like a quiet week.
- **Tests**: the handler logic is covered end to end against real SQLite via
  `node:sqlite`, including the CORS-preflight regression that once broke the
  whole flow, and the dead-push-channel cases. Run them with
  `node worker/test/worker.test.mjs` before changing this file.
