#!/usr/bin/env python3
"""De-Framer the portfolio: strip Framer runtime, localize all assets."""
import re, os, hashlib, pathlib, urllib.request, urllib.parse, concurrent.futures
import json, glob, base64, html as _htmlmod
from PIL import Image

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "site"
PAGES = {
    "index": "", "projects": "projects", "healthcare": "healthcare",
    "turfly": "turfly", "communication-saas": "communication-saas",
    "nda": "nda", "terms": "terms", "privacy-policy": "privacy-policy",
    "404": "404",
}

SITE_URL = "https://www.thepurvangmehta.com"
CONTACT_EMAIL = "thepurvangmehta@gmail.com"
# Password for NDA/gated case studies. Read from the environment ONLY, never
# hardcoded, so it never lands in this (public) repo. Set it when building for
# deploy:  CS_GATE_PW='your-password' python3 build.py  (deploy.sh prompts).
CS_GATE_PW = (os.environ.get("CS_GATE_PW") or "").strip() or None
RESUME_URL = "https://drive.google.com/file/d/1i2vT2GYwkOnyoGzwG4zNUabKpk-ayuYX/view?usp=sharing"

# ---- hand-built nav (replaces the Framer-exported nav entirely) ----------
def _dotted_logo():
    """logo.svg with the trailing period split out so it can be accent-colored."""
    svg = open(pathlib.Path(__file__).parent / "logo.svg", encoding="utf-8").read().strip()
    m = re.search(r'(<path[^>]*\bd=")(M[^"]*?Z)\s*(M[^"]*")', svg)
    if m:
        svg = svg.replace(m.group(0), f'<path class="pm-dot" d="{m.group(2)}"/>{m.group(1)}{m.group(3)}', 1)
    return svg

LOGO_SVG = _dotted_logo()

NAV_CSS = """
.pm-nav{position:fixed;top:32px;left:50%;transform:translateX(-50%);z-index:1000;
  display:flex;align-items:center;gap:clamp(40px,5vw,72px);max-width:calc(100vw - 32px);
  padding:11px 12px 11px 26px;background:var(--ds-paper);border:1px solid var(--ds-border);
  border-radius:var(--ds-radius-pill);box-shadow:0 6px 22px rgb(0 0 0/.05);
  transition:transform .38s var(--ds-ease),box-shadow .2s var(--ds-ease)}
/* hide on scroll down, reveal on scroll up (toggled by NAV_JS) */
.pm-nav.pm-hidden{transform:translateX(-50%) translateY(calc(-100% - 40px))}
@media (prefers-reduced-motion:reduce){.pm-nav{transition:box-shadow .2s var(--ds-ease)}}
/* body was dark ink, keep the top area (behind the floating nav) light like the page */
body{background:var(--ds-surface)!important}
/* anchor jumps (Contact/About) clear the fixed nav instead of tucking under it */
:root{scroll-padding-top:120px}
html{scroll-padding-top:120px}
/* even vertical rhythm: gap above nav (32) == gap below nav == gap below the
   hero card. nav top:32 + nav height ~60/64; hero margin-top puts card 32 below
   the nav; hero-wrap padding-bottom gives the matching 32 below the card. */
/* full-height hero: the first fold is ALWAYS just the hero; the card group
   (headline card + ticker) is vertically centered in the viewport, clear of
   the fixed nav. #pm-hero-wrap is already a flex column, so justify-content
   centers vertically without disturbing the horizontal layout. */
/* full-height hero: the fold is always the hero; the card (.pm-hero, flex:1)
   fills, content centered, ticker pinned to the bottom. Consistent 32px gaps:
   above nav, nav->card, and card->bottom. */
/* DESKTOP: card fills the fold with EQUAL top/bottom padding = the nav's
   vertical centre, so the nav straddles the card's top edge (half above, half
   over it) and the block reads balanced. nav = top:32 + height ~60.
   MOBILE: keep the older layout, nav sits fully above the card. */
#pm-hero-wrap{margin-top:0!important;min-height:100vh;min-height:100dvh;
  box-sizing:border-box;
  padding-top:62px!important;padding-bottom:62px!important}
@media (max-width:767.98px){#pm-hero-wrap{padding-top:128px!important;padding-bottom:32px!important}}
.pm-nav.pm-scrolled{box-shadow:0 12px 30px rgb(0 0 0/.12)}
.pm-nav-logo{display:flex;align-items:center;flex:none;text-decoration:none;
  /* 44px hit area without shifting the pill layout (WCAG 2.5.5) */
  min-height:44px;padding:8px 10px;margin:-8px -10px}
.pm-nav-logo svg{height:19px;width:auto;display:block;overflow:visible}
.pm-nav-logo svg path{fill:var(--ds-ink)}
.pm-nav-logo svg path.pm-dot{fill:var(--ds-accent)}
.pm-nav-links{display:flex;align-items:center;gap:2px}
.pm-nav-links>a:not(.ds-btn){padding:8px 14px;border-radius:var(--ds-radius-pill);
  font:500 15px/1 var(--ds-font-sans);color:var(--ds-ink);text-decoration:none;white-space:nowrap;
  transition:background .15s var(--ds-ease)}
.pm-nav-links>a:not(.ds-btn):hover{background:var(--ds-surface)}
.pm-nav-links .ds-btn{margin-left:8px;font-size:14px}
.pm-nav-toggle{display:none}
@media (max-width:767.98px){
  .pm-nav{left:16px;right:16px;transform:none;max-width:none;justify-content:space-between;
    gap:0;padding:9px 10px 9px 20px}
  .pm-nav.pm-hidden{transform:translateY(calc(-100% - 32px))}
  .pm-nav-toggle{display:flex;flex-direction:column;justify-content:center;gap:5px;width:44px;height:44px;
    padding:11px;background:none;border:0;cursor:pointer;-webkit-tap-highlight-color:transparent}
  .pm-nav-toggle span{display:block;width:22px;height:2px;border-radius:2px;background:var(--ds-ink);
    transition:transform .22s var(--ds-ease),opacity .18s var(--ds-ease)}
  .pm-nav.open .pm-nav-toggle span:nth-child(1){transform:translateY(7px) rotate(45deg)}
  .pm-nav.open .pm-nav-toggle span:nth-child(2){opacity:0}
  .pm-nav.open .pm-nav-toggle span:nth-child(3){transform:translateY(-7px) rotate(-45deg)}
  .pm-nav-links{position:absolute;top:calc(100% + 10px);left:0;right:0;flex-direction:column;
    align-items:stretch;gap:2px;padding:8px;background:var(--ds-paper);border:1px solid var(--ds-border);
    border-radius:20px;box-shadow:0 16px 40px rgb(0 0 0/.14);
    opacity:0;visibility:hidden;transform:translateY(-6px);pointer-events:none;
    transition:opacity .22s var(--ds-ease),transform .22s var(--ds-ease),visibility 0s .22s}
  .pm-nav.open .pm-nav-links{opacity:1;visibility:visible;transform:none;pointer-events:auto;transition-delay:0s}
  .pm-nav-links>a:not(.ds-btn){text-align:center;padding:14px;font-size:17px}
  .pm-nav-links .ds-btn{margin:6px 0 0;width:100%;font-size:16px}
}
"""

NAV_JS = """<script>(function(){var n=document.getElementById('pm-nav');if(!n)return;
var t=n.querySelector('.pm-nav-toggle'),l=n.querySelector('.pm-nav-links');
if(t){t.addEventListener('click',function(e){e.stopPropagation();var o=n.classList.toggle('open');t.setAttribute('aria-expanded',o?'true':'false');});
if(l)l.addEventListener('click',function(e){var link=e.target.closest('a');if(!link)return;
n.classList.remove('open');if(t)t.setAttribute('aria-expanded','false');
var href=link.getAttribute('href')||'';
if(href.charAt(0)==='#'&&href.length>1){var tgt=document.getElementById(href.slice(1));
if(tgt){e.preventDefault();e.stopPropagation();setTimeout(function(){tgt.scrollIntoView({behavior:'smooth'});},50);}}});
document.addEventListener('click',function(e){if(!n.contains(e.target)){n.classList.remove('open');t.setAttribute('aria-expanded','false');}});}
var lastY=window.scrollY||0,g=function(){var y=window.scrollY||0;
n.classList.toggle('pm-scrolled',y>24);
if(!n.classList.contains('open')){
if(y>lastY+4&&y>140)n.classList.add('pm-hidden');
else if(y<lastY-4)n.classList.remove('pm-hidden');}
lastY=y;};window.addEventListener('scroll',g,{passive:true});g();
var lg=n.querySelector('.pm-nav-logo');if(lg)lg.addEventListener('click',function(){try{sessionStorage.setItem('pm-logo-nav','1');}catch(_){}});
})();</script>"""

def build_nav(prefix):
    home = prefix if prefix else "./"
    work = prefix + "projects/"
    about = prefix + "#about-me"
    return (
        f"<style>{NAV_CSS}</style>"
        '<nav class="pm-nav" id="pm-nav" aria-label="Primary">'
        f'<a class="pm-nav-logo" href="{home}" aria-label="Home">{LOGO_SVG}</a>'
        '<button class="pm-nav-toggle" type="button" aria-label="Open menu" aria-expanded="false" aria-controls="pm-nav-links">'
        '<span></span><span></span><span></span></button>'
        '<div class="pm-nav-links" id="pm-nav-links">'
        f'<a href="{work}">Work</a>'
        f'<a href="{about}">About</a>'
        '<a href="#contact">Contact</a>'
        f'<a class="ds-btn ds-btn--secondary" href="{RESUME_URL}" target="_blank" rel="noopener">Resume'
        '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M7 17 17 7M7 7h10v10"/></svg></a>'
        '</div></nav>' + NAV_JS
    )

# ---- hand-built hero (replaces the Framer-exported Hero section) ----------
HERO_CSS = """
.pm-hero{flex:1 1 auto;display:flex;flex-direction:column;justify-content:center;align-items:center;
  width:1200px;max-width:calc(100vw - 48px);box-sizing:border-box;text-align:center;
  background:var(--ds-paper);border-radius:20px 20px 0 0;padding:56px 40px}
.pm-hero-content{width:100%;max-width:920px;margin:0 auto}
.pm-hero-title{margin:0;font-family:var(--ds-font-display,var(--ds-font-sans));font-weight:600;
  font-size:clamp(34px,5vw,64px);line-height:1.06;letter-spacing:-.02em;color:var(--ds-ink)}
.pm-hero-accent{color:var(--ds-accent)}
.pm-hero-mbreak{display:none}
@media (max-width:767.98px){.pm-hero-mbreak{display:inline}}
.pm-hero-sub{margin:20px auto 0;max-width:620px;font-family:var(--ds-font-sans);
  font-size:clamp(16px,1.35vw,20px);line-height:1.5;color:var(--ds-ink-soft)}
.pm-hero .pm-hero-cta{margin-top:36px}
@media (max-width:767.98px){
  .pm-hero{width:calc(100vw - 32px);padding:40px 20px;border-radius:24px 24px 0 0}
  .pm-hero-title{font-size:clamp(30px,8.5vw,42px);line-height:1.12}
  .pm-hero-sub{font-size:17px}
}
/* entrance (plays after the splash, unless skipped) */
@media (prefers-reduced-motion:no-preference){
  html:not(.pm-no-splash) .pm-hero-title{animation:pm-hero-zoom 1.3s cubic-bezier(.68,0,0,.99) .75s both}
  html:not(.pm-no-splash) .pm-hero-sub,
  html:not(.pm-no-splash) .pm-hero .pm-hero-cta{animation:pm-hero-fade 1.2s cubic-bezier(.68,0,0,1) 1.9s both}
}
"""

# ---- hand-built client-logos ticker (replaces the Framer Client Logos strip) ----
# Seamless loop: the track holds TWO identical groups and animates
# translateX(-50%); since each group (logos + trailing gap) is pixel-identical,
# the wrap lands exactly where the first group started, no jerk.
TICKER_LOGOS = [
    ("assets/images/uqBkjQAQVZ6FQAGc94xcLZ0NKs-9052c048.png", "WilyFox logo"),
    ("assets/images/partner-badge.svg", "Partner company logo"),
    ("assets/images/xFJuVZTZCWzqsLxOGyzoypBcwZs-faff6ad8.png", "Josh Talks logo"),
    ("assets/images/4HIqxJjznyKT7GW1sYt3VI23bcQ-45e0d2b9.png", "PFC Club logo"),
    ("assets/images/Fp8qUkVhICa26PEhY5ELOptBPVI-dd71a6de.webp", "The Ranveer Show logo"),
    ("assets/images/1AijdZwonEPf8NVUMMQ6nlw96E-69f4a02f.png", "Partner company logo"),
    ("assets/images/truth-in-app.png", "Truth In App logo"),
    ("assets/images/aumbre.png", "Aumbre logo"),
]

TICKER_CSS = """
.pm-ticker{background:var(--ds-paper);border-top:1px solid var(--ds-border);
  border-radius:0 0 20px 20px;width:1200px;max-width:calc(100vw - 48px);
  box-sizing:border-box;display:flex;align-items:center;gap:48px;padding:28px 40px 32px}
.pm-ticker-label{flex:none;margin:0;font:400 15px/1.4 var(--ds-font-sans);color:var(--ds-ink-soft)}
.pm-ticker-view{flex:1 1 auto;min-width:0;overflow:hidden;
  -webkit-mask:linear-gradient(90deg,transparent,#000 48px,#000 calc(100% - 48px),transparent);
  mask:linear-gradient(90deg,transparent,#000 48px,#000 calc(100% - 48px),transparent)}
.pm-ticker-track{display:flex;width:max-content;animation:pm-ticker-scroll 24s linear infinite}
.pm-ticker-group{display:flex;align-items:center;gap:56px;padding-right:56px;flex:none}
.pm-ticker-group img{height:32px;width:auto;display:block}
@keyframes pm-ticker-scroll{to{transform:translateX(-50%)}}
@media (max-width:767.98px){
  .pm-ticker{flex-direction:column;align-items:flex-start;gap:18px;
    padding:24px 20px 28px;width:calc(100vw - 32px);border-radius:0 0 24px 24px}
  .pm-ticker-view{width:100%;
    -webkit-mask:linear-gradient(90deg,transparent,#000 24px,#000 calc(100% - 24px),transparent);
    mask:linear-gradient(90deg,transparent,#000 24px,#000 calc(100% - 24px),transparent)}
  .pm-ticker-track{animation-duration:14s}
  .pm-ticker-group{gap:40px;padding-right:40px}
}
@media (prefers-reduced-motion:no-preference){
  html:not(.pm-no-splash) .pm-ticker{animation:pm-hero-fade 1.2s cubic-bezier(.68,0,0,1) 2.4s both}
}
@media (prefers-reduced-motion:reduce){.pm-ticker-track{animation:none}}
"""

def build_ticker(prefix):
    imgs = "".join(
        f'<img src="{prefix}{src}" alt="{alt}" loading="lazy">' for src, alt in TICKER_LOGOS)
    # each half repeats the set twice so it always exceeds the visible window
    # (half ~1057px vs max window ~893px), otherwise the wrap shows a gap
    group = imgs + imgs
    return (
        '<div class="pm-ticker">'
        "<p class=\"pm-ticker-label\">Companies I've worked with</p>"
        '<div class="pm-ticker-view"><div class="pm-ticker-track">'
        f'<div class="pm-ticker-group">{group}</div>'
        f'<div class="pm-ticker-group" aria-hidden="true">{group}</div>'
        '</div></div></div>'
    )

