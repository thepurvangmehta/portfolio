# thepurvangmehta.com — Framer-free static clone

A fully self-contained static copy of www.thepurvangmehta.com with all Framer
dependencies removed. Everything (HTML, CSS, fonts, images) is served locally.

## Structure

```
site/                    ← deploy this folder
  index.html             ← home
  projects/  healthcare/  turfly/  communication-saas/
  nda/  terms/  privacy-policy/  404/
  assets/images/         ← 24 images + all srcset scale variants
  assets/fonts/          ← DM Sans, Fragment Mono, Fontshare fonts
src_*.html               ← raw Framer HTML snapshots (build input)
build.py                 ← regenerates site/ from the snapshots
mjs/                     ← Framer JS bundles (reference only, not used by the site)
```

## Run locally

```bash
cd site && python3 -m http.server 8080
# open http://localhost:8080
```

## Deploy

The `site/` folder works as-is on any static host (Netlify, Vercel, Cloudflare
Pages, GitHub Pages). Pages use directory URLs (`/healthcare/`), so paths match
the original site's URLs. Point your domain at the new host and remove the
Framer custom-domain settings.

## What was removed / kept / replaced

**Removed** (all Framer runtime):
- `script_main.mjs` + 20 module bundles from framerusercontent.com
- Framer analytics (`events.framer.com`), search index, editor hooks, Lenis smooth-scroll
- "Made in Framer" badge (was injected by the runtime)

**Kept**:
- Google Analytics (G-6SDM6ELNS3)
- The custom `data-tags` splitter script
- Framer's self-contained appear-animation engine (entrance animations still play)
- All responsive breakpoints (pure CSS media queries — desktop / tablet / phone)

**Replaced with vanilla JS** (in `build.py`, injected per page):
- **NDA gate** on gated case studies (/healthcare/, /communication-saas/) — the
  content is AES-256-GCM encrypted at build time and decrypted client-side via
  Web Crypto only after the correct password is entered, so it is genuinely
  absent from the shipped HTML. The password lives only in the `CS_GATE_PW`
  environment variable and is never committed. See `content/README.md` for the
  full gating rules.
- **Mobile hamburger menu** — dots toggle the nav links open/closed.
- **Contact buttons** — the Framer contact-form modal required Framer's form
  backend, so Contact now opens https://cal.com/thepurvangmehta. Swap in
  Formspree/Tally if you want a real form back.

## Layout/design fixes (July 2026 audit)

An end-to-end audit (all 9 pages × desktop 1440px + mobile 390px, programmatic
overlap/blur/offscreen scan + visual review) found and fixed these defects left
behind by the removed Framer runtime — all implemented in the injected
"runtime-lite" CSS/JS in `build.py`:

- Project-card hover captions and the cursor-follow "View Project" pill were
  rendering statically on top of the cards / off the page edge → hidden.
- Tech-stack tooltips rendered permanently, overlapping "My tech stack" →
  now hidden, shown on hover above each logo.
- Work-history cards (3 jobs) rendered stacked on top of each other → now a
  clean list with a working "Show all" / "Show less" toggle.
- Footer word cycler ("Lets create/design/build…") rendered all three words
  at once, overlapping the next line → CSS-animated cycle, one word at a time.
- Client-logo ticker was frozen → seamless CSS marquee (track duplicated once).
- Social icons (X, Threads, LinkedIn, Dribbble, Behance) were empty circles
  (glyphs were injected by the runtime) → inline SVGs injected by aria-label.
- Mobile: first Services card was collapsed to 48px inside a 1px parent,
  spilling onto the next card → accordion cards get natural height.
- Mobile: active-year "2026" label overlapped "My work history" → spacing fix.
- Desktop nav showed three stray indicator dots under "Work" → hidden; nav
  variants now strictly one-per-breakpoint (desktop ≥768px, mobile <768px).
