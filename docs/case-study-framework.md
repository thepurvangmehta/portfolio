# Case Study Framework — Layout & Design Guidebook

The system behind every case study page. Goal: a clean, modern, scannable reading
experience that lets a recruiter grasp the work fast and go deep where they want.
Everything here is encoded as design-system tokens (`design-system.css`) and applied
by `case-study.css`. Content is data (`content/<slug>.json`) → rendered by `build.py`.

Grounded in how strong product portfolios (Simon Pan, Sébastien Gabriel, Adam Fard,
Buzz Usborne) structure long case studies.

---

## 1. Widths — three nested columns

Everything aligns to one of three widths. Never invent a new one.

| Role | Token | Value | Used for |
|------|-------|-------|----------|
| Container | `--ds-container` | 1200px | page max, hero, cover image |
| Media | `--ds-media-max` | 960px | screenshots, image panels, grids |
| Prose (measure) | `--ds-measure` | 66ch (~660px) | all reading text (body, intros) |

- Prose is capped at a **readable measure** (~66 chars) — the single biggest lever for
  a premium feel. Body text never runs full width.
- Media caps at **960px** and centers. Nothing sprawls to the viewport edge (the old
  1200px / 83%-of-viewport images are gone).
- The **cover** image (one per study) may use full container width as the hero moment.

## 2. Type scale (fluid, desktop → mobile)

| Role | Token | Desktop → Mobile |
|------|-------|------------------|
| Hero title | `--ds-display-1` | 72 → 40 |
| Section title (h2) | `--ds-title-2` | 44 → 28 |
| Big statement / number | `--ds-display-2` | 46 → 28 |
| Lede / subtitle | `--ds-text-lg` | 20 |
| Reading body | `--ds-text-read` | 18 |
| Card / sub | `--ds-text-lg`/`md` | 20 / 17 |
| Eyebrow / label | `--ds-text-xs` | 12, uppercase, .14em tracking |
| Caption | `--ds-text-sm` | 13, muted |

Rules:
- Headings: `text-wrap: balance`, `hyphens: none`, capped at ~16ch so they never
  hard-break mid-phrase.
- Body: `text-wrap: pretty` (no orphans), `overflow-wrap: break-word`.
- Display font (Gilroy) for titles/numbers/quotes; DM Sans for everything else.

## 3. Spacing & rhythm

- **Section rhythm** `--ds-section-y` = `clamp(64px, 7vw, 104px)`, applied as a single
  vertical **gap** between stacked sections (whitespace separates sections — no divider
  rules, per the research). Numbered problems add a hairline top border as a chapter cue.
- **Gutters**: `--ds-space-6` (24px) mobile, growing on desktop.
- Body paragraph gap: `--ds-space-4` (16px). Title→body: `--ds-space-5` (20px).
- Media→caption: `--ds-space-3` (12px). Section text→media: `--ds-space-10` (40px).

## 4. Image system — the "screenshot panel"

The premium differentiator. UI screenshots **do not bleed edge-to-edge**; they float
inside a tinted, padded panel so each image reads as a deliberate object.

**Panel** (`.cs-fig-box`):
- background `--ds-surface` (tinted), 1px `--ds-border` hairline, radius `--ds-radius-xl`
- inner padding `--ds-panel-pad` = `clamp(16px, 3vw, 48px)`
- the screenshot inside: radius `--ds-radius-md`, soft shadow `--ds-shadow-media`
  (`0 10px 30px rgba(0,0,0,.08)`), shown at natural aspect (never cropped)

**Layouts** (set per image group in content):
- `full` — one screenshot, centered, capped at `--ds-media-max` (960).
- `pair` — 2-up grid, `--ds-space-4` gap; collapses to 1 col on mobile.
- `grid` — auto-fit ≥280px columns; good for 3–4 state screens.
- Portrait/phone screens sit in `pair`/`grid` so they never stretch full width.

**Captions**: optional per image (`"caption"` field). 13px, muted, 12px above.

**Cover**: the first standalone image = the hero shot, panelized at container width.

## 5. Section vocabulary (all consistent)

`hero` · `facts` (meta strip) · `media` (cover) · `overview`/`stats` (TL;DR + at-a-glance)
· `section` (eyebrow + title + body + media) · `steps` · `cards` (stakeholders/validation/
metrics) · `testimonial` · `lessons` · `closing` (CTA + next project).

Every content section is a scroll-spy target in the sticky left **"Scroll to" nav**
(desktop ≥1024px); it hides on mobile and content stacks.

## 6. Non-negotiables (quality floor)

Responsive at 375 / 768 / 1024 / 1440 · zero horizontal overflow · `:focus-visible`
rings · `prefers-reduced-motion` respected · ≥44px tap targets · alt text required on
every image · single `h1` · clean h1→h2→h3 order · zero hardcoded colors (tokens only).