# ---- hand-built footer (replaces the Framer footer component) --------------
PM_SOCIAL = [
    ("X", "https://x.com/thepurvangmehta",
     "M18.9 1.15h3.68l-8.04 9.19L24 22.85h-7.4l-5.8-7.59-6.64 7.59H.47l8.6-9.83L0 1.15h7.6l5.24 6.93 6.06-6.93Zm-1.29 19.5h2.04L6.49 3.24H4.3l13.31 17.4Z"),
    ("Threads", "https://www.threads.net/@thepurvangmehta",
     "M12.19 24h-.01c-3.58-.02-6.33-1.2-8.18-3.51C2.35 18.44 1.5 15.59 1.47 12.01v-.02c.03-3.58.88-6.43 2.53-8.48C5.85 1.2 8.6.02 12.18 0h.01c2.75.02 5.04.73 6.83 2.1 1.68 1.29 2.86 3.13 3.51 5.47l-2.04.57c-1.1-3.96-3.9-5.98-8.3-6.01-2.91.02-5.11.94-6.54 2.72C4.31 6.5 3.62 8.91 3.59 12c.03 3.09.72 5.5 2.06 7.16 1.43 1.78 3.63 2.7 6.54 2.72 2.62-.02 4.36-.63 5.8-2.05 1.65-1.61 1.62-3.59 1.09-4.8-.31-.71-.87-1.3-1.63-1.75-.19 1.35-.62 2.45-1.28 3.27-.89 1.1-2.14 1.7-3.73 1.79-1.2.07-2.36-.22-3.26-.8-1.06-.69-1.69-1.74-1.75-2.96-.07-1.19.41-2.29 1.33-3.08.88-.76 2.12-1.21 3.58-1.29a13.85 13.85 0 0 1 3.02.14c-.13-.74-.38-1.33-.75-1.76-.51-.59-1.31-.88-2.36-.89h-.03c-.84 0-1.99.23-2.72 1.32L7.73 7.85c.98-1.45 2.57-2.26 4.48-2.26h.04c3.19.02 5.1 1.98 5.29 5.39l.32.14c1.49.7 2.58 1.76 3.15 3.07.8 1.82.87 4.79-1.55 7.16C17.62 23.16 15.37 23.98 12.19 24Zm1-11.69c-.24 0-.49.01-.74.02-1.84.1-2.98.95-2.92 2.14.07 1.26 1.45 1.84 2.78 1.77 1.22-.07 2.82-.54 3.09-3.71a10.5 10.5 0 0 0-2.21-.22Z"),
    ("Instagram", "https://www.instagram.com/thepurvangmehta",
     "M12 2.16c3.2 0 3.58.01 4.85.07 1.17.05 1.8.25 2.23.41.56.22.96.48 1.38.9.42.42.68.82.9 1.38.16.42.36 1.06.41 2.23.06 1.27.07 1.65.07 4.85s-.01 3.58-.07 4.85c-.05 1.17-.25 1.8-.41 2.23-.22.56-.48.96-.9 1.38-.42.42-.82.68-1.38.9-.42.16-1.06.36-2.23.41-1.27.06-1.65.07-4.85.07s-3.58-.01-4.85-.07c-1.17-.05-1.8-.25-2.23-.41a3.7 3.7 0 0 1-1.38-.9 3.7 3.7 0 0 1-.9-1.38c-.16-.42-.36-1.06-.41-2.23-.06-1.27-.07-1.65-.07-4.85s.01-3.58.07-4.85c.05-1.17.25-1.8.41-2.23.22-.56.48-.96.9-1.38.42-.42.82-.68 1.38-.9.42-.16 1.06-.36 2.23-.41 1.27-.06 1.65-.07 4.85-.07M12 0C8.74 0 8.33.01 7.05.07 5.78.13 4.9.33 4.14.63c-.79.31-1.46.72-2.13 1.38A5.9 5.9 0 0 0 .63 4.14c-.3.76-.5 1.64-.56 2.91C.01 8.33 0 8.74 0 12s.01 3.67.07 4.95c.06 1.27.26 2.15.56 2.91.31.79.72 1.46 1.38 2.13.67.66 1.34 1.07 2.13 1.38.76.3 1.64.5 2.91.56C8.33 23.99 8.74 24 12 24s3.67-.01 4.95-.07c1.27-.06 2.15-.26 2.91-.56.79-.31 1.46-.72 2.13-1.38.66-.67 1.07-1.34 1.38-2.13.3-.76.5-1.64.56-2.91.06-1.28.07-1.69.07-4.95s-.01-3.67-.07-4.95c-.06-1.27-.26-2.15-.56-2.91a5.9 5.9 0 0 0-1.38-2.13A5.9 5.9 0 0 0 19.86.63c-.76-.3-1.64-.5-2.91-.56C15.67.01 15.26 0 12 0Zm0 5.84A6.16 6.16 0 1 0 12 18.16 6.16 6.16 0 0 0 12 5.84Zm0 10.16A4 4 0 1 1 12 8a4 4 0 0 1 0 8Zm7.85-10.4a1.44 1.44 0 1 1-2.88 0 1.44 1.44 0 0 1 2.88 0Z"),
    ("Dribbble", "https://dribbble.com/thepurvangmehta",
     "M12 24C5.39 24 0 18.62 0 12S5.39 0 12 0s12 5.39 12 12-5.39 12-12 12Zm10.12-10.36c-.35-.11-3.17-.95-6.38-.44 1.34 3.68 1.89 6.68 1.99 7.31 2.3-1.56 3.94-4.02 4.39-6.87Zm-6.11 7.81c-.15-.9-.75-4.03-2.19-7.77l-.07.02c-5.79 2.02-7.86 6.03-8.04 6.4a10.2 10.2 0 0 0 6.29 2.17c1.42 0 2.77-.29 4.01-.82Zm-11.62-2.58c.23-.4 3.04-5.06 8.33-6.77l.4-.12c-.26-.59-.54-1.17-.83-1.74C7.17 11.78 2.21 11.71 1.76 11.7v.31c0 2.63 1 5.04 2.63 6.86Zm-2.42-8.96c.46.01 4.68.03 9.48-1.25a65.8 65.8 0 0 0-3.8-5.93 10.23 10.23 0 0 0-5.68 7.18ZM9.6 2.05c.28.38 2.15 2.91 3.82 6 3.65-1.37 5.19-3.44 5.37-3.7A10.15 10.15 0 0 0 12 1.76c-.83 0-1.63.1-2.4.29Zm10.34 3.49c-.22.29-1.94 2.49-5.72 4.04.24.49.47.98.68 1.48.08.18.15.36.22.53 3.41-.43 6.8.26 7.14.33a10.2 10.2 0 0 0-2.32-6.38Z"),
    ("Behance", "https://www.behance.net/thepurvangmehta",
     "M22 7h-7V5h7v2Zm1.73 10c-.44 1.3-2.03 3-5.1 3-3.07 0-5.56-1.73-5.56-5.68 0-3.91 2.32-5.92 5.47-5.92 3.08 0 4.96 1.78 5.37 4.43.08.5.11 1.19.1 2.14H15.97c.13 3.21 3.48 3.31 4.59 2.03h3.17Zm-7.69-4h4.97c-.11-1.55-1.14-2.22-2.48-2.22-1.47 0-2.28.77-2.49 2.22Zm-9.57 6.99H0V5.02h6.95c5.48.08 5.58 5.44 2.72 6.9 3.46 1.26 3.58 8.07-3.2 8.07ZM3 11h3.58c2.51 0 2.91-3-.31-3H3v3Zm3.39 3H3v3.02h3.34c3.06 0 2.87-3.02.05-3.02Z"),
    ("LinkedIn", "https://www.linkedin.com/in/thepurvangmehta/",
     "M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28ZM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13Zm1.78 13.02H3.56V9h3.56v11.45ZM22.23 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.23 0Z"),
]

FOOTER_CSS = """
.pm-footer{--pm-fg:var(--ds-ink,rgb(25,25,25));--pm-mut:rgb(140,140,140);--pm-sub:var(--ds-ink-soft,rgb(77,77,77));--pm-acc:var(--ds-accent,rgb(28,53,236));
  position:relative;background:var(--ds-paper,#fff);color:var(--pm-fg);overflow:hidden;padding:88px 40px 0}
.pm-footer-inner{max-width:var(--ds-container);margin:0 auto;position:relative;z-index:1}
.pm-footer-cta{margin:0 0 64px;font-family:var(--ds-font-display,var(--ds-font-sans));font-weight:600;
  font-size:clamp(34px,4.2vw,54px);line-height:1.1;letter-spacing:-.02em;color:var(--pm-mut)}
.pm-footer-cta .pm-lead{color:var(--pm-fg)}
.pm-footer-cycle{color:var(--pm-acc);transition:opacity .3s ease}
.pm-footer-cols{display:grid;grid-template-columns:repeat(3,1fr);gap:32px;padding-bottom:36px}
.pm-footer-label{margin:0 0 16px;font:500 13px/1 var(--ds-font-sans);color:var(--pm-sub);letter-spacing:.01em}
.pm-footer-links{display:flex;flex-direction:column;gap:12px;align-items:flex-start}
.pm-footer-link{display:inline-block;font:500 16px/1.4 var(--ds-font-sans);color:var(--pm-fg);
  text-decoration:none;transition:color .15s ease}
.pm-footer-link:hover{color:var(--pm-acc)}
.pm-footer-social{display:flex;gap:12px}
.pm-footer-social a{width:44px;height:44px;flex:none;border-radius:50%;background:var(--ds-ink,#191919);
  display:inline-flex;align-items:center;justify-content:center;
  transition:transform .18s ease,background .18s ease}
.pm-footer-social a:hover{transform:translateY(-2px);background:var(--pm-acc)}
.pm-footer-social svg{width:19px;height:19px;display:block;fill:#fff;transition:fill .18s ease}
.pm-footer-social a:hover svg{fill:#fff}
.pm-footer-rule{border:0;border-top:1px solid var(--ds-border,rgba(0,0,0,.12));margin:0}
.pm-footer-bottom{display:grid;grid-template-columns:repeat(3,1fr);gap:32px;padding-top:36px;align-items:start}
.pm-footer-copy{margin:0;grid-column:3;justify-self:end;font:500 13px/1 var(--ds-font-sans);color:var(--pm-sub)}
/* sized to fit the full 'PURVANG' word on every width (text ~= 4.35x font-size),
   capped so it doesn't get oversized on large desktops */
.pm-footer-mark{position:relative;z-index:0;text-align:center;margin:40px 0 -.14em;
  font-family:var(--ds-font-display,var(--ds-font-sans));font-weight:700;font-size:clamp(64px,20vw,300px);
  line-height:.82;letter-spacing:-.03em;color:rgba(0,0,0,.05);user-select:none;white-space:nowrap;pointer-events:none}
@media (max-width:767.98px){
  .pm-footer{padding:56px 20px 0}
  .pm-footer-cta{margin-bottom:44px}
  .pm-footer-cols{grid-template-columns:1fr;gap:26px;padding-bottom:28px}
  .pm-footer-bottom{grid-template-columns:1fr;gap:22px;padding-top:28px}
  .pm-footer-copy{grid-column:1;justify-self:start}
}
"""

FOOTER_JS = ("<script>(function(){var el=document.querySelector('.pm-footer-cycle');if(!el)return;"
             "var w=['design','build','create'],i=0;setInterval(function(){i=(i+1)%w.length;"
             "el.style.opacity='0';setTimeout(function(){el.textContent=w[i];el.style.opacity='1';},280);},2600);})();</script>")

def build_footer(prefix):
    terms = prefix + "terms/"
    privacy = prefix + "privacy-policy/"
    social = "".join(
        f'<a href="{href}" target="_blank" rel="noopener" aria-label="{name}">'
        f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="{path}"/></svg></a>'
        for name, href, path in PM_SOCIAL)
    return (
        '<footer class="pm-footer" id="contact"><div class="pm-footer-inner">'
        '<h2 class="pm-footer-cta"><span class="pm-lead">Lets</span> '
        '<span class="pm-footer-cycle">design</span><br>incredible work together.</h2>'
        '<div class="pm-footer-cols">'
        '<div><p class="pm-footer-label">Email</p>'
        '<a class="pm-footer-link" href="mailto:thepurvangmehta@gmail.com">thepurvangmehta@gmail.com</a></div>'
        '<div><p class="pm-footer-label">Call Me</p>'
        '<a class="pm-footer-link" href="https://cal.com/thepurvangmehta" target="_blank" rel="noopener">Book Now</a></div>'
        '<div><p class="pm-footer-label">Social</p>'
        f'<div class="pm-footer-social">{social}</div></div>'
        '</div>'
        '<hr class="pm-footer-rule">'
        '<div class="pm-footer-bottom">'
        '<div><p class="pm-footer-label">Legal</p><div class="pm-footer-links">'
        f'<a class="pm-footer-link" href="{terms}">Terms of service</a>'
        f'<a class="pm-footer-link" href="{privacy}">Privacy Policy</a></div></div>'
        '<p class="pm-footer-copy">© 2026 Purvang Mehta</p>'
        '</div></div>'
        '<div class="pm-footer-mark" aria-hidden="true">PURVANG</div>'
        '</footer>' + FOOTER_JS
    )

# ============================================================================
# CONTENT-DRIVEN CASE STUDIES (templatized, CMS-style)
# A case study is a content/<slug>.json file: metadata + an ordered list of
# typed section blocks. render_case_study() turns that data into a full page,
# reusing the shared head (fonts/GA/SEO/design-system), nav, and footer.
# This decouples case-study structure+content from the Framer snapshots.
# ============================================================================

CS_IMG_WIDTHS = [512, 1024, 1600, 2240]

def _esc(s):
    return _htmlmod.escape(str(s or ""), quote=True)

def _accent(s):
    """Escape text, then turn **phrase** into an accent-colored span."""
    parts = _htmlmod.escape(str(s or ""), quote=False).split("**")
    out = ""
    for i, p in enumerate(parts):
        out += p if i % 2 == 0 else f'<span class="cs-accent">{p}</span>'
    return out

def _cs_best_source(hash_id):
    """Pick the highest-resolution on-disk variant for a Framer asset hash."""
    best, bestw = None, -1
    for f in glob.glob(str(OUT / "assets" / "images" / f"{hash_id}-*")):
        try:
            w, h = Image.open(f).size
        except Exception:
            continue
        if w > bestw:
            bestw, best = w, (f, w, h)
    return best