- Residual scroll-reveal blur stripped; `body{overflow-x:clip}` kills sideways
  scroll from decorative offscreen elements (e.g. turfly's floating chips).

Final scan result: 0 overlap/blur/offscreen issues at either width (the only
remaining flag is turfly's decorative "Redeemed" chip, which sits fully
offscreen and invisible, as it did while runtime-animated).

## Design system (v2.0 — "minimal")

Redefined July 2026 with muhid.de as the vibe reference (content untouched):

- **Two fonts only**: Gilroy (all headings/display, tight negative tracking)
  and DM Sans (body, UI, labels, buttons). Switzer/Inter/Fragment Mono
  @font-face declarations dropped from the DS stylesheet.
- **Type scale shrunk to muhid proportions**: hero 44 (was 64), sections 32
  (was 54), body 15–17. Tracking −.015 to −.03em on display sizes.
- **Color**: soft-black ink rgb(25 25 25), pure-white surfaces, 10%-black
  hairline borders, and ONE blue — rgb(28 53 236) kept as primary; the old
  purple and light-blue links are unified into it.
- **Flat**: decorative box-shadows removed site-wide; elevation is hairlines.
  Nav is a quiet gray bar (no glass/blur/border) with a solid-ink Contact pill.
- **Motion**: ease-out-expo default.
- **Reskin layer**: section 3 of `design-system.css` re-themes the existing
  Framer markup by overriding its `.framer-styles-preset-*` classes and
  heading tags — the mechanism by which the redesign applies without touching
  markup or copy. Side effect: the old mobile hero text-clipping is gone.
- **Enforcement layer** (section 4): a full-site inline-style audit mapped
  every off-system value to a token — legacy light-blue links (424 uses),
  two stray purples (timeline year + dot, NDA highlights), pure-black
  surfaces → soft ink, the password gate fully restyled to system components,
  `::selection` and `:focus-visible` in accent, social icon glyphs pinned to
  ink. The remaining gradients are alpha masks (edge fades), not colors.
  Deliberate content exceptions: turfly's product-mockup status chips and
  the "made with love" heart sticker (illustrations, not site chrome).

### Previous (v1.0)

- **Gallery page**: `/design-system/` — private (linked nowhere, `noindex`).
  Documents colors, the five font families and type scale, spacing/radius/
  elevation, the icon rule, and live demos of every reusable component.
- **Tokens**: `site/assets/design-system.css` — the single source of truth.
  Semantic `--ds-*` variables (color, type, spacing, radius, shadow, motion)
  plus a bridge that re-points Framer's original `--token-*` variables at the
  semantic ones. Framer never defined those tokens (each usage carried an
  inline fallback), so the bridge makes the whole site live-editable:
  change `--ds-accent` once and every page follows.
- **Components**: clean `ds-*` classes (buttons, cards, tags, nav pill,
  tooltip, input, marquee, icon button) for anything new; existing markup
  keeps its Framer classes but inherits the tokens.
- **Icons**: Simple Icons geometry, inline SVG, 24×24 viewBox,
  `fill="currentColor"`, sized by `--ds-icon-size`. No icon images, no
  icon fonts. The injected social icons follow this rule.
- The stylesheet is linked into every page by `build.py`.

## Polish pass (v2.1)

- Nav logo is now a link to home on every page (role=link, keyboard-accessible).
- Social icon buttons normalized: 40px pill hit-area, 18px glyphs, hairline —
  nothing clipped; the X follower count renders in ink on all backgrounds.
- Footer word cycler rebuilt as an in-place vertical roll (words roll through
  a one-line clipped window, ease-out-quint, seamless handoff).
- Testimonials redesigned: accent-50 tinted band, ink heading, equal-height
  white hairline cards. (The "Visual explorations" band shares the section
  name in some breakpoints and picks up the same tint — kept as a motif.)
- Work-history timeline block (2026/years/cards/Show-all) removed.
- System expanded: accent tint/shade scale (600/200/100/50), illustration
  palette (content-only), `--ds-container: 1120px` applied site-wide.
- Icon policy: Phosphor (regular) for UI icons, Simple Icons for brand
  glyphs — documented in the gallery with canonical starter paths.

## Project cards (v2.2)

Restyled to the muhid case-study pattern on the home "Selected Projects" grid
and the /projects/ page: rounded-xl media card, clickable corner chip (an
<a> with Phosphor arrow-up-right, navigating like the card) injected by
runtime-lite, and the previously-hidden Framer caption block restored BELOW each
card as title (17/700 ink) + type of work (15/500 gray). Card rows top-align
so captions don't shift siblings.

## Hero card (uxdayshankar pattern, v2.3)

Home hero restructured to match uxdayshankar.com: hero + client-logo band
now form one white rounded card floating on the page surface, with a
centered hairline divider between them. Injected on top of existing markup:
"Available for work" badge (green --ds-positive dot) and two CTAs
("More about me" -> #about-me, "View work" -> /projects/) that fade in with
the subtitle. Colors sampled from the reference: page bg rgb(245 245 245)
(--ds-surface, applied site-wide), card white rgb(255 255 255), display
charcoal rgb(77 77 77) (--ds-ink-soft, hero headline — the blue accent span
is preserved). Hero h1 scales up to 64px. Legacy vertical column hairlines
("Border" elements) hidden site-wide — they clashed with the card layout.

## Layout refinement (v2.4)

- Hero card capped at 1200px, centered via a build-time wrapper
  (`#pm-hero-wrap`) around the hero section + client-logos band — Framer's
  own parent was a zero-width node, so runtime CSS math couldn't center it.
  (A runtime reparenting approach was tried first and abandoned: moving the
  nodes restarted their CSS entrance animations.)
  Inner container padding zeroed; the card is now ~compact like the
  reference instead of viewport-height.
- Blue accent-50 section bands removed — sections differentiate as white
  cards / white bands on the gray page, like uxdayshankar.com. (Accent tints
  stay in the token set.)
- One vertical rhythm: all home sections get clamp(64px, 7vw, 104px)
  top/bottom padding, min-heights removed.

## Spacing pass (v2.4.1)

Measurement-driven: a probe walked every home section and reported child
gaps + fixed-height slack. Fixes: section padding tightened to
clamp(56px, 6vw, 88px) with a 40px heading-to-content gap; containers
(Inside Container, sliders, Projects grid) forced to natural height; the
testimonial band's 466px fixed-height wrapper (250px of dead air below
~210px cards) is shrunk to content at runtime, and testimonial cards are
equalized to the tallest card in the row.

## Content restructure (v2.4.2)

"My Skills that supercharge your business." (Services) section retired on
home — hidden via a :has() guard scoped to its Techstack child so the
case-study pages' own "Services" sections are unaffected. The "My tech
stack" block (label + tool logos, hover tooltips intact) moved into the
About Me section, appended under the bio with a hairline divider. Note:
the nav "Services" anchor now points at a hidden section.

## Visual explorations marquee (v2.4.3)

The home gallery (was a runtime 3D carousel, static since de-Framering) is
rebuilt at runtime into two marquee rows scrolling in opposite directions
(uxdayshankar "Selected interfaces" pattern): the 7 gallery images split
across two tracks, each duplicated for a seamless 45s loop, cards as white
radius-lg tiles with the shot letterboxed (background contain), edge-fade
mask, pause on hover, disabled under prefers-reduced-motion.

## Small cuts (v2.4.4)

- Divider line above the moved "My tech stack" block removed.
- End-card section ("In some other universe...") hidden on the home page
  only (via the index-only style block); it remains on the NDA and
  case-study pages, which have their own copies.

## Section color + width system (v2.5)

- Sections differentiate by BACKGROUND, not dividers: all section/wrapper
  borders killed; Latest Projects and About Me are white bands, gallery and
  testimonials sit on the gray page (uxdayshankar pattern).
- ONE content line: --ds-container raised to 1200px (= hero card width) and
  every section's content wrapper is centered at that width with flush edges
  (a heading wrapper was `justify-content:center`-ing a fixed-width block 36px
  off-line — now left-justified; the projects grid's negative margins zeroed).
  Measured result: hero card, headings, and grids all at the same left edge.
- Full-bleed marquees (visual explorations) keep viewport width but fade out
  over 140px at both ends (mask + -webkit-mask), verified by pixel sampling.

## Fold-fit + marquee testimonials (v2.5.1)

- Visual-explorations marquee is no longer full-bleed: bounded to
  `--ds-container` (same 1200px line as everything else); the 140px fades now
  sit at the container's endpoints. On mobile the fade narrows to 36px so
  cards stay readable at 390px (`--pm-fade` custom property).
- Project cards shrunk to fit all 4 in one fold: media forced to
  `aspect-ratio:16/10`, `max-height:350px`, images `object-fit:cover` anchored
  to the top (`object-position:50% 0`) so baked-in titles aren't cropped.
- About Me photo simplified to a single straight photo: the two rotated
  photos behind are hidden at runtime (keeps the topmost visible layer,
  clears its rotation, 16px radius). Visible-layer detection filters out
  hidden breakpoint variants via `getBoundingClientRect().width > 0`.
- Testimonials converted from static cards to an auto-scrolling marquee
  (`.pm-gal.pm-testi`, 38s loop, hover pause, reduced-motion off) reusing the
  explorations pattern: same container width, same end fades. Cloned cards
  are clamped to `min(560px, 85vw)` with wrapping re-enabled on descendants
  (Framer's absolute-position layout blew clones out to 3000px+ otherwise).
- Zero-overlap scan clean at 1440 and 390 (corner chips and marquee tracks
  excluded as intentional overlays).

## Section bands, heading actions, About Me rework (v2.6)

- ROOT-CAUSE FIX for section backgrounds: Framer ships a full-page absolute
  "BG Color" overlay at z-index:1 in an off-token rgb(250,250,250). Any
  section without its own z-index (Latest Projects) had its white background
  painted OVER by that layer, and the page "gray" was never our 245 token.
  The overlay is retinted to `--ds-surface` and banded sections get
  z-index:1. Result: gray hero → white projects → gray explorations → white
  about → gray testimonials, all on-token.
- "View all my projects" moved from below the grid onto the Selected Projects
  heading row, right-aligned, copy shortened to "View All" (`.pm-sec-head`
  flex row built at runtime).
- Project-card caption gap tightened (margin-top 16 → 4px).
- Explorations marquee no longer pauses on hover; only the testimonial
  marquee keeps hover-pause (quotes need reading time).
- About Me: heading rewritten to "About Me" (keeps the framer type preset by
  reusing an existing span's classes); photo/socials stack was hard-sized at
  258px — now fills a 42% column while the text takes 58%, so both columns
  span the full 1200px line; philosophy copy normalized to DM Sans only,
  17px/1.7, soft-ink body with ink 600 lead-ins; the "MADE WITH LOVE"
  curved-text stamp is removed across all breakpoint variants (JS matches the
  textPath content, since each variant has a different generated class).
- Mobile About order fixed: Framer re-sequences children via CSS `order` on
  small screens; heading → photo → text → tech stack is enforced.
- Testimonials: heading copy now "What clients say"; cards stretch to the
  tallest card (`align-self:stretch` + quote area flex-grow).
- Zero-overlap scan clean at 1440/390 (client-logo ticker items passing under
  their masked label are intentional, as are chips and marquee tracks).

## Hero spacing pass (v2.6.1)

- "Available for work" badge removed entirely (build.py no longer injects
  `.pm-badge`; its styles and entrance-animation hook are gone too). Card
  padding is now symmetric — 96px top/bottom desktop, 56px mobile — so the
  headline block sits centered in the card and the card + logos strip fit
  one fold.
- Consistent air around the white hero card: ~48px below the nav pill
  (margin-top 104 → 128), and a 48px gray gap below the card before the
  white Projects band (`#pm-hero-wrap{padding-bottom:48px}`, 24px on
  mobile) — previously the card sat flush against the next section and its
  bottom corners disappeared white-on-white.

## Mobile pass (v2.9)

Full 390px audit + fixes:

- NAV: proper mobile menu. The pill keeps logo + dots; tapping the dots
  opens a `.pm-mmenu` dropdown card (solid paper, hairline border, 20px
  radius, soft shadow) with Work / About / Resume rows and a full-width ink
  Contact CTA (cal.com). Closes on link tap or tap outside. Framer's inline
  "Desktop" links stay hidden; the old expand-in-pill CSS is gone.
- TYPE: mobile hero headline (an h2 in the phone variant, was a weak 26px)
  → 31px/1.18. Section titles cap at 26px on mobile so they hold one line.
- SPACING: hero card inner side padding 20 → 12px, so with the 12px card
  margin the hero content sits on the same 24px edge as every section.
- VIEW ALL: was invisible on mobile (the heading row was built around the
  hidden desktop h2 variant) — the builder now targets the VISIBLE h2, and
  the moved link is force-displayed. On mobile the row wraps: title on its
  own line, "View All" right-aligned beneath.
- Verified: full-page sweep at 390px, menu open/close, zero-overlap scan at
  390 + 1440 (only hits: collapsed accordion bodies, clipped invisible).

## Explorations: fade removed (v2.8.2)

- The white edge-fade mask is off for `#explorations .pm-gal` only — cards
  now hard-clip at the 1200px container edges. Testimonials keep their fade.

## Section-title component + polish (v2.8.1)

- `.ds-section-title` is now a real component (base = the About Me title:
  Gilroy 600, clamp(28px,2.6vw,36px)/1.2, -0.02em, ink, `<span>` soft) and
  ALL home section headings map to it (#projects/#explorations/#testimonials
  h2s via reskin; About uses the class directly). Documented on the gallery.
- Title→content gap tightened: section flex gap 40 → 28px; the About grid's
  row gap dropped from ~100px to 28px (it was inheriting the column clamp).
- Nav Contact button: Framer drew a gray hairline ring via ::after on top of
  the ink pill — removed, along with outline/box-shadow in all states.

## Cleanup batch (v2.8)

- About Me got its section title back ("About **Me**", `.pm-about-title`,
  same voice as the other section headings) and the small "About" label
  above the facts is gone.
- Nav: "Services" removed on every page (runtime hides the highest wrapper
  containing only that link, so the flex gap collapses — hiding just the
  anchor left a double gap). "Work" now opens the projects page at the top:
  the `#lprojects` fragment is stripped from all Work links.
- Projects page: "Trusted by many" Client Logos strip removed (page-scoped
  style; the home hero keeps its own ticker).
- SECTION MAP added to the design-system.css header; the runtime-built
  sections now get clean ids: `#explorations` and `#testimonials`
  (joining `#pm-hero-wrap`, `#projects`, `#about-me`).
- Splash: radial gradient glow deleted (off-system). Exit is now a mild
  shutter-open — the flat ink cover is two panels (::before/::after) that
  slide apart top/bottom at 1.35s while the logo fades at 1.2s; the fixed
  overlay clears via visibility at 1.95s and is removed from DOM at 2.1s.

## Social pills: centering + real X count (v2.7.1)

- Icon centering: Framer wraps some glyphs (Dribbble, Behance) in fixed
  14px boxes around 18px svgs — the overflow shifted them off-center.
  Wrappers now size to their glyph and flex-center.
- X follower count is real now (the baked "1,214" was stale; actual: 256).
  Two layers: build.py fetches the count from api.fxtwitter.com and bakes
  it into every page (source snapshots always carry the 1,214 literal, so
  the replace is stable across rebuilds); runtime-lite re-fetches on every
  visit and overwrites the number live, falling back to the baked value if
  the API is unreachable. CAVEAT: fxtwitter is an unofficial third-party
  API — if it dies, the count silently stays at the last baked value
  (rebuild refreshes it). X's official API needs a paid token + backend.

## About Me v2 — muhid.de layout (v2.7)

- Section rebuilt to mirror muhid.de/#work: left column = rotated polaroid
  photo (white frame, soft shadow, square crop of the real photo) + "About"
  facts list + My tech stack; right column = two-line hook headline, intro
  paragraph, and an expandable work-history accordion (chevron rotates,
  row slides open). Runtime-lite builds `.pm-about` inside the section and
  hides the old Framer children (`display:none !important` — stylesheet
  !important rules beat plain inline styles).
- Data status (all in build.py's about builder): FACTS still placeholder-ish
  ("4+ Years Experience / 1M+ Users Reached / SURAT · Remote-Open" — user
  said "close, tweak later"). JOBS sourced from public profiles since
  LinkedIn blocks fetches (Logicwind 2025–Present · Josh Talks 2023–2025 ·
  BeerBiceps Media 2021–2023) — DATES APPROXIMATE, confirm with Purvang.
- Per user: tech stack removed from About entirely (element stays in the
  hidden Services section, easy to resurrect); social icon row and the
  handwritten signature brought back — socials under the About facts,
  signature between the intro and the work list. Both are the original
  Framer elements re-parented at runtime (visible variant captured before
  the old children are hidden).
- Dropped: the "About Me" section heading (the reference's hook headline
  replaces it).
- Copy modified, not copied: "I didn't start out in design. / I just never
  left once I found it."

## Explorations cards: full-bleed art (v2.6.7)

- `.pm-gal-card` is now a fixed 3:2 frame (`min(390px, 80vw)` wide) and the
  artwork covers it edge-to-edge (`background-size:cover`, padding removed)
  — no inner margins. IMAGE SPEC: design exports at 3:2, e.g. 1200x800;
  current images are center-crop-fitted until replaced.

## About Me fold-fit (v2.6.6)

- Restructured to the reference (muhid-style) profile layout: the left
  column is one profile card — photo, socials, name/role, and "My tech
  stack" stacked together (build.py now appends the moved Techstack to the
  Picture / Work History column instead of the section container, which also
  gives mobile the right order for free). The right column stays bio text +
  signature.
- Photo clamped to `min(300px, 52vw)` with `overflow:hidden` on its
  container — the inner Framer wrapper keeps a fixed 493px box and was
  painting 113px past the clamp, behind the socials row.
- Column gap slack removed (Picture column's 48px class gap zeroed; stack
  spacing owned by margin). Section band measured 885px: one fold.
- v2.6.6a: name/role and social icons share ONE row under the photo
  (name left, socials right via flex-wrap + margin-left:auto; the photo
  spans the full first row), tech stack below. Band now 820px. On mobile
  the pair wraps back into two stacked rows.

## Testimonial card width (v2.6.5)

- Cards narrowed 560 → 388px (`min(388px, 85vw)`): exactly three fit the
  1200px container per view (2×388 + gaps + faded partials at the edges),
  instead of barely two. Equal-height logic re-measures automatically.

## Placeholder testimonials (v2.6.4)

- Four dummy testimonials added to the marquee (Sarah Mitchell / Finlo,
  Arjun Nair / Zapline, Emily Carter / Bloomer, Rohan Desai / Quantly) —
  PLACEHOLDER COPY, swap for real quotes when available (the `pmDummies`
  array in build.py's marquee builder). Each is a clone of a real card with
  name/role/quote swapped and the photo replaced by a `.pm-avatar` initials
  disc (accent-50 bg, accent text) — real people's photos never appear on
  invented quotes.
- Track repetitions corrected 3 → 2: the loop animation translates -50%, so
  the track must contain its content exactly twice or the wrap point jumps.

## Testimonial equal heights + copy (v2.6.3)

- All marquee cards now match the tallest card exactly. CSS flex stretch was
  silently defeated by Framer's cascade, so the marquee builder measures the
  tallest clone and pins every card to that height (re-measured on load and
  resize). Clones also drop the original layout's staggered translateY, so
  the row shares one top edge.
- Ranveer Allahbadia quote: paragraph break removed — now
  "Really good stuff Purvang, / Loving your work! Just Keep going."
  (build-time content replace in build.py).

## Nav glass (v2.6.2)

- Nav pill restyled on the uxdayshankar pattern, all pages. At rest:
  `rgba(255,255,255,.92)` with a hairline `--ds-border` (it used to be flat
  245 gray with no border and vanished into the page). Past 24px of scroll,
  runtime-lite toggles `.pm-scrolled`: translucent white (.58) +
  `backdrop-filter: blur(20px) saturate(1.6)` + soft shadow, with a .35s
  eased transition between states. The open mobile menu forces near-opaque
  (.97) so links stay readable over content. Framer's own inner
  backdrop-filter layer stays disabled — the nav element itself is the glass.

## Hero entrance animation (home page)

Modeled on uxdayshankar.com's hero choreography (timings taken from its
Framer appear-effects data), rebuilt as pure CSS keyframes + a splash div,
injected by `build.py` on the home page only:

| t (s)       | element        | motion                                        |
|-------------|----------------|-----------------------------------------------|
| 0 – 0.5     | splash wordmark| "Purvang." scales 2.6 → 1 on ink overlay      |
| 1.05 – 1.65 | splash         | fades out, removed from DOM at 1.9s           |
| 0.75 – 2.05 | headline       | zoom-settle: scale 2 → 1, y 100 → 0, ease(.68,0,0,.99) |
| 1.3 – 1.8   | nav pill       | drops in from y −106                          |
| 1.9 – 3.1   | subtitle       | fade in                                       |
| 2.4 – 3.6   | client logos   | fade in                                       |

Splash gating (v2.7.2/.3): plays on reload, fresh/external entry, or a logo
click from another page (the logo handler sets a sessionStorage flag read
before first paint). Internal link navigations — e.g. nav About/Services
from a project page, back/forward — add `pm-no-splash` on `<html>`, which
hides the splash AND skips the staged entrance reveals so content shows
instantly; the browser then jumps straight to the target anchor. Same-page
anchor clicks are intercepted for smooth scrolling (no navigation at all),
and cross-page internal links set a skip flag as a referrer-independent
backup. ROOT CAUSE of "About/Services still splashed" (v2.7.3): the logo
click handler was bound to `closest('[data-framer-name]')`, which on nav
was the WHOLE nav pill — every nav-link click fired the logo's go-home
(with splash flag) instead of the link. Now bound to the ~81px logo element
only, and clicks originating inside real `<a>`s are ignored. Everything is
disabled under `prefers-reduced-motion`. Uses `--ds-ease` / motion tokens.

## Known differences from the live site

- The client-logo ticker is static (was runtime-driven marquee).
- Scroll-triggered reveal effects render in their final visible state
  (the scroll animation engine was part of the removed runtime).
- Contact modal → cal.com link (see above).

## Things you may want to fix in the content

- Typo on the home page: "Companies I've **workd** with".
- A leftover template link: `mailto:joseph@launchnow.design` appears on the
  home page (likely from the original Framer template author).
