# Case study content system

Case studies are data, not hand-built pages. Each one is a single JSON file in this
folder (`content/<slug>.json`). `build.py` reads it and renders the page through a fixed
set of section components (`CS_RENDERERS` in `build.py`), all styled from the design
tokens in `site/assets/design-system.css` and the layout rules in
`site/assets/case-study.css`.

Add a case study by adding a JSON file. No code changes are needed: the build loop
(`build.py`, near line 1550) auto-detects `content/<name>.json` for any page listed in
`PAGES` and renders it through this system. If no JSON exists, that page falls back to the
legacy Framer HTML path, which is exactly the inconsistency this system exists to prevent.
Every case study should have a JSON file here.

## File shape

```jsonc
{
  "slug": "my-project",              // must match the PAGES entry
  "thumbnail": "<framer-hash>",      // cover image (same one used on home/work);
                                     // shown in the "Ready for next?" cards
  "title": "...",                    // <title> and SEO
  "meta_description": "...",         // SEO description
  "gated": false,                    // true = password gate (NDA work)
  "next": "turfly",                  // slug of the next case study (nav loop)
  "blocks": [ { "type": "hero", ... }, ... ]
}
```

`blocks` is an ordered list. Each block has a `type` from the catalog below. Unknown
types are skipped silently, so a typo drops a section without erroring: check the build
log and the page after adding blocks.

## Spacing rule (don't hand-tune padding)

Vertical rhythm comes from two tokens on `main.cs`, not ad-hoc values:
- `--cs-section-y` — vertical padding of a standard content section (64px; 48px on
  mobile). Every section (`section`, `overview`, `stats`, `testimonial`) uses it.
- `--cs-band-y` — vertical padding inside a full-bleed band (the closing outro).

Change the rhythm in ONE place (the token), never per-section. Backgrounds: all
case-study content (hero, sections) sits on **`--ds-paper` (white)** for clean
visibility; cards/steps use `--ds-surface` (light grey) so they stay visible on white.
The closing order is: **contact CTA** ("In some other universe…") on white (contained
navy card), then **`Ready for next?`** as a full-bleed `--ds-surface` (grey) band that
reads as the distinct end zone before the footer.

## Global rules (do not fight the system)

- **One measure for reading.** Body copy is capped at `--ds-measure` (66ch) automatically.
  Never widen it. Long lines were the single biggest defect on the old legacy page.
- **One container.** Every block is capped at `--ds-container` (1200px) and centered.
  Media is capped tighter, at `--ds-media-max` (960px).
- **Spacing comes from tokens.** All padding and gaps use the `--ds-space-*` scale
  (4px base). Do not introduce raw pixel spacing in the CSS.
- **Accent emphasis is markup, not styling.** In any `title`, wrap a phrase in `**double
  asterisks**` to render it in the accent color. This is the ONLY hero/title emphasis
  treatment. Do not add italics, color spans, or bold by hand.
- **Vertical rhythm is automatic.** Sections self-space. Do not add empty blocks as
  spacers.

## Gated (NDA) case studies

Setting `"gated": true` encrypts the entire content region so it is genuinely absent
from the shipped HTML, not just hidden behind an overlay. This matters because the site
is a public static host (GitHub Pages): there is no server to check a password, so the
old approach of shipping the content plus a JS password check left everything readable
via view-source, curl, or a disabled-JS crawl.

How it works now:
- At build time, `build.py` AES-256-GCM encrypts the rendered content. Only the salt, IV,
  and ciphertext ship, as a JSON blob. The image URLs live inside the ciphertext too, so
  they are not discoverable from the page.
- In the browser, the gate derives the key from the typed password via Web Crypto
  (PBKDF2, matching iterations) and decrypts in place. A wrong password fails the GCM auth
  and reveals nothing. Nothing is persisted, so a reload re-locks.

Operating rules (important):
- **The password comes from the environment only:** `CS_GATE_PW`. It is never written to
  the repo. `deploy.sh` prompts for it. Build locally with
  `CS_GATE_PW='...' python3 build.py`. If it is unset, the gated page still builds but is
  shipped locked and unreadable (encrypted with a throwaway key), never as plaintext.
- **Never commit the plaintext source of a gated page.** Both `content/<slug>.json` and the
  legacy `src_<slug>.html` for a gated page must be listed in `.gitignore` (they are read
  locally at build time). See `.gitignore` for the healthcare entries as the pattern.
- Keep the public `<head>` (title, meta description) free of anything the NDA protects.
  The client name in particular should stay out of SEO metadata.

## Block catalog

Ordered roughly by where they appear on a page.

### `hero` (required, first)
Page title and lede. `title` (accent with `**`), `subtitle`.

### `facts` (recommended, right after hero)
The thin metadata strip (role, tool, status, platform). `items: [{label, value}]`.
Keep to 4 to 5 items. This is metadata, not narrative.