def cs_image(hash_id, alt, prefix, layout="full"):
    """Resolve a case-study image to a responsive, optimized webp set.
    Auto-selects the sharpest source variant and emits 1x..2x widths."""
    src = _cs_best_source(hash_id)
    if not src:
        print(f"  CS WARN: no source found for image {hash_id}")
        return None
    path, sw, sh = src
    ratio = (sw / sh) if sh else 1.6
    outdir = OUT / "assets" / "cs"
    outdir.mkdir(parents=True, exist_ok=True)
    widths = [w for w in CS_IMG_WIDTHS if w <= sw] or [min(sw, CS_IMG_WIDTHS[0])]
    im = None
    srcset = []
    for w in widths:
        outp = outdir / f"{hash_id}-{w}.webp"
        if not outp.exists():
            if im is None:
                im = Image.open(path)
                im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
            h = max(1, round(w / ratio))
            im.resize((w, h), Image.LANCZOS).save(outp, "WEBP", quality=82, method=6)
        srcset.append(f"{prefix}assets/cs/{hash_id}-{w}.webp {w}w")
    sizes = {
        "full": "(max-width:1120px) 92vw, 1040px",
        "pair": "(max-width:760px) 92vw, 520px",
        "grid": "(max-width:760px) 92vw, 33vw",
    }.get(layout, "100vw")
    return {"src": f"{prefix}assets/cs/{hash_id}-{widths[-1]}.webp",
            "srcset": ", ".join(srcset), "sizes": sizes,
            "ratio": round(ratio, 4), "alt": alt or ""}

def _cs_figure(img):
    if not img:
        return ""
    cap = (f'<figcaption class="cs-caption">{_esc(img["caption"])}</figcaption>'
           if img.get("caption") else "")
    # no panel/box: the image is shown directly, rounded corners only
    cls = "cs-fig cs-fig--portrait" if img.get("ratio", 1.6) < 1 else "cs-fig"
    return (f'<figure class="{cls}">'
            f'<img loading="lazy" decoding="async" src="{img["src"]}" '
            f'srcset="{img["srcset"]}" sizes="{img["sizes"]}" alt="{_esc(img["alt"])}">{cap}</figure>')

def _cs_media(media, prefix):
    """Strict, count-driven image layout. The number of images alone decides
    the grid (the JSON `layout` field is ignored): 1=full, 2=two-up, 3=three-up,
    4=2x2, 5+=three-up wrap. Images carry no panel; rounded corners only."""
    imgs = media.get("images", [])
    n = len(imgs)
    # 1 = full, 2 = two-up, 3+ = horizontal scroller (keeps images readable)
    variant = "1" if n == 1 else ("2" if n == 2 else "scroll")
    size_hint = "full" if n == 1 else "pair"
    figs = ""
    count = 0
    for i in imgs:
        img = cs_image(i["img"], i.get("alt", ""), prefix, size_hint)
        if not img:
            continue
        if i.get("caption"):
            img["caption"] = i["caption"]
        figs += _cs_figure(img)
        count += 1
    if variant == "scroll":
        # pagination dots signal (and drive) the horizontal scroll
        dots = "".join(
            f'<button class="cs-media-dot" type="button" aria-label="Show image {k + 1}"></button>'
            for k in range(count))
        return (f'<div class="cs-media cs-media--scroll">'
                f'<div class="cs-scroll-track">{figs}</div>'
                f'<div class="cs-scroll-dots">{dots}</div></div>')
    return f'<div class="cs-media cs-media--{variant}">{figs}</div>'

def _cs_hero(b, prefix):
    sub = f'<p class="cs-sub">{_esc(b["subtitle"])}</p>' if b.get("subtitle") else ""
    return (f'<header class="cs-hero">'
            f'<h1 class="cs-title">{_accent(b["title"])}</h1>{sub}</header>')

def _cs_facts(b, prefix):
    items = "".join(
        f'<div><p class="cs-fact-label">{_esc(it["label"])}</p>'
        f'<p class="cs-fact-value">{_esc(it["value"])}</p></div>'
        for it in b.get("items", []))
    return f'<div class="cs-facts">{items}</div>'

def _cs_stats(b, prefix):
    eb = f'<p class="cs-eyebrow">{_esc(b["eyebrow"])}</p>' if b.get("eyebrow") else ""
    items = "".join(
        f'<div class="cs-stat"><p class="cs-stat-value">{_esc(it["value"])}</p>'
        f'<p class="cs-stat-desc">{_esc(it["desc"])}</p></div>'
        for it in b.get("items", []))
    return f'<section class="cs-stats">{eb}<div class="cs-stats-grid">{items}</div></section>'

def _cs_body(items):
    """Body items are either plain strings (paragraphs) or {h,p} sub-headed blocks."""
    out = ""
    for it in items or []:
        if isinstance(it, dict):
            if it.get("h"):
                out += f'<p class="cs-body-h">{_esc(it["h"])}</p>'
            if it.get("p"):
                out += f'<p>{_esc(it["p"])}</p>'
        else:
            out += f"<p>{_esc(it)}</p>"
    return f'<div class="cs-body">{out}</div>' if out else ""

def _cs_overview(b, prefix):
    eb = f'<p class="cs-eyebrow">{_esc(b["eyebrow"])}</p>' if b.get("eyebrow") else ""
    items = "".join(
        f'<div class="cs-ov-item"><p class="cs-ov-label">{_esc(it["label"])}</p>'
        f'<p class="cs-ov-value">{_esc(it["value"])}</p></div>'
        for it in b.get("items", []))
    return f'<section class="cs-block cs-overview">{eb}<div class="cs-ov-grid">{items}</div></section>'

def _cs_cards(b, prefix):
    eb = f'<p class="cs-eyebrow">{_esc(b["eyebrow"])}</p>' if b.get("eyebrow") else ""
    title = f'<h2 class="cs-h2">{_accent(b["title"])}</h2>' if b.get("title") else ""
    intro = _cs_body(b.get("intro") if isinstance(b.get("intro"), list) else ([b["intro"]] if b.get("intro") else []))
    cards = "".join(
        f'<div class="cs-card">'
        + (f'<p class="cs-card-kicker">{_esc(it["kicker"])}</p>' if it.get("kicker") else "")
        + f'<p class="cs-card-title">{_esc(it["title"])}</p>'
        + (f'<p class="cs-card-desc">{_esc(it["desc"])}</p>' if it.get("desc") else "")
        + '</div>'
        for it in b.get("items", []))
    return f'<section class="cs-block">{eb}{title}{intro}<div class="cs-cards">{cards}</div></section>'

def _cs_section(b, prefix):
    num = f'<span class="cs-num">{_esc(b["number"])}</span>' if b.get("number") else ""
    eb = f'<p class="cs-eyebrow">{_esc(b["eyebrow"])}</p>' if b.get("eyebrow") else ""
    title = f'<h2 class="cs-h2">{_accent(b["title"])}</h2>' if b.get("title") else ""
    body = _cs_body(b.get("body", []))
    chips = ""
    if b.get("chips"):
        chips = '<div class="cs-chips">' + "".join(
            f'<span class="cs-chip">{_esc(c)}</span>' for c in b["chips"]) + "</div>"
    media = _cs_media(b["media"], prefix) if b.get("media") else ""
    head = f'<div class="cs-head">{num}{eb}{title}</div>'
    content = f'<div class="cs-content">{body}{chips}</div>' if (body or chips) else ""
    cls = "cs-block cs-block--split" + (" cs-block--numbered" if b.get("number") else "")
    return f'<section class="{cls}">{head}{content}{media}</section>'

def _cs_steps(b, prefix):
    eb = f'<p class="cs-eyebrow">{_esc(b["eyebrow"])}</p>' if b.get("eyebrow") else ""
    title = f'<h2 class="cs-h2">{_accent(b["title"])}</h2>' if b.get("title") else ""
    intro = f'<div class="cs-body"><p>{_esc(b["intro"])}</p></div>' if b.get("intro") else ""
    items = "".join(
        f'<div class="cs-step"><p class="cs-step-n">{_esc(it["step"])}</p>'
        f'<p class="cs-step-name">{_esc(it["name"])}</p>'
        f'<p class="cs-step-desc">{_esc(it["desc"])}</p></div>'
        for it in b.get("items", []))
    return (f'<section class="cs-block">{eb}{title}{intro}'
            f'<div class="cs-steps-grid">{items}</div></section>')

def _cs_media_block(b, prefix):
    return f'<section class="cs-block cs-media-block">{_cs_media(b, prefix)}</section>'

def _cs_testimonial(b, prefix):
    attr = f'<p class="cs-quote-attr">{_esc(b["attribution"])}</p>' if b.get("attribution") else ""
    return (f'<section class="cs-quote"><blockquote>&ldquo;{_esc(b["quote"])}&rdquo;</blockquote>'
            f'{attr}</section>')

def _cs_lessons(b, prefix):
    eb = f'<p class="cs-eyebrow">{_esc(b["eyebrow"])}</p>' if b.get("eyebrow") else ""
    title = f'<h2 class="cs-h2">{_accent(b["title"])}</h2>' if b.get("title") else ""
    items = "".join(
        f'<div class="cs-lesson"><p class="cs-lesson-title">{_esc(it["title"])}</p>'
        f'<p class="cs-lesson-body">{_esc(it["body"])}</p></div>'
        for it in b.get("items", []))
    return (f'<section class="cs-block">{eb}{title}'
            f'<div class="cs-lessons-grid">{items}</div></section>')

def _cs_showreel(b, prefix):
    """Top-of-page motion reel. Renders an autoplay/muted/loop <video> when
    `video` is set (a filename or list of filenames under assets/video/).
    Until a video exists, EVERY case study shows the same shared gradient
    placeholder (assets/images/hero-placeholder.webp) for consistency.
    `ratio` sets the video frame (default 16/9)."""
    ratio = b.get("ratio", "16 / 9")
    vids = b.get("video")
    if isinstance(vids, str):
        vids = [vids]
    cap = (f'<figcaption class="cs-caption">{_esc(b["caption"])}</figcaption>'
           if b.get("caption") else "")
    if vids:
        srcs = "".join(
            f'<source src="{prefix}assets/video/{v}" '
            f'type="video/{"webm" if v.lower().endswith(".webm") else "mp4"}">'
            for v in vids)
        poster_img = cs_image(b["poster"], b.get("alt", ""), prefix, "full") if b.get("poster") else None
        poster_attr = f' poster="{poster_img["src"]}"' if poster_img else ""
        media = ('<video class="cs-reel-video" autoplay muted loop playsinline '
                 f'preload="metadata"{poster_attr}>{srcs}'
                 '<span class="cs-reel-placeholder">Your browser cannot play this video.</span>'
                 '</video>')
    else:
        # shared gradient placeholder — consistent across every case study
        media = ('<img class="cs-reel-video cs-reel-video--img" loading="eager" decoding="async" '
                 f'src="{prefix}assets/images/hero-placeholder.webp" alt="">')
    return (f'<section class="cs-reel" style="--reel-ratio:{ratio}">'
            f'<figure class="cs-reel-fig">{media}{cap}</figure></section>')

CS_RENDERERS = {
    "hero": _cs_hero, "facts": _cs_facts, "overview": _cs_overview, "stats": _cs_stats,
    "section": _cs_section, "steps": _cs_steps, "cards": _cs_cards, "media": _cs_media_block,
    "testimonial": _cs_testimonial, "lessons": _cs_lessons, "showreel": _cs_showreel,
}

CS_GATE_PBKDF2_ITERS = 250000

def _cs_encrypt(plaintext, password):
    """AES-256-GCM encrypt a gated case-study body so only ciphertext ships.
    Key = PBKDF2-HMAC-SHA256(password, random salt). The password never ships;
    only salt + iv + ciphertext(+tag) do, base64-encoded, for the in-browser
    Web Crypto gate to decrypt. Interoperable with crypto.subtle."""
    from Crypto.Cipher import AES
    salt, iv = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                              CS_GATE_PBKDF2_ITERS, dklen=32)
    ct, tag = AES.new(key, AES.MODE_GCM, nonce=iv).encrypt_and_digest(
        plaintext.encode("utf-8"))
    b64 = lambda x: base64.b64encode(x).decode("ascii")
    return {"salt": b64(salt), "iv": b64(iv), "data": b64(ct + tag),
            "iters": CS_GATE_PBKDF2_ITERS}

# In-browser gate: derive the key from the typed password via Web Crypto and
# decrypt the embedded blob. No password or plaintext is present in the page;
# a wrong password simply fails to decrypt (GCM auth), so there is nothing to
# read via view-source, curl, or a disabled-JS crawl.
CS_GATE_JS = (
    "<script>(function(){"
    "var g=document.getElementById('pm-cs-gate'),b=document.getElementById('pm-cs-blob'),"
    "doc=document.getElementById('pm-cs-doc');"
    "if(!g||!b||!doc)return;"
    "var blob=JSON.parse(b.textContent);"
    "document.documentElement.style.overflow='hidden';"
    "var f=g.querySelector('form'),i=g.querySelector('input'),"
    "e=g.querySelector('.cs-gate-err'),btn=g.querySelector('button');"
    "function u8(s){var n=atob(s),a=new Uint8Array(n.length);"
    "for(var k=0;k<n.length;k++)a[k]=n.charCodeAt(k);return a;}"
    "f.addEventListener('submit',function(ev){ev.preventDefault();"
    "e.hidden=true;btn.disabled=true;"
    "crypto.subtle.importKey('raw',new TextEncoder().encode(i.value),{name:'PBKDF2'},false,['deriveKey'])"
    ".then(function(bk){return crypto.subtle.deriveKey("
    "{name:'PBKDF2',salt:u8(blob.salt),iterations:blob.iters,hash:'SHA-256'},"
    "bk,{name:'AES-GCM',length:256},false,['decrypt']);})"
    ".then(function(key){return crypto.subtle.decrypt("
    "{name:'AES-GCM',iv:u8(blob.iv)},key,u8(blob.data));})"
    ".then(function(buf){doc.innerHTML=new TextDecoder().decode(buf);"
    "g.remove();document.documentElement.style.overflow='';"
    "if(window.pmCsToc)window.pmCsToc();if(window.pmCsReveal)window.pmCsReveal();"
    "if(window.pmCsReel)window.pmCsReel();if(window.pmCsMedia)window.pmCsMedia();})"
    ".catch(function(){btn.disabled=false;e.hidden=false;i.value='';i.focus();});});"
    "setTimeout(function(){i.focus();},60);})();</script>")

CS_NICE_NAMES = {
    "turfly": "Turfly", "healthcare": "SimpleTherapy onboarding",
    "communication-saas": "Communication SaaS", "nda": "Private project",
}

def _cs_project_meta(slug):
    """slug -> {slug, next, name, poster} read from its content JSON."""
    if not slug:
        return None
    p = ROOT / "content" / f"{slug}.json"
    if not p.exists():
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return None
    # prefer the explicit project thumbnail (same cover used on home/work),
    # then the showreel poster, then the first media image
    thumb = d.get("thumbnail")
    if not thumb:
        for b in d.get("blocks", []):
            if b.get("type") == "showreel" and b.get("poster"):
                thumb = b["poster"]; break
    if not thumb:
        for b in d.get("blocks", []):
            if b.get("type") == "media" and b.get("images"):
                thumb = b["images"][0].get("img"); break
    return {"slug": slug, "next": d.get("next"), "thumb": thumb,
            "name": CS_NICE_NAMES.get(slug, slug.replace("-", " ").title())}

