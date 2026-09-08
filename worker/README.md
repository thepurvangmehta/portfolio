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
3. **Set secrets** (Settings, Variables, tick Encrypt):
   - `GATE_PASSWORD` - must exactly match `CS_GATE_PW` used by `build.py`
   - `ADMIN_KEY` - any long random string; it is the password to the
     collected-email page below
   - `PUSHOVER_TOKEN` - application token from pushover.net
   - `PUSHOVER_USER` - your Pushover user key
   - `RESEND_TOKEN`, `NOTIFY_EMAIL_TO`, `NOTIFY_EMAIL_FROM` - *optional*, the
     email fallback. `NOTIFY_EMAIL_FROM` must be a verified Resend sender,
     e.g. `Access <access@thepurvangmehta.com>`.
4. **Set the plain var** `ALLOWED_ORIGIN` to `https://thepurvangmehta.com`.
5. **Register the phone**: install Pushover, sign in to that account, and
   confirm the device is listed at [pushover.net](https://pushover.net/).
6. **Deploy** the code in `src/index.js` (paste it into the dashboard editor,
   or `wrangler deploy` from this directory).
7. **Verify** at `/admin/notify-test?key=<ADMIN_KEY>`, from the phone.

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
| `GET /admin/notify-test?key=` | tests Pushover and email separately, shows what each said |
| `GET /admin/invite?key=&email=` | apologise to someone by email and grant them access |
| `GET /health` | binding sanity check |

## How you get told

Two independent channels, tried in order:

1. **Pushover** - the buzz on your phone, with Approve/Deny in the notification.
2. **Email via Resend** - the fallback, only used when Pushover fails. No app,
   no device registration, nothing to lose when a phone is replaced.

A fallback is only worth having if it cannot *hide* the primary's failure, so a
request delivered by email alone is recorded as delivered **and** as a Pushover
error, and `/admin` shows it amber rather than green. Silent degradation is the
failure mode this file exists to prevent.

### Why not ntfy (or anything else metered per IP)

This was tried and reverted. ntfy's free tier allows **250 messages per day per
IP address**, and a Cloudflare Worker has no IP of its own - outbound requests
share Cloudflare's address pool with every other customer's Worker. The quota
was already spent by strangers, so ntfy returned `HTTP 429 daily message quota
reached` on the *second* message ever sent. That would recur unpredictably
forever.

Pushover meters per account (10,000 messages/month free, and this Worker sends
single figures), so nobody else's traffic can starve it. **Before swapping in
any new provider, check how it meters.** Per-IP limits do not work from here.

## Inviting someone whose request never reached you

When notifications were broken, people asked and got nothing back. The **Invite**
button beside any contact without live access emails them an apology, tells them
to enter that same address on any locked case study, and grants it.

Two deliberate differences from a normal approval:

- **The mail goes first.** If it cannot be sent, no access is granted, because a
  grant to someone who was never told just makes the admin list lie about who
  can get in.
- **The window is 7 days** (`INVITE_TTL_MS`), not the usual 4 hours. An approval
  answers someone sitting on the page right now; an invite reaches someone who
  may open it tomorrow, and a window that expires before they read it is worse
  than not sending one.

It needs the email channel configured. Optional vars: `INVITE_URL` (where to
send them, default `ALLOWED_ORIGIN` + `/projects`) and `INVITE_SIGNATURE` (the
name it signs off with).

## When notifications stop

The likeliest cause is the phone: a wiped or reinstalled handset is
de-registered from Pushover, even though your user key never changes. Signing
back in on the phone is the whole fix - nothing server-side needs updating.
(Signing *up* again rather than in gives you a new user key, which does need
copying into `PUSHOVER_USER`.)

1. Open `/admin?key=<ADMIN_KEY>`. The banner says whether the last notification
   was delivered and by which channel, and prints the failure verbatim if not.
   Anything waiting is still listed with Approve/Deny, so nobody is stuck.
2. Hit **Test both channels** from the phone. Each is reported separately - the
   fallback working is not evidence that your phone does.
3. Fix per the error:
   - *Pushover failed, email worked* (amber banner) -> the phone. Re-install /
     sign back in, and check the device at pushover.net.
   - *not a valid user/group key* -> the account behind `PUSHOVER_USER` was
     re-created. Copy the current key from pushover.net into that secret.
   - *no active devices* -> account is right, no handset registered.
   - *application token is invalid* -> same, for `PUSHOVER_TOKEN`.
   - *Resend 403 / domain not verified* -> `NOTIFY_EMAIL_FROM` is not a verified
     sender on your Resend domain.
   - *could not reach ...* -> transient; re-test.
4. Re-test until the banner is green. A passing test counts as evidence and
   turns the banner green, labelled "last test" rather than "last one", so you
   never have to wait for a stranger to prove the channel works. `/health` lists
   `notifyChannels`, which only says what is configured, not that it works.

Changing a secret takes effect immediately; no redeploy is needed.

**The admin page is the real backstop.** Notifications are a convenience, not
the system of record - every request is in D1 whether or not anything was
delivered, which is why a dead phone can never lose one.

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
- **Delivery state lives in `notify_status`** (one row), written by real
  notifications and by the test button alike. That is why a green test is
  believed: a banner that said "not verified" straight after a passing test
  would only teach you to ignore it.
- **A failed notification never fails the request.** Every sender returns
  `{ok, detail}` rather than throwing its result away, and the caller records it
  on the request row (`notified_at` / `notified_via` / `notify_error`). Do not go
  back to ignoring those responses: they are the only evidence the channels
  work, and without them a broken phone looks exactly like a quiet week. That is
  precisely how this broke once already.
- **Tests**: the handler logic is covered end to end against real SQLite via
  `node:sqlite`, including the CORS-preflight regression that once broke the
  whole flow, and the dead-push-channel cases. Run them with
  `node worker/test/worker.test.mjs` before changing this file.