### `showreel`  ,  the top motion section
A large motion/animation reel, meant to sit at the very top of a case study
(place it right after `facts`). Fields:
- `poster` , image hash shown before the video loads AND as the fallback when no
  video is set yet. Keeps its natural ratio when shown as the still image.
- `video` , optional. A filename or list of filenames living in
  `site/assets/video/`. List webm first, mp4 second (`["x.webm", "x.mp4"]`) so
  browsers pick the best. When present, renders an autoplay + muted + loop +
  playsinline `<video>` in a fixed `ratio` frame.
- `ratio` , the video frame aspect ratio (default `"16 / 9"`).
- `alt`, `caption` , optional.

Behaviour: with no `video`, the section shows the poster image, so it works
before footage exists. Under `prefers-reduced-motion`, autoplay is disabled and
playback controls are shown instead. Keep videos optimized (muted, ~1080p, short
loop, H.264 mp4 + VP9/AV1 webm).

### `media`  ,  strict count-driven image grid
A standalone image or image group. **The layout is decided ONLY by how many
images the block has** (there is no manual `layout` field to set anymore):

| Images | Layout |
|---|---|
| 1 | full width |
| 2 | two-up |
| 3+ | horizontal scroller (fixed readable height, swipe/scroll) |

Rules, applied to every image identically:
- **No container, no panel, no padding** around images. An image is just an image
  with **rounded corners** and a 1px hairline edge, nothing else.
- 3+ images scroll horizontally so screenshots never shrink below a readable size;
  each keeps a fixed height (uniform row) with its natural width.
- Consistent gap between images; 1-up / 2-up **stack to one column on mobile**.
- A lone portrait image is capped so it doesn't stretch to full width.

`images: [{img, alt, caption?}]`. `img` is the Framer asset hash; the build auto-selects
the sharpest on-disk variant and emits optimized webp. The hash must have `-` suffixed
variants on disk or it will not resolve (single-file no-dash assets are skipped).
To change how a set reads, change the *number* of images, not a layout flag.

### `overview`  ,  the "At a glance" block
Factual project summary as label/value pairs. `eyebrow: "At a glance"`, `items:
[{label, value}]`. **Use this whenever the at-a-glance content is descriptive**
(client, role, scope, constraint, timeline). This is the standard at-a-glance treatment.

### `stats`  ,  the "Impact" block
Headline metrics with big display numbers. `eyebrow: "Impact"`, `items: [{value, desc}]`.
**Use this only for punchy, quantified outcomes** (`350+`, `0 to 1`, `Live`). Do not use
it for descriptive facts, that is what `overview` is for. Reserve the eyebrow "At a
glance" for `overview` and "Impact" for `stats` so the two never blur together.

### `section`  ,  the workhorse
A titled block with body copy and optional media. Fields:
- `eyebrow`, `title` (accent with `**`)
- `number` , optional, renders a large numeral and a top hairline (use for "Problem 01")
- `nav` , optional short label for the sticky table of contents (falls back to `eyebrow`)
- `body` , array. Each item is either a plain string (a paragraph) OR an object
  `{h, p}` where `h` is a bold sub-heading and `p` is its paragraph. Mix freely.
- `chips` , optional array of short strings, rendered as pills (e.g. status states)
- `media` , optional, same shape as the `media` block (`{layout, images}`)

### `cards`
A responsive grid of small cards. Good for comparisons (2 up) or enumerated lists
(3 to 5 up). `eyebrow`, `title`, `intro` (string or array), `items: [{kicker?, title,
desc?}]`. `kicker` is a small label above the card title (a number like `01`, or a
category like "Admin side").

### `steps`
A numbered process grid. `eyebrow`, `title`, `intro`, `items: [{step, name, desc}]`.
`step` is the label ("Phase 01", "Step 01"), `name` is the step title, `desc` the body.
Keep step numbering sequential.

### `testimonial`
A large pull quote. `quote`, `attribution`.

### `lessons`
A reflections grid. `eyebrow`, `title`, `items: [{title, body}]`.

## Sticky table of contents

The build splits blocks into two regions automatically. Leading blocks (hero, facts) run
full width. Once the first nav-eligible block appears, everything after it moves into a
two-column layout with a sticky TOC on the left. Nav-eligible types: `section`, `steps`,
`cards`, `overview`, `stats`, `lessons`, and only when the block carries a `nav` or
`eyebrow` label. Give every major section an `eyebrow` (and a short `nav` if the eyebrow
is long) so the TOC reads well.

## Extending the system

When a new case study needs a section shape none of these cover, add a renderer rather
than hand-rolling HTML in the JSON:
1. Add a `_cs_<type>(b, prefix)` function in `build.py` next to the others.
2. Register it in `CS_RENDERERS`.
3. Add its selectors to `site/assets/case-study.css` using only `--ds-*` tokens.
4. Add the `nav`-eligibility entry in `CS_NAV_TYPES` if it should appear in the TOC.
5. Document it here.

Keep the catalog small. Prefer reusing `section` (its `{h,p}` body covers most needs)
over inventing near-duplicate block types.