def _cs_next_projects(data, prefix):
    """'Ready for next?' — the next two case studies as thumbnail cards
    (follows the next-chain, skips the current one)."""
    cur = data.get("slug")
    seq, slug = [], data.get("next")
    while slug and slug != cur and all(m["slug"] != slug for m in seq) and len(seq) < 2:
        m = _cs_project_meta(slug)
        if not m:
            break
        seq.append(m); slug = m["next"]
    arrow = ('<svg class="cs-more-arrow" viewBox="0 0 24 24" width="18" height="18" fill="none" '
             'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
             '<path d="M5 12h14M12 5l7 7-7 7"/></svg>')
    cards = ""
    for m in seq:
        thumb = ""
        if m["thumb"]:
            img = cs_image(m["thumb"], "", prefix, "pair")
            if img:
                thumb = (f'<img src="{img["src"]}" srcset="{img["srcset"]}" '
                         'sizes="(max-width:760px) 92vw, 46vw" alt="" loading="lazy" decoding="async">')
        cards += (f'<a class="cs-more-card" href="{prefix}{m["slug"]}/">'
                  f'<span class="cs-more-thumb">{thumb}</span>'
                  f'<span class="cs-more-foot"><span class="cs-more-name">{_esc(m["name"])}</span>'
                  f'{arrow}</span></a>')
    if not cards:
        return ""
    return ('<section class="cs-more"><div class="cs-more-inner">'
            '<h2 class="cs-more-title">Ready for next?</h2>'
            f'<div class="cs-more-grid">{cards}</div></div></section>')

def build_cta(prefix):
    """The single, canonical contact CTA ("In some other universe...").

    This is the ONE closing CTA used everywhere on the site. The old Framer
    black/yellow variant has been retired; never reintroduce a second version.
    Returns the full-bleed grey band section so it can be dropped into any page.
    """
    # illustration panel: prefer an animated mascot if one has been dropped in
    # (assets/images/closing-mascot.gif|webp or assets/video/closing-mascot.mp4|webm),
    # otherwise fall back to the static mascot asset in the repo.
    art_html = ""
    for fn in ("closing-mascot.gif", "closing-mascot.webp", "closing-mascot.png"):
        if (OUT / "assets" / "images" / fn).exists():
            art_html = (f'<img class="cs-closing-media" src="{prefix}assets/images/{fn}" '
                        'alt="" loading="lazy" decoding="async">')
            break
    if not art_html:
        for fn, mime in (("closing-mascot.mp4", "mp4"), ("closing-mascot.webm", "webm")):
            if (OUT / "assets" / "video" / fn).exists():
                art_html = ('<video class="cs-closing-media" autoplay muted loop playsinline preload="metadata">'
                            f'<source src="{prefix}assets/video/{fn}" type="video/{mime}"></video>')
                break
    if not art_html:
        art = cs_image("6Pg7fbhqux70xMtctNjAPrXByo", "", prefix, "full")
        art_html = (f'<img class="cs-closing-media" src="{art["src"]}" srcset="{art["srcset"]}" '
                    f'sizes="(max-width:760px) 92vw, 340px" alt="" loading="lazy" decoding="async">'
                    if art else "")
    # social row: uniform icon buttons
    show = ("X", "Instagram", "Dribbble", "Behance", "LinkedIn")
    socs = "".join(
        f'<a class="cs-soc" href="{href}" target="_blank" rel="noopener" aria-label="{name}">'
        f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="{path}"/></svg></a>'
        for name, href, path in PM_SOCIAL if name in show)
    # CTA sits in its own full-bleed grey band (differentiated from the white body)
    cta = ('<section class="cs-closing"><div class="cs-closing-inner">'
           '<div class="cs-closing-card">'
           f'<div class="cs-closing-art">{art_html}</div>'
           '<div class="cs-closing-panel">'
           '<p class="cs-closing-kicker">You&rsquo;ve made it to the end of quite the scroll.. Great job!</p>'
           '<h2 class="cs-closing-title">In some other universe, we&rsquo;re already friends. '
           '<span class="cs-closing-dim">So why not in this one?</span></h2>'
           '<div class="cs-closing-actions">'
           '<a class="ds-btn ds-btn--secondary cs-cta" href="#contact">Let&rsquo;s Connect</a>'
           f'<div class="cs-closing-socials">{socs}</div>'
           '</div></div></div></div></section>')
    return cta

def _cs_closing(data, prefix):
    # CTA sits first on white; 'Ready for next?' follows on a grey band
    return build_cta(prefix) + _cs_next_projects(data, prefix)

def _cs_gate(data):
    """Clean NDA password gate (replaces the Framer gate for content pages)."""
    return ('<div id="pm-cs-gate" class="cs-gate"><div class="cs-gate-card">'
            '<h2 class="cs-gate-title">Enter Password</h2>'
            '<p class="cs-gate-sub">This case study is under NDA. Enter the password to view it, or '
            f'<a href="mailto:{CONTACT_EMAIL}?subject=Case%20study%20access">email me for access</a>.</p>'
            '<form class="cs-gate-form"><input type="password" class="cs-gate-input" '
            'placeholder="Enter password" aria-label="Password" autocomplete="off">'
            '<button type="submit" class="ds-btn ds-btn--primary cs-gate-btn">Continue</button>'
            '<p class="cs-gate-err" hidden>Incorrect password. Try again.</p></form>'
            '</div></div>')

def _cs_slug(text):
    s = re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-')
    return "cs-" + (s or "section")

# blocks that become jump-nav / scroll-spy targets (when they carry a label)
CS_NAV_TYPES = {"section", "steps", "cards", "overview", "stats", "lessons"}

CS_TOC_JS = (
    "<script>window.pmCsToc=function(){"
    "var links=[].slice.call(document.querySelectorAll('.cs-toc a'));"
    "if(!links.length)return;"
    "var map={};links.forEach(function(a){var id=a.getAttribute('href').slice(1);var s=document.getElementById(id);if(s)map[id]=a;});"
    "var ids=Object.keys(map);"
    "function setActive(id){links.forEach(function(a){a.classList.remove('is-active');a.removeAttribute('aria-current');});"
    "var a=map[id];if(a){a.classList.add('is-active');a.setAttribute('aria-current','true');}}"
    "if('IntersectionObserver' in window){"
    "var io=new IntersectionObserver(function(es){"
    "es.forEach(function(e){if(e.isIntersecting)setActive(e.target.id);});"
    "},{rootMargin:'-45% 0px -50% 0px',threshold:0});"
    "ids.forEach(function(id){io.observe(document.getElementById(id));});}"
    "};</script>")

# Subtle scroll reveal. Below-fold blocks fade/slide in as they enter view.
# Above-fold blocks and no-JS / reduced-motion users see everything immediately,
# so content is never gated on the animation.
CS_REVEAL_JS = (
    "<script>window.pmCsReveal=function(){"
    "if(!('IntersectionObserver' in window))return;"
    "if(window.matchMedia&&matchMedia('(prefers-reduced-motion:reduce)').matches)return;"
    "var els=[].slice.call(document.querySelectorAll("
    "'.cs-sec,.cs-media-block,.cs-quote'));"
    "if(!els.length)return;"
    "var io=new IntersectionObserver(function(es){es.forEach(function(e){"
    "if(e.isIntersecting){e.target.classList.add('is-in');io.unobserve(e.target);}});},"
    "{rootMargin:'0px 0px -6% 0px',threshold:0.04});"
    "els.forEach(function(el){"
    "if(el.getBoundingClientRect().top>window.innerHeight*0.92){"
    "el.classList.add('cs-reveal');io.observe(el);}});"
    "};</script>")

# Reduced-motion: don't autoplay the top motion reel; pause it and expose
# controls so the visitor opts in. No-op when there is no reel.
CS_REEL_JS = (
    "<script>window.pmCsReel=function(){"
    "if(!(window.matchMedia&&matchMedia('(prefers-reduced-motion:reduce)').matches))return;"
    "[].forEach.call(document.querySelectorAll('video.cs-reel-video'),function(v){"
    "try{v.pause();v.removeAttribute('autoplay');v.setAttribute('controls','');}catch(e){}});"
    "};</script>")

# Horizontal image scrollers: sync the pagination dots to scroll position,
# let dots jump to an image, and hide the dots when nothing overflows.
CS_MEDIA_JS = (
    "<script>window.pmCsMedia=function(){"
    "[].forEach.call(document.querySelectorAll('.cs-media--scroll'),function(w){"
    "var t=w.querySelector('.cs-scroll-track'),dw=w.querySelector('.cs-scroll-dots');"
    "if(!t||!dw)return;"
    "var figs=[].slice.call(t.querySelectorAll('.cs-fig')),"
    "dots=[].slice.call(dw.querySelectorAll('.cs-media-dot'));"
    "if(!dots.length)return;"
    "function set(i){dots.forEach(function(d,k){d.classList.toggle('is-active',k===i);});}"
    "function active(){var tl=t.getBoundingClientRect().left,best=0,bd=1/0;"
    "figs.forEach(function(f,k){var dd=Math.abs(f.getBoundingClientRect().left-tl);if(dd<bd){bd=dd;best=k;}});return best;}"
    "function refresh(){dw.style.display=(t.scrollWidth>t.clientWidth+2)?'':'none';set(active());}"
    "dots.forEach(function(d,i){d.addEventListener('click',function(){"
    "if(figs[i])figs[i].scrollIntoView({behavior:'smooth',inline:'start',block:'nearest'});});});"
    "var raf;t.addEventListener('scroll',function(){if(raf)return;"
    "raf=requestAnimationFrame(function(){raf=null;set(active());});},{passive:true});"
    "[].forEach.call(t.querySelectorAll('img'),function(im){im.addEventListener('load',refresh);});"
    "window.addEventListener('resize',refresh,{passive:true});refresh();});"
    "};</script>")

def render_case_study(data, prefix, shell):
    """Compose a full case-study document from content data, reusing the
    processed shell's <head> (fonts, GA, SEO, design-system, footer CSS).
    Content sits in a two-part layout: a sticky left 'Scroll to' nav
    (scroll-spy jump list) + the main content column on the right."""
    # Layout: the video reel is a full-bleed banner; the hero title spans the
    # full width; everything else (facts + sections) shares the content column
    # with the sticky sidebar, so they all line up on one clean left edge.
    banner_parts, hero_parts, main_parts, nav_items, seen = [], [], [], [], set()
    for b in data["blocks"]:
        t = b["type"]
        if t not in CS_RENDERERS:
            continue
        html = CS_RENDERERS[t](b, prefix)
        label = b.get("nav") or b.get("eyebrow")
        is_nav = t in CS_NAV_TYPES and bool(label)
        if t == "showreel":
            banner_parts.append(html)       # full-bleed banner, above the layout
            continue
        if t == "hero":
            hero_parts.append(html)         # full-width, above the sidebar layout
            continue
        if is_nav:
            sid = _cs_slug(label)
            n = 2
            base = sid
            while sid in seen:
                sid = f"{base}-{n}"; n += 1
            seen.add(sid)
            nav_items.append((sid, label))
            html = f'<div class="cs-sec" id="{sid}">{html}</div>'
        main_parts.append(html)             # facts + sections, in the content column

    # breadcrumb lives at the top of the sticky sidebar, above the section list
    home = (f'<a class="cs-toc-home" href="{prefix}">'
            '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M19 12H5M12 19l-7-7 7-7"/></svg>Home</a>')
    toc = ""
    if nav_items:
        items = "".join(f'<li><a href="#{sid}">{_esc(label)}</a></li>' for sid, label in nav_items)
        toc = ('<nav class="cs-toc" aria-label="Case study navigation">'
               f'{home}<ul>{items}</ul></nav>')
    layout = (f'<div class="cs-layout">{toc}'
              f'<div class="cs-main">{"".join(main_parts)}</div></div>')
    content_html = ("".join(banner_parts) + "".join(hero_parts)
                    + layout + _cs_closing(data, prefix))
    toc = CS_TOC_JS if nav_items else ""
    nav = build_nav(prefix)
    footer = build_footer(prefix)
    head = shell[shell.find("<html"):shell.find("</head>")]
    cs_css = f'<link rel="stylesheet" href="{prefix}assets/case-study.css">'
    if data.get("gated"):
        # Encrypt the whole content region; ship only ciphertext. The image
        # URLs live inside the ciphertext too, so they are not discoverable.
        pw = CS_GATE_PW
        if not pw:
            print(f"  CS WARN: '{data.get('slug')}' is gated but CS_GATE_PW is unset; "
                  "shipping locked, UNREADABLE content. Set CS_GATE_PW to make it viewable.")
            pw = base64.b64encode(os.urandom(24)).decode()  # throwaway: never plaintext, undecryptable
        blob = json.dumps(_cs_encrypt(content_html, pw)).replace("</", "<\\/")
        body = (f'{nav}{_cs_gate(data)}<main class="cs" id="pm-cs-doc"></main>'
                f'<script type="application/json" id="pm-cs-blob">{blob}</script>'
                f'{footer}{toc}{CS_REVEAL_JS}{CS_REEL_JS}{CS_MEDIA_JS}{CS_GATE_JS}')
    else:
        call = ("<script>window.pmCsToc&&pmCsToc();window.pmCsReveal&&pmCsReveal();"
                "window.pmCsReel&&pmCsReel();window.pmCsMedia&&pmCsMedia();</script>")
        body = (f'{nav}<main class="cs">{content_html}</main>{footer}'
                f'{toc}{CS_REVEAL_JS}{CS_REEL_JS}{CS_MEDIA_JS}{call}')
    return ("<!DOCTYPE html>" + head + cs_css + "</head><body>"
            + body + "</body></html>")


def build_hero(prefix):
    about = prefix + "#about-me"
    work = prefix + "projects/"
    return (
        '<section class="pm-hero" id="hero">'
          '<div class="pm-hero-content">'
            '<h1 class="pm-hero-title">Your product is fine.<br>Your UX isn’t. '
            '<br class="pm-hero-mbreak"><span class="pm-hero-accent">I Fix That.</span></h1>'
            '<p class="pm-hero-sub">I’m Purvang. I shape products from first idea to final interaction.</p>'
            '<div class="pm-hero-cta">'
              f'<a class="ds-btn ds-btn--secondary" href="{about}">More about me</a>'
              f'<a class="ds-btn ds-btn--primary" href="{work}">View work'
              '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" '
              'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
              '<path d="M12 5v14M5 12l7 7 7-7"/></svg></a>'
            '</div>'
          '</div>'
        '</section>'
    )

META = {
    "index": {
        "title": "Purvang Mehta - Product Designer",
        "description": "Portfolio of Purvang Mehta, a product designer creating UX, product strategy, and interface systems for SaaS, healthcare, fintech, and creator platforms.",
    },
    "projects": {
        "title": "Projects - Purvang Mehta",
        "description": "Selected product design case studies by Purvang Mehta across healthcare, fintech, B2B SaaS, AI, construction, and media platforms.",
    },
    "healthcare": {
        "title": "Healthcare Platform Case Study - Purvang Mehta",
        "description": "A product design case study for a virtual musculoskeletal healthcare platform, focused on onboarding, clinical trust, and member engagement.",
    },
    "turfly": {
        "title": "Turfly Case Study - Purvang Mehta",
        "description": "Brand identity, design system, and admin dashboard design for Turfly, a voucher-based payment platform for the golf industry.",
    },
    "communication-saas": {
        "title": "Communication SaaS Case Study - Purvang Mehta",
        "description": "UX and product design for a B2B communication SaaS platform that helps organizations deliver personalized audio episodes.",
    },
    "nda": {
        "title": "NDA Projects - Purvang Mehta",
        "description": "A private project overview for product design work that cannot be shared publicly because of NDA restrictions.",
    },
    "terms": {
        "title": "Terms - Purvang Mehta",
        "description": "Terms and conditions for using Purvang Mehta's portfolio website.",
    },
    "privacy-policy": {
        "title": "Privacy Policy - Purvang Mehta",
        "description": "Privacy policy for Purvang Mehta's portfolio website.",
    },
    "404": {
        "title": "Page Not Found - Purvang Mehta",
        "description": "The requested page could not be found on Purvang Mehta's portfolio website.",
    },
}

