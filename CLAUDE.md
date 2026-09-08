# CLAUDE.md — working brief for this repository

Read this before changing anything. It exists because parts of this project
fail in ways that are invisible until weeks later, and because two of its
constraints are non-obvious enough that they have already been violated once
each. The **Hard constraints** section is the important half.

## What this is

The static site behind <https://thepurvangmehta.com> — a personal portfolio,
built from Python into plain HTML, plus one Cloudflare Worker that gates a
small number of NDA-ish case studies behind an approval flow.

Audience note: **the owner is a designer, not a developer.** Explain in plain
language, avoid jargon, and never assume a terminal or a build toolchain is at
hand. Give exact click paths and exact values to paste. Two of the longest
detours in this project's history were a menu that had been renamed and a
setting that looked saved but was not deployed — neither was a code problem.

## Layout

| Path | What it is |
|---|---|
| `build.py` | The whole site generator. Reads `content/*.json`, writes `site/`. |
| `content/*.json` | Case-study and page content. `"gated": true` marks a locked one. |
| `site/` | Build output. Served by GitHub Pages from the `gh-pages` branch. |
| `deploy.sh` | Build + commit + push `main` + rebuild and force-push `gh-pages`. |
| `worker/src/index.js` | The access-request Worker. Single file, no build step. |
| `worker/test/worker.test.mjs` | Its test suite, real SQLite via `node:sqlite`. |
| `worker/README.md` | **The Worker's runbook.** Read it before touching the Worker. |
| `src_*.html`, `original.html`, `ref*.html` | Reference captures of the original Framer site. Not built from. |

## Two deploy paths, and only one is automated

**The site**: `./deploy.sh "message"` on the owner's Mac. Builds, pushes `main`,
rebuilds `gh-pages` from `site/`, force-pushes. GitHub Pages serves `gh-pages`.

**The Worker**: *manually pasted* into the Cloudflare dashboard
(Workers & Pages → `case-study-access` → Edit Code → paste → Deploy). There is
no CI, and `deploy.sh` does **not** touch it.

Consequences worth holding onto:

- **The repo can silently drift from what is live.** Changing
  `worker/src/index.js` and committing changes nothing in production. Say so
  explicitly when handing over Worker changes, and give a copyable link:
  `https://github.com/thepurvangmehta/portfolio/blob/main/worker/src/index.js`
  (the copy icon on that page beats attaching a file — the owner asked for
  links over downloads).
- **Verify what is actually running** via `GET /health` on the Worker, which
  reports its live storage and configured notification channels. Never infer
  the deployed version from the repo.
- **Cloudflare variables need a deploy to take effect.** Saving a variable in
  Settings shows the value in the table but does not apply it to the running
  Worker. If a setting appears ignored, redeploy before debugging anything else.
  This cost an hour once.

## Hard constraints

Each of these was learned by breaking it. Do not undo them without reading why.

1. **Never move access state back to Workers KV.** KV edge-caches reads for at
   least 60s including misses, so the browser polling "approved yet?" is served
   a stale "no" long after approval. D1 is strongly consistent. Details in
   `worker/README.md`.
2. **Never use a service metered per IP address from the Worker.** Cloudflare
   Workers have no dedicated egress IP — outbound requests share Cloudflare's
   pool with every other customer. ntfy's free tier (250 msgs/day/IP) returned
   `429 daily message quota reached` on the *second* message ever sent, because
   strangers had spent it. Pushover meters per account, which is why it is used.
   Check how any new provider meters before adopting it.
3. **Never discard the response from a delivery API.** The original bug: the
   Pushover response was awaited and thrown away, so a de-registered phone was
   indistinguishable from a quiet month. Every sender returns `{ok, detail}`,
   the outcome is recorded, and `/admin` shows it. Keep it that way.
4. **A failed notification must never fail the visitor's request.** The request
   is stored either way and is visible on `/admin`; a visitor cannot act on the
   owner's broken phone. Senders must not throw.
5. **A fallback must never hide the primary's failure.** Delivery by the email
   fallback alone is recorded as delivered *and* as a Pushover error, and shows
   amber, not green. Otherwise the original bug returns one layer up.
6. **No secrets in this repo, ever.** `GATE_PASSWORD` / `CS_GATE_PW`,
   `ADMIN_KEY`, Pushover and Resend credentials live only in the Cloudflare
   dashboard and the owner's Keychain. The gated content JSON is gitignored.
   `ADMIN_KEY` is a bearer credential: whoever holds the `/admin?key=` link can
   read every collected email address and grant access.
7. **Escape anything interpolated into HTML.** Email addresses arrive from a
   public form and `EMAIL_RE` accepts `<img/src=x/onerror=...>@evil.co`.
   `esc()` exists for this and is covered by a test.

## How the gate works, briefly

Gated case studies ship as AES-256-GCM ciphertext and are decrypted in the
browser with a password the Worker hands out. The build password
(`CS_GATE_PW`) and the Worker's `GATE_PASSWORD` must match exactly or approved
visitors see "could not be unlocked".

A visitor enters their email → `POST /request-access` → if already approved the
password comes straight back; otherwise the request is stored and the owner is
notified with Approve/Deny links → the browser polls `/check-access`.

Approval is global (opens every gated case study) and lasts 4 hours. Invites
sent from `/admin` last 7 days, deliberately — see `worker/README.md`.

This is a speed bump and a lead-capture form, not confidentiality: the
ciphertext is public, the password is global, and anyone approved can share
what they decrypt. Do not let anyone believe otherwise.

## Before you commit

- Worker changes: `node worker/test/worker.test.mjs` — must print `ALL PASSED`.
  There is no CI; this is the only gate.
- Site changes: `python3 build.py` needs `CS_GATE_PW` set or gated pages fall
  back to previously-built ciphertext.
- `tests/gate-behaviour.test.js` needs Playwright installed and is not part of
  the default loop.

## History

`worker/README.md` carries the incident record for the September 2026
notification outage — what broke, why it stayed invisible for a month, and
which options were tried and rejected. Read it before redesigning the
notification path; the obvious alternatives have already been costed.