IMAGE_ALTS = {
    # Homepage/project cards
    "folDL4NbZNbF2Dn9sLvXnypw": "Healthcare platform mobile and web app case study preview",
    "iHchcT84XQu4bwD9AuOiNIK8g": "Turfly voucher payment platform dashboard case study preview",
    "QilWc8w98IbOCWPCc8ixKkOZ9Vc": "US communication SaaS product design case study preview",
    "usr4OdpdrB7ur79BjOTODkWvJh0": "AI self-discovery platform case study preview",
    "jrO1z4D5TLzwUpAUPCLYgrS5PhA": "Construction quality SaaS case study preview",
    "BDpATK7dNSFgeV5EJaegq8Ot8": "US-based news and media platform case study preview",
    "47bbnnowXS5iCJeTkpODuAkxuY": "Purvang Mehta portrait",
    "SRKbDdKGOtLyOt1LfS4UAYN7ZEk": "Purvang Mehta working portrait",
    "EWPNgrvXM9KPilrp5gUZHOvH7g8": "Purvang Mehta profile portrait",
    "7fplUzhUftZmT4FytxscMUyFM": "Client testimonial portrait",
    "48MxYIJ3eRarVnSkzSgwPp02bCA": "Client testimonial portrait",
    # Client logos / small decorative marks
    "uqBkjQAQVZ6FQAGc94xcLZ0NKs": "WilyFox logo",
    "xFJuVZTZCWzqsLxOGyzoypBcwZs": "Josh Talks logo",
    "4HIqxJjznyKT7GW1sYt3VI23bcQ": "PFC Club logo",
    "Fp8qUkVhICa26PEhY5ELOptBPVI": "Partner company logo",
    "1AijdZwonEPf8NVUMMQ6nlw96E": "Partner company logo",
    # Healthcare case study
    "Yj5mfV28hErZstFVWQjpYGK9Q": "Healthcare onboarding interface showing a personalized care plan",
    "pHdYev1n0UtfVOLnBI3zXscPpI": "SimpleTherapy care pack unlock concept with recovery equipment",
    "IP3wBueoVTleVDv3wQfIjureJw": "Healthcare app onboarding reward screen",
    "2tH1wUgScWjlAM6ij6uYMKpkX8c": "Healthcare instruction screen with confirmation checkbox",
    "yKmvVJUCNaSx477CGrOF5jpKCF8": "Sara healthcare companion concept screen",
    "YrkZuzbYYNLEr0TlPjimNReMLQE": "Healthcare companion-led care plan introduction",
    "FkrqPCcnW0PBwxfJRYMQgyjpqJA": "Healthcare app onboarding flow screens",
    "Mn0UfKK2rOHn9HWJVBM54rqbN0k": "Healthcare dashboard state variations",
    "uRlrNM9Z3qBvwdWg1f38lJy7aMI": "Healthcare mobile dashboard outcome screens",
    # Turfly case study
    "zCfLFZrIwmNaLtAZKFHiN9jEbYw": "Turfly admin dashboard overview",
    "Mhy8oARGd1goIepA9sqf5ZaoWWM": "Turfly brand identity and design system exploration",
    "7grfr24B041JT5B4HJtwRTZsY": "Turfly brand system application",
    "tAoFVemx76et8Eip4rvHhD5rxU": "Turfly authentication screen illustration set",
    "oJVTqNhkhnmiDan07ZKxBcy9jM": "Turfly login and password recovery screens",
    "sPuKFJw6LzRogbv5mHSDQY4Rk": "Turfly OTP verification and password setup screens",
    "yddPHywM3GXoSb7CS7kCEDrKiI": "Turfly searchable management table interface",
    "TRM9u7jrR7LY1dS00QR9JrgPV5g": "Turfly user profile and voucher history interface",
    "oPcIrCgrQG3qmoIcVCJihIpa4": "Turfly transaction management screen",
    "0ql6q3LVmXuK4wOmMMiYhDks5EA": "Turfly redeemed voucher state screen",
    "fWz5ogMiPZIUAgNsOdMhx9xhvDg": "Turfly empty state illustration screen",
    "68PQmZYafQ2Ls8P54iMzk0KzvQ": "Turfly error state illustration screen",
    "lcZvfquvtTtxK3X84upzouUNHHs": "Turfly no results state illustration screen",
    "ok1aJEHHLjOAvfLAMSbJdMeRuU": "Turfly edge state screen set",
    # Communication SaaS / NDA
    "cprQYGWI2w0ct2oNQElOGVMfJus": "Communication SaaS product interface overview",
    "3Dajn6ESNqYTSiL8X6Icv1oDk1o": "Communication SaaS listener experience screens",
    "MpQe5qEQcxKohvR3HqPeuP2m1A": "Communication SaaS admin workflow screens",
    "Yncc4yDXL3FXdxDjPFFwsSOAnlw": "Communication SaaS handoff and component specification screens",
    "a6BfZqzgqHd6aPjn2Q8sDUpZ0": "Private NDA project preview",
    "6Pg7fbhqux70xMtctNjAPrXByo": "",
}

ASSET_RE = re.compile(
    r'https://(?:framerusercontent\.com/(?:images|assets|modules|third-party-assets)/|fonts\.gstatic\.com/s/)[^\s"\'()<>\\]+'
)

url_map = {}  # remote url -> local path relative to site root


def local_name(url):
    p = urllib.parse.urlparse(url)
    base = os.path.basename(p.path)
    stem, ext = os.path.splitext(base)
    if p.query:  # srcset scale variants get unique names
        stem += "-" + hashlib.md5(p.query.encode()).hexdigest()[:8]
    if ext.lower() in (".woff", ".woff2", ".ttf", ".otf", ".eot"):
        sub = "fonts"
    elif ext.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif"):
        sub = "images"
    else:
        sub = "misc"
    return f"assets/{sub}/{stem}{ext}"

def collect(html):
    for url in ASSET_RE.findall(html):
        url = url.rstrip(",;")
        # html-unescape &amp;
        clean = url.replace("&amp;", "&")
        if clean not in url_map:
            url_map[clean] = local_name(clean)

def canonical_url(name):
    slug = PAGES[name]
    return SITE_URL + ("/" if not slug else f"/{slug}/")

def remove_balanced_block(html, start, tag_name):
    depth = 0
    tag_re = re.compile(rf'</?{tag_name}\b[^>]*>', re.I)
    for m in tag_re.finditer(html, start):
        if m.group(0).startswith("</"):
            depth -= 1
        else:
            depth += 1
        if depth == 0:
            return html[:start] + html[m.end():]
    return html

def remove_named_blocks(html, tag_name, data_name):
    pattern = re.compile(rf'<{tag_name}\b(?=[^>]*data-framer-name="{re.escape(data_name)}")[^>]*>', re.I)
    pos = 0
    while True:
        m = pattern.search(html, pos)
        if not m:
            return html
        html = remove_balanced_block(html, m.start(), tag_name)
        pos = m.start()

def remove_services(html, remove_section=False):
    html = remove_named_blocks(html, "div", "Services - 0.1 delay")
    if remove_section:
        section_re = re.compile(r'<section\b(?=[^>]*\bid="services")[^>]*>', re.I)
        pos = 0
        while True:
            m = section_re.search(html, pos)
            if not m:
                break
            html = remove_balanced_block(html, m.start(), "section")
            pos = m.start()
    html = re.sub(
        r'<div\b(?=[^>]*class="[^"]*framer-1rykvad[^"]*")[^>]*>\s*<p\b[^>]*>\s*<!--\$-->\s*<a\b[^>]*href="[^"]*#services"[^>]*>Services</a>\s*<!--/\$-->\s*</p>\s*</div>',
        "",
        html,
        flags=re.I | re.S,
    )
    return html

def image_alt_for(tag):
    src_bits = " ".join(re.findall(r'(?:src|srcset)="([^"]*)"', tag))
    for key, alt in IMAGE_ALTS.items():
        if key in src_bits:
            return alt
    return None

def set_img_alt(tag, alt):
    alt_attr = f'alt="{alt}"'
    if re.search(r'\salt\s*=', tag):
        return re.sub(r'\salt\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^ >]*)', " " + alt_attr, tag, count=1)
    if re.search(r'\salt(?=[\s>])', tag):
        return re.sub(r'\salt(?=[\s>])', " " + alt_attr, tag, count=1)
    return re.sub(r'\s*/?>$', lambda m: " " + alt_attr + m.group(0), tag, count=1)

def fix_image_alts(html):
    def repl(m):
        tag = m.group(0)
        alt = image_alt_for(tag)
        if alt is None:
            # Unknown Framer-exported images are treated as decorative instead
            # of being exposed to screen readers as anonymous filenames.
            alt = ""
        return set_img_alt(tag, alt)
    return re.sub(r'<img\b[^>]*>', repl, html)

def normalize_headings(html):
    h1_count = 0
    stack = []
    def repl(m):
        nonlocal h1_count
        close, attrs = m.group(1), m.group(2)
        if close:
            return stack.pop() if stack else "</h2>"
        h1_count += 1
        out = "<h1" + attrs + ">" if h1_count == 1 else "<h2" + attrs + ">"
        stack.append("</h1>" if h1_count == 1 else "</h2>")
        return out
    return re.sub(r'<(/?)h1\b([^>]*)>', repl, html, flags=re.I)

def apply_seo(html, name):
    meta = META[name]
    url = canonical_url(name)
    html = re.sub(r'<title>.*?</title>', f'<title>{meta["title"]}</title>', html, count=1, flags=re.S)
    html = re.sub(r'<meta[^>]+name="description"[^>]*>', "", html, flags=re.I)
    html = re.sub(r'<meta[^>]+property="og:(?:title|description|url|type)"[^>]*>', "", html, flags=re.I)
    html = re.sub(r'<meta[^>]+name="twitter:(?:card|title|description)"[^>]*>', "", html, flags=re.I)
    html = re.sub(r'<link rel="canonical" href="[^"]*"\s*/?>', "", html, flags=re.I)
    block = (
        f'<meta name="description" content="{meta["description"]}">\n'
        f'<link rel="canonical" href="{url}">\n'
        f'<meta property="og:type" content="website">\n'
        f'<meta property="og:title" content="{meta["title"]}">\n'
        f'<meta property="og:description" content="{meta["description"]}">\n'
        f'<meta property="og:url" content="{url}">\n'
        f'<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{meta["title"]}">\n'
        f'<meta name="twitter:description" content="{meta["description"]}">'
    )
    return html.replace("</head>", block + "\n</head>", 1)

def download(url, rel):
    dest = OUT / rel
    if dest.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
            f.write(r.read())
        return None
    except Exception as e:
        return f"{url}: {e}"

def process(name, html):
    depth = 0 if name == "index" else 1
    prefix = "../" * depth

    # ---- strip external Framer/tracking scripts (keep GA loader) ----
    html = re.sub(r'<script[^>]*src="https://events\.framer\.com[^"]*"[^>]*>\s*</script>', "", html)
    html = re.sub(r'<script[^>]*src="https://framerusercontent\.com[^"]*"[^>]*>\s*</script>', "", html)
    # modulepreload + framer preconnects + lenis css
    html = re.sub(r'<link[^>]*rel="modulepreload"[^>]*>', "", html)
    html = re.sub(r'<link[^>]*href="https://unpkg\.com[^"]*"[^>]*>', "", html)
    html = re.sub(r'<link[^>]*href="https://events\.framer\.com[^"]*"[^>]*>', "", html)
    html = re.sub(r'<link[^>]*rel="preconnect"[^>]*href="https://fonts\.gstatic\.com"[^>]*>', "", html)
    html = re.sub(r'<link[^>]*href="https://fonts\.gstatic\.com"[^>]*>', "", html)

    # ---- drop Framer-runtime inline scripts, keep GA / animator / user scripts ----
    def keep_script(m):
        body = m.group(1)
        if "gtag(" in body:                       return m.group(0)   # Google Analytics
        if "var animator=" in body:               return m.group(0)   # appear-effects engine
        if "__framer_disable_appear_effects" in body: return m.group(0)  # appear bootstrap
        if re.match(r'\s*\{"', body) and '"initial"' in body:  return m.group(0)  # animation data
        if re.match(r'\s*\[\{"hash"', body):      return m.group(0)   # breakpoint map (animator uses it)
        if "data-tags" in body:                   return m.group(0)   # user's custom script
        return ""                                                      # everything else: Framer runtime
    html = re.sub(r'<script(?![^>]*src=)[^>]*>(.*?)</script>', keep_script, html, flags=re.S)

    # ---- force scroll-reveal initial states to final (runtime that animated them is gone) ----
    def fix_style(m):
        st = m.group(1)
        if re.search(r'opacity:\s*0(\.001)?(;|$)', st):
            st = re.sub(r'opacity:\s*0(\.001)?(?=;|$)', 'opacity:1', st)
            st = re.sub(r'(-webkit-)?filter:blur\([^)]*\)', r'\1filter:none', st)
            st = re.sub(r'transform:translate[XY]\([^;"]*\)(?=;|$)', 'transform:none', st)
        return f'style="{st}"'
    html = re.sub(r'style="([^"]*)"', fix_style, html)

    # ---- remove Framer meta/editor traces ----
    html = re.sub(r'<meta[^>]*name="generator"[^>]*>', "", html)
    html = re.sub(r'<meta[^>]*name="framer-search-index[^"]*"[^>]*>', "", html)
    html = re.sub(r'\s*data-framer-ssr-released-at="[^"]*"', "", html)

    # ---- rewrite asset urls to local (handles &amp; in srcset) ----
    for remote, rel in sorted(url_map.items(), key=lambda kv: -len(kv[0])):
        esc = remote.replace("&", "&amp;")
        html = html.replace(esc, prefix + rel)
        html = html.replace(remote, prefix + rel)

    # ---- internal links: absolute -> relative directory urls ----
    def fix_link(m):
        target = m.group(1).strip("/")
        if target == "" :
            return f'href="{prefix if depth else "./"}"' if depth else 'href="./"'
        return f'href="{prefix}{target}/"'
    html = re.sub(r'href="https://www\.thepurvangmehta\.com/?([^"#]*)"', fix_link, html)

    # relative links: "./slug" resolved against flat Framer urls; our pages live in dirs
    def fix_rel(m):
        target, frag = m.group(1), m.group(2) or ""
        if target == "":
            base = prefix if depth else "./"
        elif target in PAGES.values():
            base = f"{prefix}{target}/"
        else:
            return m.group(0)
        return f'href="{base}{frag}"'
    html = re.sub(r'href="\./([a-z0-9-]*)(#[^"]*)?"', fix_rel, html)

    # ---- content fixes ----
    # typo: "workd" -> "worked" (homepage hero, high-visibility)
    html = html.replace("Companies I&#x27;ve workd with", "Companies I&#x27;ve worked with")
    html = html.replace("Companies I've workd with", "Companies I've worked with")
    # project cards / internal links: open in the SAME tab (was target=_blank,
    # which spawned a new tab per case study and broke the back button)
    for slug in ("healthcare", "turfly", "communication-saas", "projects", "nda"):
        html = html.replace(f'href="{prefix}{slug}/" target="_blank"', f'href="{prefix}{slug}/"')
        html = html.replace(f'href="{slug}/" target="_blank"', f'href="{slug}/"')
    # hero subhead copy (both breakpoint variants carry the same string)
    html = html.replace(
        "I break down flows, structure, and user decisions before touching visuals, so the final design isn’t just clean, it works.",
        "Hi, I’m Purvang, A Product Designer who designs how products feel and builds how they work, end to end.")
    # Ranveer testimonial: drop the paragraph break, quote reads as two lines
    html = html.replace(
        'Loving your work!<br class="framer-text"><br class="framer-text">Just Keep going.',
        'Loving your work! Just Keep going.')
    html = html.replace("mailto:joseph@launchnow.design", f"mailto:{CONTACT_EMAIL}")
    html = html.replace("joseph@launchnow.design", CONTACT_EMAIL)
    html = html.replace(">1M+ Users Reached<", "")
    html = remove_services(html, remove_section=(name == "index"))
    if name != "index":
        html = re.sub(r'(<section\b[^>]*\bid=")services(")', r'\1case-study\2', html, flags=re.I)
    html = fix_image_alts(html)
    html = normalize_headings(html)

    # ---- design system: single source of truth for tokens (see site/assets/design-system.css) ----
    html = html.replace("</head>", f'<link rel="stylesheet" href="{prefix}assets/design-system.css"></head>')

    # ---- case-study pages: a "back to work" link above the title ----
    if name in ("healthcare", "turfly", "communication-saas"):
        back_js = ("""<script>document.addEventListener('DOMContentLoaded',function(){
  var h1=document.querySelector('h1');if(!h1||document.querySelector('.pm-back'))return;
  var a=document.createElement('a');a.className='pm-back';a.href='__BACK__';
  a.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>Back to work';
  h1.parentNode.insertBefore(a,h1);
});</script>""").replace("__BACK__", f"{prefix}projects/")
        html = html.replace("</body>", back_js + "</body>")

    # ---- runtime-lite: static/vanilla replacements for removed Framer runtime behaviors ----
    runtime_lite = """<style>
/* cursor-follow "View Project" pill on project cards: was runtime-positioned */
[data-framer-name="View Project"]{display:none!important}
/* tech-stack tooltips: hidden, reveal on hover above the logo */
[data-framer-name="Tech Stack Logo"]{position:relative}
[data-framer-name="Tooltip"]{position:absolute!important;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%)!important;opacity:0!important;pointer-events:none;transition:opacity .15s;white-space:nowrap;z-index:20}
[data-framer-name="Tech Stack Logo"]:hover [data-framer-name="Tooltip"]{opacity:1!important}
/* mobile: active-year label needs clearance above "My work history" */
@media (max-width:767.98px){[data-framer-name="Timeline"]{margin-bottom:26px!important}}
/* sliders (framer carousels): scroll-snap instead of runtime dragging */
.pm-slider{overflow-x:auto!important;scroll-snap-type:x mandatory;scrollbar-width:none}
.pm-slider::-webkit-scrollbar{display:none}
.pm-slider>li{scroll-snap-align:center}
body{overflow-x:clip}
/* a11y: give small icon/dot controls a comfortable 44x44 tap area
   (glyph stays visually centered; WCAG 2.5.5). Text links untouched. */
a[aria-label$="Link" i]{min-width:44px;min-height:44px;
  display:inline-flex!important;align-items:center;justify-content:center}
/* footer text links (Work, Terms, Privacy, email, Book Now): 44px hit area,
   padding+negative-margin pair so the visual layout doesn't shift */
footer a:not([aria-label]){display:inline-flex!important;align-items:center;
  min-height:44px;padding:10px 8px;margin:-10px -8px}
/* X chip: icon only, hide the follower count */
a[aria-label="X / Twitter Link"] p{display:none!important}
</style>
<script>(function(){
document.addEventListener('DOMContentLoaded',function(){
  /* Work opens projects at the top */
  document.querySelectorAll('a[href*="#lprojects"]').forEach(function(a){
    a.setAttribute('href',a.getAttribute('href').replace(/#lprojects$/,'')||'./')});
  /* anchor links: same-page -> smooth scroll (no navigation, no splash);
     cross-page internal -> flag the next load to skip the splash */
  document.addEventListener('click',function(e){
    var a=e.target.closest?e.target.closest('a[href]'):null;
    if(!a||a.origin!==location.origin||!a.hash)return;
    var norm=function(p){return p.replace(/index\\.html$/,'')};
    if(norm(a.pathname)===norm(location.pathname)){
      var t=document.querySelector(a.hash);
      if(t&&t.getBoundingClientRect().height>0){
        e.preventDefault();
        t.scrollIntoView({behavior:'smooth'});
        history.pushState(null,'',a.hash);
      }
    }else{
      try{sessionStorage.setItem('pm-skip-splash','1')}catch(x){}
    }
  });
  /* Contact -> the footer contact zone (email OR book a call), so the
     visitor chooses their commitment level instead of being dropped
     straight into a booking calendar. Falls back to cal.com if no footer. */
  /* target the whole footer (its top is the "Lets ... together" heading) so
     Contact lands on the section heading with nav clearance, not mid-footer */
  var contactZone=[].find.call(document.querySelectorAll('footer'),function(f){return f.getBoundingClientRect().height>50;})||
                  document.querySelector('[data-framer-name="Email / Book Call"]')||
                  document.querySelector('footer');
  if(contactZone&&!contactZone.id)contactZone.id='contact';
  document.querySelectorAll('button[aria-label="Contact Form"]').forEach(function(b){
    b.addEventListener('click',function(){
      if(contactZone)contactZone.scrollIntoView({behavior:'smooth',block:'center'});
      else window.open('https://cal.com/thepurvangmehta','_blank');
    });
  });
  /* strip leftover scroll-reveal blurs (never animate without runtime) */
  document.querySelectorAll('[style*="blur("]').forEach(function(el){
    var m=(el.getAttribute('style')||'').match(/(?:^|;)\\s*filter:\\s*blur\\(([\\d.]+)px\\)/);
    if(m&&parseFloat(m[1])<30){el.style.removeProperty('filter');el.style.removeProperty('-webkit-filter');}
  });
  /* footer word cycler */
  document.querySelectorAll('[data-framer-name="Text Cycle"]').forEach(function(tc){
    var inner=tc.querySelector('[data-framer-name]:not([data-framer-name="Text Cycle"])')||tc.firstElementChild;
    if(!inner)return;
    var kids=[].slice.call(inner.children).filter(function(k){return k.textContent.trim()});
    if(kids.length<2)return;
    inner.classList.add('pm-cycle');
    kids.forEach(function(k,i){k.style.animationDelay=(-9+i*3)+'s'});
  });
  /* other framer sliders -> scroll-snap tracks */
  document.querySelectorAll('ul[role="group"]').forEach(function(ul){
    if(ul.closest('[data-framer-name="Ticker"]'))return;
    var lis=[].slice.call(ul.children);
    if(lis.length<2)return;
    var a=lis[0].getBoundingClientRect(),b=lis[1].getBoundingClientRect();
    var overlap=Math.min(a.right,b.right)-Math.max(a.left,b.left)>10&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>10;
    var parent=ul.parentElement;
    if(overlap||ul.scrollWidth>parent.clientWidth+10){
      (overlap?ul:parent).classList.add('pm-slider');
      if(overlap){ul.style.gap='16px';lis.forEach(function(li){li.style.position='relative';li.style.transform='none'})}
    }
  });
  /* collapsed accordion cards (services on mobile): give them their natural height */
  document.querySelectorAll('[data-framer-name^="Variant"]').forEach(function(el){
    if(el.getBoundingClientRect().width<5)return;
    if(el.scrollHeight>el.clientHeight+10){
      el.style.height='auto';
      if(el.parentElement.clientHeight<5)el.parentElement.style.height='auto';
    }
  });
  /* project cards: clickable corner chip (Phosphor arrow-up-right) */
  var ARROW='M200 64v104a8 8 0 0 1-16 0V83.31L69.66 197.66a8 8 0 0 1-11.32-11.32L172.69 72H88a8 8 0 0 1 0-16h104a8 8 0 0 1 8 8Z';
  document.querySelectorAll('[data-framer-name="Image Container"]').forEach(function(box){
    var a=box.querySelector('a'); if(!a||box.querySelector('.pm-chip'))return;
    var s=document.createElementNS('http://www.w3.org/2000/svg','svg');
    s.setAttribute('viewBox','0 0 256 256');
    s.innerHTML='<path d="'+ARROW+'" fill="currentColor"/>';
    var chip=document.createElement('a');
    chip.className='pm-chip';chip.href=a.href;
    if(a.target)chip.target=a.target;
    chip.setAttribute('aria-label','Open project');
    chip.appendChild(s);
    box.appendChild(chip);
  });
  /* testimonial band: shrink slack wrappers to content, equalize card heights */
  document.querySelectorAll('section[data-framer-name="Big Quote Testimonial"]').forEach(function(sec){
    var divs=[].slice.call(sec.querySelectorAll('div')).reverse();
    divs.forEach(function(el){
      if(!el.children.length)return;
      var r=el.getBoundingClientRect(); if(r.height<320)return;
      var m=0;[].forEach.call(el.children,function(c){var cr=c.getBoundingClientRect();if(cr.height>0)m=Math.max(m,cr.bottom);});
      if(m&&r.bottom-m>60)el.style.setProperty('height',Math.ceil(m-r.top)+'px','important');
    });
    var cards=[].slice.call(sec.querySelectorAll('[data-framer-name^="Big Quote"]')).filter(function(c){return c.getBoundingClientRect().height>50});
    var mx=0;cards.forEach(function(c){mx=Math.max(mx,c.getBoundingClientRect().height)});
    cards.forEach(function(c){c.style.setProperty('min-height',Math.ceil(mx)+'px','important')});
  });
  /* social icons: glyphs were injected by the framer runtime */
  var IC={
    twitter:'M18.9 1.15h3.68l-8.04 9.19L24 22.85h-7.4l-5.8-7.59-6.64 7.59H.47l8.6-9.83L0 1.15h7.6l5.24 6.93 6.06-6.93Zm-1.29 19.5h2.04L6.49 3.24H4.3l13.31 17.4Z',
    threads:'M12.19 24h-.01c-3.58-.02-6.33-1.2-8.18-3.51C2.35 18.44 1.5 15.59 1.47 12.01v-.02c.03-3.58.88-6.43 2.53-8.48C5.85 1.2 8.6.02 12.18 0h.01c2.75.02 5.04.73 6.83 2.1 1.68 1.29 2.86 3.13 3.51 5.47l-2.04.57c-1.1-3.96-3.9-5.98-8.3-6.01-2.91.02-5.11.94-6.54 2.72C4.31 6.5 3.62 8.91 3.59 12c.03 3.09.72 5.5 2.06 7.16 1.43 1.78 3.63 2.7 6.54 2.72 2.62-.02 4.36-.63 5.8-2.05 1.65-1.61 1.62-3.59 1.09-4.8-.31-.71-.87-1.3-1.63-1.75-.19 1.35-.62 2.45-1.28 3.27-.89 1.1-2.14 1.7-3.73 1.79-1.2.07-2.36-.22-3.26-.8-1.06-.69-1.69-1.74-1.75-2.96-.07-1.19.41-2.29 1.33-3.08.88-.76 2.12-1.21 3.58-1.29a13.85 13.85 0 0 1 3.02.14c-.13-.74-.38-1.33-.75-1.76-.51-.59-1.31-.88-2.36-.89h-.03c-.84 0-1.99.23-2.72 1.32L7.73 7.85c.98-1.45 2.57-2.26 4.48-2.26h.04c3.19.02 5.1 1.98 5.29 5.39l.32.14c1.49.7 2.58 1.76 3.15 3.07.8 1.82.87 4.79-1.55 7.16C17.62 23.16 15.37 23.98 12.19 24Zm1-11.69c-.24 0-.49.01-.74.02-1.84.1-2.98.95-2.92 2.14.07 1.26 1.45 1.84 2.78 1.77 1.22-.07 2.82-.54 3.09-3.71a10.5 10.5 0 0 0-2.21-.22Z',
    linkedin:'M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28ZM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13Zm1.78 13.02H3.56V9h3.56v11.45ZM22.23 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.23 0Z',
    dribbble:'M12 24C5.39 24 0 18.62 0 12S5.39 0 12 0s12 5.39 12 12-5.39 12-12 12Zm10.12-10.36c-.35-.11-3.17-.95-6.38-.44 1.34 3.68 1.89 6.68 1.99 7.31 2.3-1.56 3.94-4.02 4.39-6.87Zm-6.11 7.81c-.15-.9-.75-4.03-2.19-7.77l-.07.02c-5.79 2.02-7.86 6.03-8.04 6.4a10.2 10.2 0 0 0 6.29 2.17c1.42 0 2.77-.29 4.01-.82Zm-11.62-2.58c.23-.4 3.04-5.06 8.33-6.77l.4-.12c-.26-.59-.54-1.17-.83-1.74C7.17 11.78 2.21 11.71 1.76 11.7v.31c0 2.63 1 5.04 2.63 6.86Zm-2.42-8.96c.46.01 4.68.03 9.48-1.25a65.8 65.8 0 0 0-3.8-5.93 10.23 10.23 0 0 0-5.68 7.18ZM9.6 2.05c.28.38 2.15 2.91 3.82 6 3.65-1.37 5.19-3.44 5.37-3.7A10.15 10.15 0 0 0 12 1.76c-.83 0-1.63.1-2.4.29Zm10.34 3.49c-.22.29-1.94 2.49-5.72 4.04.24.49.47.98.68 1.48.08.18.15.36.22.53 3.41-.43 6.8.26 7.14.33a10.2 10.2 0 0 0-2.32-6.38Z',
    behance:'M22 7h-7V5h7v2Zm1.73 10c-.44 1.3-2.03 3-5.1 3-3.07 0-5.56-1.73-5.56-5.68 0-3.91 2.32-5.92 5.47-5.92 3.08 0 4.96 1.78 5.37 4.43.08.5.11 1.19.1 2.14H15.97c.13 3.21 3.48 3.31 4.59 2.03h3.17Zm-7.69-4h4.97c-.11-1.55-1.14-2.22-2.48-2.22-1.47 0-2.28.77-2.49 2.22Zm-9.57 6.99H0V5.02h6.95c5.48.08 5.58 5.44 2.72 6.9 3.46 1.26 3.58 8.07-3.2 8.07ZM3 11h3.58c2.51 0 2.91-3-.31-3H3v3Zm3.39 3H3v3.02h3.34c3.06 0 2.87-3.02.05-3.02Z',
    instagram:'M12 2.16c3.2 0 3.58.01 4.85.07 3.25.15 4.77 1.69 4.92 4.92.06 1.27.07 1.65.07 4.85s-.01 3.58-.07 4.85c-.15 3.23-1.66 4.77-4.92 4.92-1.27.06-1.64.07-4.85.07-3.2 0-3.58-.01-4.85-.07-3.26-.15-4.77-1.7-4.92-4.92-.06-1.27-.07-1.64-.07-4.85s.01-3.58.07-4.85C2.38 3.92 3.9 2.38 7.15 2.23 8.42 2.18 8.8 2.16 12 2.16ZM12 0C8.74 0 8.33.01 7.05.07 2.7.27.27 2.69.07 7.05.01 8.33 0 8.74 0 12s.01 3.67.07 4.95c.2 4.36 2.62 6.78 6.98 6.98 1.28.06 1.69.07 4.95.07s3.67-.01 4.95-.07c4.35-.2 6.78-2.62 6.98-6.98.06-1.28.07-1.69.07-4.95s-.01-3.67-.07-4.95C23.73 2.7 21.31.27 16.95.07 15.67.01 15.26 0 12 0Zm0 5.84A6.16 6.16 0 1 0 18.16 12 6.16 6.16 0 0 0 12 5.84Zm0 10.15A4 4 0 1 1 16 12a4 4 0 0 1-4 4Zm6.41-11.85a1.44 1.44 0 1 0 1.44 1.44 1.44 1.44 0 0 0-1.44-1.44Z'
  };
  document.querySelectorAll('a[aria-label]').forEach(function(a){
    var l=a.getAttribute('aria-label').toLowerCase(),key=null;
    Object.keys(IC).forEach(function(k){if(l.indexOf(k)>-1)key=k});
    if(!key)return;
    var svg=a.querySelector('svg');
    var mk='<path d="'+IC[key]+'" fill="currentColor"/>';
    if(svg&&svg.querySelector('use')){
      svg.removeAttribute('class');svg.setAttribute('viewBox','0 0 24 24');
      svg.style.cssText='width:22px;height:22px;display:block';svg.innerHTML=mk;
    }else if(!svg){
      var host=a.querySelector('div[style*="display:contents"]')||a.firstElementChild||a;
      var s=document.createElementNS('http://www.w3.org/2000/svg','svg');
      s.setAttribute('viewBox','0 0 24 24');s.style.cssText='width:22px;height:22px;display:block';
      s.innerHTML=mk;
      if(host.style&&host.style.display==='contents')host.style.display='block';
      host.appendChild(s);
    }
  });
});
})();</script>"""
    html = html.replace("</body>", runtime_lite.replace("__HOME__", prefix if depth else "./") + "</body>")

    # ---- non-home pages: drop any Framer Client Logos strip outright ----
    if name != "index":
        html = remove_named_blocks(html, "div", "Client Logos")

    # ---- hero entrance choreography (home only): splash -> headline zoom-settle -> staged reveals ----
    if name == "index":
        hero_anim = """<style>
@keyframes pm-hero-zoom{from{opacity:.001;transform:translateY(100px) scale(2)}to{opacity:1;transform:none}}
@keyframes pm-hero-fade{from{opacity:.001}to{opacity:1}}
/* splash: flat ink cover (no gradients, system surfaces only); exit is a
   mild shutter: the cover splits into top/bottom panels that slide apart */
#pm-splash{position:fixed;inset:0;z-index:99999;background:transparent;display:flex;align-items:center;justify-content:center;overflow:hidden;animation:pm-splash-clear .1s linear 1.95s both}
#pm-splash::before,#pm-splash::after{content:"";position:absolute;left:0;width:100%;height:50.2%;background:var(--ds-ink)}
#pm-splash::before{top:0;animation:pm-shutter-top .6s cubic-bezier(.83,0,.17,1) 1.35s both}
#pm-splash::after{bottom:0;animation:pm-shutter-bot .6s cubic-bezier(.83,0,.17,1) 1.35s both}
#pm-splash svg{width:clamp(180px,24vw,300px);height:auto;overflow:visible;position:relative;z-index:1;animation:pm-logo-reveal .8s cubic-bezier(.65,0,.13,1) .15s both,pm-logo-out .3s var(--ds-ease) 1.2s both}
#pm-splash svg path{fill:var(--ds-paper)}
#pm-splash svg path.pm-dot{fill:var(--ds-accent);transform-box:fill-box;transform-origin:center;animation:pm-dot-pop .45s cubic-bezier(.34,1.56,.64,1) .85s both}
@keyframes pm-logo-reveal{from{opacity:0;clip-path:inset(0 100% 0 0);transform:scale(1.08)}60%{opacity:1}to{opacity:1;clip-path:inset(0 -8% 0 0);transform:scale(1)}}
@keyframes pm-dot-pop{from{transform:scale(0)}to{transform:scale(1)}}
@keyframes pm-logo-out{to{opacity:0}}
@keyframes pm-shutter-top{to{transform:translateY(-101%)}}
@keyframes pm-shutter-bot{to{transform:translateY(101%)}}
@keyframes pm-splash-clear{to{visibility:hidden}}
.pm-no-splash #pm-splash{display:none}
@media (prefers-reduced-motion: reduce){#pm-splash{display:none}}
/* end-card section: off on home (kept on all other pages) */
section[data-framer-name="Schedule Call"]{display:none!important}
/* mobile: extra clearance so the hero card doesn't tuck under the nav pill */
@media (max-width:767.98px){
  section[data-framer-name="Hero"]{margin-top:132px!important}
}
</style>"""
        logo_svg = open(ROOT / "logo.svg", encoding="utf-8").read().strip()
        # the trailing period is the first subpath of the first path, split it out so it can be accent-colored
        pm = re.search(r'(<path[^>]*\bd=")(M[^"]*?Z)\s*(M[^"]*")', logo_svg)
        if pm:
            logo_svg = logo_svg.replace(pm.group(0), f'<path class="pm-dot" d="{pm.group(2)}"/>{pm.group(1)}{pm.group(3)}', 1)
        # splash plays on: reload, fresh/external entry, or logo click from
        # another page (sessionStorage flag set by the logo handler).
        # Internal link navigations (nav About from a project page,
        # back/forward) skip it via the pm-no-splash class.
        splash_gate = ("<script>(function(){try{"
                       "var e=performance.getEntriesByType('navigation')[0];"
                       "var t=e?e.type:'navigate';"
                       "var logo=sessionStorage.getItem('pm-logo-nav')==='1';"
                       "var skip=sessionStorage.getItem('pm-skip-splash')==='1';"
                       "sessionStorage.removeItem('pm-logo-nav');"
                       "sessionStorage.removeItem('pm-skip-splash');"
                       "var internal=false;"
                       "try{internal=!!document.referrer&&new URL(document.referrer).origin===location.origin}catch(x){}"
                       "if(!logo&&t!=='reload'&&(skip||internal))document.documentElement.classList.add('pm-no-splash');"
                       "}catch(x){}})()</script>")
        splash = (splash_gate + '<div id="pm-splash" aria-hidden="true">' + logo_svg +
                  '</div><script>setTimeout(function(){var s=document.getElementById(\'pm-splash\');if(s)s.remove()},2100)</script>')
        hero_extras = """<script>document.addEventListener('DOMContentLoaded',function(){
  /* hero is now hand-built (with its own CTAs); this block only handles the
     other sections below, no dependency on the Framer hero anymore. */
  /* section heading rewrites: keep an existing span's classes so the
     framer type presets (size/weight) carry over */
  function setHeading(h2,parts){
    if(!h2)return;
    var sp=h2.querySelector('span.framer-text');
    var base=sp?sp.className:'framer-text';
    h2.innerHTML=parts.map(function(p){
      return '<span class="'+base+'" style="'+(p[1]?'color:var(--ds-ink-soft);--framer-text-color:var(--ds-ink-soft)':'color:var(--ds-ink);--framer-text-color:var(--ds-ink)')+'">'+p[0]+'</span>';
    }).join(' ');
  }
  var abSec=document.querySelector('section[data-framer-name="About Me"]');
  /* "made with love" curved-text stamp: retired (all breakpoint variants) */
  if(abSec)[].forEach.call(abSec.querySelectorAll('textPath'),function(tp){
    if(/made\\s+with\\s+love/i.test(tp.textContent)){
      var box=tp.closest('[class*="-container"]')||tp.closest('svg');
      if(box)box.style.setProperty('display','none','important');
    }
  });
  if(abSec)[].forEach.call(abSec.querySelectorAll('[data-framer-name="Designing experiences that solve real problems."] h2'),function(h){
    setHeading(h,[['About',0],['Me',1]]);
  });
  var tSecH=[].find.call(document.querySelectorAll('section[data-framer-name="Big Quote Testimonial"]'),function(s){
    return /impressed/i.test(s.textContent)});
  if(tSecH)[].forEach.call(tSecH.querySelectorAll('h2'),function(h){
    if(/impressed/i.test(h.textContent))setHeading(h,[['What clients',0],['say',1]]);
  });
  /* "View all my projects" moves onto the Selected Projects heading row
     (the VISIBLE breakpoint variant's heading, so mobile gets it too) */
  var vaBox=document.querySelector('section[data-framer-name="Latest Projects"] [data-framer-name="View all projects"]');
  var lpSec=document.querySelector('section[data-framer-name="Latest Projects"]');
  var lpH2=lpSec?([].find.call(lpSec.querySelectorAll('h2'),function(h){
    return h.getBoundingClientRect().width>0})||lpSec.querySelector('h2')):null;
  if(vaBox&&lpH2){
    [].forEach.call(vaBox.querySelectorAll('p,span'),function(e){
      if(!e.children.length&&/view all/i.test(e.textContent))e.textContent='View All';
    });
    var headBlock=lpH2.parentElement;
    var row=document.createElement('div');row.className='pm-sec-head';
    headBlock.parentNode.insertBefore(row,headBlock);
    row.appendChild(headBlock);row.appendChild(vaBox);
  }
  /* visual explorations: two counter-scrolling marquee rows (was a 3d carousel) */
  var galSec=null;
  document.querySelectorAll('section').forEach(function(sec){
    if(!galSec&&/explorations/i.test(sec.textContent)&&sec.querySelector('[aria-label="Gallery image"]'))galSec=sec;
  });
  if(galSec){
    if(!galSec.id)galSec.id='explorations'; /* section map: clean anchors */
    /* hand-picked exploration images: row 1 (top) and row 2 (bottom), 5 each */
    var galRows=[
      ['assets/images/exploration-1.webp','assets/images/exploration-2.webp','assets/images/exploration-3.webp','assets/images/exploration-4.webp','assets/images/exploration-5.webp'],
      ['assets/images/exploration-6.webp','assets/images/exploration-7.webp','assets/images/exploration-8.webp','assets/images/exploration-9.webp','assets/images/exploration-10.webp']
    ];
    var headingEl=[].find.call(galSec.querySelectorAll('h2,h3,p'),function(e){return /explorations/i.test(e.textContent)});
    [].forEach.call(galSec.children,function(ch){if(!headingEl||!ch.contains(headingEl))ch.style.display='none'});
    var gal=document.createElement('div');gal.className='pm-gal';
    galRows.forEach(function(row,ri){
      var track=document.createElement('div');
      track.className='pm-gal-track'+(ri?' pm-rev':'');
      /* two identical halves so the marquee wraps seamlessly */
      for(var rep=0;rep<2;rep++)row.forEach(function(src){
        var c=document.createElement('div');c.className='pm-gal-card';
        c.style.backgroundImage='url('+src+')';
        track.appendChild(c);
      });
      gal.appendChild(track);
    });
    galSec.appendChild(gal);
  }
  /* about photo: keep only the front picture of the fan */
  var pic=document.querySelector('section[data-framer-name="About Me"] [data-framer-name="Picture / Work History"]');
  if(pic){
    /* only the active breakpoint's photos render with size */
    var vis=[].slice.call(pic.querySelectorAll('img')).filter(function(im){return im.getBoundingClientRect().width>0});
    if(vis.length>1){
      var common=null,p=vis[0];
      while(p&&p!==pic){
        var par=p.parentElement,hits=0;
        vis.forEach(function(im){if(par&&par.contains(im))hits++});
        if(par&&hits===vis.length){common=par;break}
        p=par;
      }
      if(common){
        var layers=[];
        [].forEach.call(common.children,function(ch){if(ch.querySelector('img'))layers.push(ch)});
        if(layers.length>1){
          var keep=layers[layers.length-1]; /* topmost in paint order = front of the fan */
          layers.forEach(function(l){if(l!==keep)l.style.display='none'});
          keep.style.setProperty('transform','none','important');
          keep.style.setProperty('border-radius','16px','important');
          keep.style.overflow='hidden';
          /* photo fills its (now wider) column; height follows the container
             so the CSS fold-fit clamp works */
          keep.style.setProperty('width','100%','important');
          keep.style.setProperty('height','100%','important');
          if(common!==pic)common.style.setProperty('width','100%','important');
          [].forEach.call(keep.querySelectorAll('img'),function(im){
            im.style.setProperty('width','100%','important');
            im.style.setProperty('height','100%','important');
            im.style.setProperty('object-fit','cover','important');
          });
        }
      }
    }
  }
  /* testimonials: auto-scrolling marquee, same treatment as visual explorations */
  var tSec=[].find.call(document.querySelectorAll('section[data-framer-name="Big Quote Testimonial"]'),function(s){
    return s.querySelector('[data-framer-name^="Big Quote"]')&&!/explorations/i.test(s.textContent)});
  if(tSec&&!tSec.id)tSec.id='testimonials'; /* section map: clean anchors */
  if(tSec&&!tSec.querySelector('.pm-testi')){
    /* one card per UNIQUE testimonial (keyed by name), regardless of Framer
       breakpoint variant or current visibility. A height filter dropped a
       whole testimonial on mobile (its variant had 0 height at build time). */
    var pmSeen={},tCards=[];
    [].slice.call(tSec.querySelectorAll('[data-framer-name^="Big Quote"]')).forEach(function(c){
      if(c.classList.contains('pm-testi-card'))return;
      var n=c.querySelector('[data-framer-name="Name"] p'),q=c.querySelector('[data-framer-name="Quote"] p');
      var key=n&&n.textContent.trim();
      if(!key||!q||!q.textContent.trim()||pmSeen[key])return;
      pmSeen[key]=1;tCards.push(c);
    });
    if(tCards.length){
      var tHead=[].find.call(tSec.querySelectorAll('h2'),function(){return true});
      var track=document.createElement('div');track.className='pm-gal-track';
      /* the loop translates -50%, so each half must be at least a viewport wide */
      var setW=0;tCards.forEach(function(c){setW+=((c.getBoundingClientRect().width||360)+18)});
      var perHalf=Math.max(2,Math.ceil(2600/Math.max(setW,300)));
      for(var rep=0;rep<perHalf*2;rep++)tCards.forEach(function(c){
        var cl=c.cloneNode(true);cl.classList.add('pm-testi-card');
        cl.style.minHeight='';cl.style.height='';
        track.appendChild(cl);
      });
      [].forEach.call(tSec.children,function(ch){if(!tHead||!ch.contains(tHead))ch.style.display='none'});
      var wrap2=document.createElement('div');wrap2.className='pm-gal pm-testi';wrap2.appendChild(track);
      tSec.appendChild(wrap2);
      /* equal heights: tallest card wins, everyone matches it */
      var eqCards=function(){
        var cs=track.querySelectorAll('.pm-testi-card'),mx=0;
        [].forEach.call(cs,function(c){c.style.removeProperty('height')});
        [].forEach.call(cs,function(c){mx=Math.max(mx,c.getBoundingClientRect().height)});
        [].forEach.call(cs,function(c){c.style.setProperty('height',Math.ceil(mx)+'px','important')});
      };
      eqCards();
      window.addEventListener('load',eqCards);
      window.addEventListener('resize',eqCards);
    }
  }
  /* ---- About Me: rebuilt to the muhid.de/#work layout ----
     polaroid photo + About facts + tech stack on the left;
     hook headline + intro + expandable work history on the right.
     PLACEHOLDER DATA below (facts + work list), confirm with Purvang. */
  var abSec2=document.querySelector('section[data-framer-name="About Me"]');
    /* tech stack: removed from About entirely for now */
  if(abSec2&&!abSec2.querySelector('.pm-about')){
    var ic2=abSec2.querySelector('[data-framer-name="Inside Container"]')||abSec2;
    /* keep the real photo/socials/signature: grab the visible variants before hiding */
    var abImgs=[].filter.call(ic2.querySelectorAll('[data-framer-name="Your Details"] img'),function(im){
      return im.getBoundingClientRect().width>0});
    var abSrc='assets/images/about-purvang.jpg'; /* fixed portrait, de-Framered */
    var abSoc=[].find.call(ic2.querySelectorAll('[data-framer-name="Your Details"]>div'),function(d){
      return d.querySelector('a[aria-label$="Link"]')&&d.getBoundingClientRect().width>0});
    var abSig=[].find.call(ic2.querySelectorAll('div[style*="data:image/svg"]'),function(d){
      var r=d.getBoundingClientRect();return r.width>0&&r.width<320&&r.height<160});
    var sigW=abSig?abSig.getBoundingClientRect():null;
    [].forEach.call(ic2.children,function(ch){ch.style.setProperty('display','none','important')});
    var FACTS=['4+ Years Experience','Remote · Open to relocate'];
    /* work history from public profiles (LinkedIn blocked), dates approximate, confirm */
    var JOBS=[
      ['Logicwind','2025 – Present','Product Designer, designing web and mobile products for global clients across SaaS and e-commerce.'],
      ['Josh Talks','2023 – 2025','Product Designer, grew from the graphics team into product, leading creative direction for the Josh Creators network.'],
      ['BeerBiceps Media','2021 – 2023','Graphic Designer & Video Editor, built an Instagram page to 120K followers; edits crossed a million cumulative views.']
    ];
    var chev='<svg viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M213.7 101.7l-80 80a8 8 0 0 1-11.4 0l-80-80A8 8 0 0 1 53.7 90.3L128 164.7l74.3-74.4a8 8 0 0 1 11.4 11.4Z"/></svg>';
    var el=document.createElement('div');el.className='pm-about';
    el.innerHTML=
      '<h2 class="pm-about-title ds-section-title">About <span>Me</span></h2>'+
      '<div class="pm-about-left">'+
        '<div class="pm-polaroid">'+(abSrc?'<img src="'+abSrc+'" alt="Purvang Mehta">':'')+'</div>'+
        '<div class="pm-about-facts">'+
          FACTS.map(function(f){return '<p>'+f+'</p>'}).join('')+'</div>'+
        '<div class="pm-about-socslot"></div>'+
      '</div>'+
      '<div class="pm-about-right">'+
        '<h3 class="pm-about-head">I didn\\u2019t start out in design.<br>I just never left once I found it.</h3>'+
        '<p class="pm-about-lede">A few years in, I\\u2019ve shipped consumer and B2B products across healthcare, SaaS, and creator platforms. I do my best work when the design problem sits inside a business problem. Right now I\\u2019m deep into AI-augmented design workflows, Claude, Figma, and vibe-coded prototypes, to move faster and test more ideas in less time.</p>'+
        '<div class="pm-about-sigslot"></div>'+
        '<ul class="pm-worklist">'+
          JOBS.map(function(j){return '<li><button type="button"><strong>'+j[0]+'</strong><span>'+j[1]+chev+'</span></button><div class="pm-workbody"><p>'+j[2]+'</p></div></li>'}).join('')+
        '</ul>'+
      '</div>';
    ic2.appendChild(el);
    if(abSoc)el.querySelector('.pm-about-socslot').appendChild(abSoc);
    if(abSig&&sigW){
      abSig.style.setProperty('width',Math.round(sigW.width)+'px','important');
      abSig.style.setProperty('height',Math.round(sigW.height)+'px','important');
      el.querySelector('.pm-about-sigslot').appendChild(abSig);
    }
    [].forEach.call(el.querySelectorAll('.pm-worklist button'),function(b){
      b.addEventListener('click',function(){b.parentElement.classList.toggle('open')});
    });
  }
  /* section order: Visual explorations moves BELOW About Me. Band colors
     follow position (bands = transparent section over the gray body vs the
     section's own white bg): About goes transparent -> gray band;
     explorations gets white -> keeps the white/gray alternation. */
  var pmExpl=document.getElementById('explorations');
  var pmAbout=document.querySelector('section[data-framer-name="About Me"]');
  if(pmExpl&&pmAbout&&pmAbout.parentElement===pmExpl.parentElement){
    pmAbout.after(pmExpl);
    pmAbout.style.setProperty('background-color','transparent','important');
    pmExpl.style.setProperty('background-color','var(--ds-paper)','important');
  }
  /* consistent two-tone section titles: first words in ink, last word in the
     same --ds-ink-soft gray across ALL section headings. Framer presets force
     the span color with !important, so our inline color needs it too. */
  function pmTwoTone(re){
    var h2=[].find.call(document.querySelectorAll('main h2, main h3'),function(h){
      return re.test((h.textContent||'').trim())&&h.getBoundingClientRect().width>0;});
    if(!h2)return;
    var txt=(h2.textContent||'').replace(/\\s+/g,' ').trim();
    if(txt.indexOf(' ')<0)return;
    var sp=h2.querySelector('span.framer-text');var cls=sp?(' class="'+sp.className+'"'):'';
    var i=txt.lastIndexOf(' ');
    var st=function(v){return ' style="color:var('+v+')!important;--framer-text-color:var('+v+')"';};
    h2.innerHTML='<span'+cls+st('--ds-ink')+'>'+txt.slice(0,i)+'</span> '+
                 '<span'+cls+st('--ds-ink-soft')+'>'+txt.slice(i+1)+'</span>';
  }
  pmTwoTone(/^Selected Projects$/i);
  pmTwoTone(/^Visual explorations$/i);
  pmTwoTone(/^What clients say$/i);
  var pmAbT=document.querySelector('.pm-about-title span');
  if(pmAbT)pmAbT.style.setProperty('color','var(--ds-ink-soft)','important');
});</script>"""
        html = html.replace("</head>", hero_anim + "<style>" + HERO_CSS + TICKER_CSS + "</style></head>")
        html = html.replace("</body>", hero_extras + "</body>")

        # ---- replace the Framer Hero section + Client Logos strip with hand-built ones ----
        html = remove_named_blocks(html, "div", "Client Logos")
        hsm = re.search(r'<section\b(?=[^>]*data-framer-name="Hero")[^>]*>', html, re.I)
        if hsm:
            depth, hend = 0, hsm.start()
            for tag in re.finditer(r'</?section\b[^>]*>', html[hsm.start():], re.I):
                depth += -1 if tag.group(0).startswith("</") else 1
                if depth == 0:
                    hend = hsm.start() + tag.end(); break
            html = html[:hsm.start()] + build_hero(prefix) + build_ticker(prefix) + html[hend:]

        # wrap the hero + ticker in a clean full-height container (static, build-time)
        hm = re.search(r'<section[^>]*class="pm-hero"', html)
        lm = re.search(r'<div[^>]*class="pm-ticker"', html)
        if hm and lm and hm.start() < lm.start():
            # find end of the Client Logos div by depth-scanning tags
            depth, pos = 0, lm.start()
            for tag in re.finditer(r'<div\b|</div>', html[lm.start():]):
                depth += 1 if tag.group(0) == '<div' else -1
                if depth == 0:
                    pos = lm.start() + tag.end()
                    break
            html = (html[:hm.start()] + '<div id="pm-hero-wrap">' +
                    html[hm.start():pos] + '</div>' + html[pos:])
        html = re.sub(r'(<body[^>]*>)', r'\1' + splash.replace('\\', r'\\'), html, count=1)

    # ---- re-wire the password gate (check logic lived in the removed Framer bundle) ----
    if "Enter Password" in html:
        gate_js = ("""<script>(function(){
  var h2=[].find.call(document.querySelectorAll('h2'),function(e){return e.textContent.trim()==='Enter Password'});
  if(!h2)return;
  var card=h2.parentElement,overlay=card.parentElement,root=overlay.parentElement;
  var input=card.querySelector('input'),btn=card.querySelector('button');
  /* on-system look: flat surface (no bg image/gradient), paper card, ink button */
  [root,overlay].forEach(function(el){
    if(!el)return;
    el.style.setProperty('background-image','none','important');
    el.style.setProperty('background-color','var(--ds-surface)','important');
  });
  card.style.setProperty('background-color','var(--ds-paper)','important');
  card.style.setProperty('border','1px solid var(--ds-border)','important');
  card.style.setProperty('border-radius','var(--ds-radius-xl)','important');
  card.style.setProperty('box-shadow','0 18px 40px rgba(0,0,0,.10)','important');
  card.style.textAlign='left';
  h2.style.cssText='margin:0 0 8px;color:var(--ds-ink);font-family:var(--ds-font-display);font-size:22px';
  /* NDA context above the field */
  var nda=document.createElement('p');
  nda.style.cssText='margin:0 0 20px;color:var(--ds-ink-soft);font-family:var(--ds-font-sans);font-size:15px;line-height:1.55';
  nda.innerHTML='This case study is under NDA. Enter the password to view it, or <a href="mailto:__EMAIL__?subject=Case%20study%20access%20request" style="color:var(--ds-accent);text-decoration:underline">email me for access</a>.';
  h2.parentNode.insertBefore(nda,input);
  /* mailto silently fails for visitors with no default mail app, always give
     feedback: copy the address + toast, and still try to open a mail client */
  /* native mailto still fires (opens a mail client if one exists); we layer a
     clipboard copy + toast so the click always does something visible even
     when the visitor has no default mail app configured */
  var mailLink=nda.querySelector('a');
  mailLink.addEventListener('click',function(){
    var addr='__EMAIL__';
    try{if(navigator.clipboard)navigator.clipboard.writeText(addr);}catch(_){}
    var t=document.createElement('div');
    t.textContent='\\u2713 Email copied, '+addr;
    t.style.cssText='position:fixed;left:50%;bottom:32px;transform:translateX(-50%);background:var(--ds-ink);color:var(--ds-paper);font:500 14px/1 var(--ds-font-sans);padding:13px 20px;border-radius:var(--ds-radius-pill);z-index:100000;box-shadow:0 8px 24px rgba(0,0,0,.22);opacity:1;transition:opacity .3s';
    document.body.appendChild(t);
    setTimeout(function(){t.style.opacity='0';setTimeout(function(){t.remove()},320)},2600);
  });
  input.style.setProperty('border-radius','var(--ds-radius-md)','important');
  btn.style.setProperty('border-radius','var(--ds-radius-pill)','important');
  btn.style.setProperty('background-color','var(--ds-ink)','important');
  var err=document.createElement('p');
  err.style.cssText='color:var(--ds-accent);font-family:var(--ds-font-sans);font-size:13px;margin-top:12px;display:none';
  err.textContent='Incorrect password. Please try again.';
  card.appendChild(err);
  function check(){
    if(input.value===atob('UHVyQDIwMjY=')){root.remove();document.documentElement.style.overflow='';}
    else{err.style.display='block';input.value='';input.focus();}
  }
  btn.addEventListener('click',check);
  input.addEventListener('keydown',function(e){if(e.key==='Enter')check()});
  document.documentElement.style.overflow='hidden';
})();</script>""").replace("__EMAIL__", CONTACT_EMAIL)
        html = html.replace("</body>", gate_js + "</body>")

    # social-card images must be absolute urls for scrapers
    html = re.sub(
        r'((?:property="og:image"|name="twitter:image")\s+content=")(?:\.\./)*(assets/[^"]*)',
        r'\1https://www.thepurvangmehta.com/\2', html)
    html = re.sub(
        r'(content=")(?:\.\./)*(assets/[^"]*)("\s+(?:property="og:image"|name="twitter:image"))',
        r'\1https://www.thepurvangmehta.com/\2\3', html)

    # ---- our own nav: strip the Framer nav variants, inject the hand-built one ----
    html = remove_named_blocks(html, "nav", "Nav Default")
    html = remove_named_blocks(html, "nav", "Mobile Closed")
    nav_html = build_nav(prefix)
    html = re.sub(r'(<body[^>]*>)', lambda m: m.group(1) + nav_html, html, count=1)

    # ---- our own footer: drop ALL Framer footer variants, then append our own
    #      as a direct <body> child (decoupled from Framer's breakpoint layout,
    #      which otherwise starved it to 0 width on mobile) ----
    while True:
        m2 = re.search(r'<footer\b[^>]*>', html, re.I)
        if not m2:
            break
        e2 = html.find('</footer>', m2.end())
        if e2 == -1:
            break
        html = html[:m2.start()] + html[e2+9:]
    html = html.replace("</body>", build_footer(prefix) + "</body>", 1)
    html = html.replace("</head>", "<style>" + FOOTER_CSS + "</style></head>", 1)

    return apply_seo(html, name)

# pass 1: collect assets across all pages
srcs = {}
for name in PAGES:
    srcs[name] = open(ROOT / f"src_{name}.html", encoding="utf-8").read()
    collect(srcs[name])
print(f"{len(url_map)} unique assets to download")

# download in parallel
errs = []
with concurrent.futures.ThreadPoolExecutor(16) as ex:
    for r in ex.map(lambda kv: download(*kv), url_map.items()):
        if r: errs.append(r)
print(f"downloaded, {len(errs)} errors")
for e in errs[:10]: print("  ERR", e)

# pass 2: process + write pages
for name, slug in PAGES.items():
    _cf = ROOT / "content" / f"{name}.json"
    if _cf.exists():
        # content-driven case study: reuse the processed shell's <head>, render body from data
        _shell = process(name, srcs[name])
        _data = json.load(open(_cf, encoding="utf-8"))
        out = render_case_study(_data, "../", _shell)
    else:
        out = process(name, srcs[name])
    # No em dashes anywhere on the site (Purvang's standing rule). Strip every
    # encoding (literal U+2014, JS backslash-u2014 escape, HTML entities) to a comma.
    out = re.sub(r'\s*(?:' + chr(8212) + r'|\\u2014|&mdash;|&#8212;|&#x2014;)\s*', ', ', out, flags=re.I)
    out = re.sub(r'[ \t]+(?=\n)', '', out)
    dest = OUT / ("index.html" if name == "index" else f"{slug}/index.html")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(out, encoding="utf-8")
    # verify no framer runtime remains
    leftover = re.findall(r'framerusercontent\.com|events\.framer\.com|unpkg\.com', out)
    print(f"{dest.relative_to(ROOT)}  {len(out)//1024}KB  leftover-refs={len(leftover)}")

# custom domain for GitHub Pages (published into the deploy artifact)
(OUT / "CNAME").write_text("thepurvangmehta.com\n", encoding="utf-8")

(OUT / "robots.txt").write_text(
    "User-agent: *\nAllow: /\nSitemap: https://www.thepurvangmehta.com/sitemap.xml\n",
    encoding="utf-8")

sitemap_urls = "\n".join(
    f"  <url><loc>{canonical_url(name)}</loc></url>" for name in PAGES
)
(OUT / "sitemap.xml").write_text(
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    f'{sitemap_urls}\n'
    '</urlset>\n',
    encoding="utf-8")
