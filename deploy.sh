#!/usr/bin/env bash
# Rebuild the static site and deploy it to GitHub Pages in one shot.
#
#   ./deploy.sh "commit message"
#
# Does: python3 build.py -> commit main -> push main -> rebuild the
# gh-pages branch from site/ (subtree split) -> force-push gh-pages.
# GitHub Pages serves gh-pages/, so the force-push is what goes live.
#
# fsmonitor is disabled because this Mac's filesystem makes git's
# working-tree scans hang; reads are fine, writes are just slow (~25s).
set -euo pipefail
cd "$(dirname "$0")"

MSG="${1:-Update site}"
GIT="git -c core.fsmonitor=false"
export GIT_TERMINAL_PROMPT=0

# NDA/gated case studies are AES-encrypted at build time with a password that
# lives ONLY in your environment, never in the repo. Prompt if it is not set.
if [ -z "${CS_GATE_PW:-}" ]; then
  read -rsp "CS_GATE_PW (password for gated case studies, blank = ship locked): " CS_GATE_PW
  echo
  export CS_GATE_PW
fi
echo ">> build";            CS_GATE_PW="${CS_GATE_PW:-}" python3 build.py >/dev/null
echo ">> stage + commit";   $GIT add -A
$GIT commit -m "$MSG" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" \
  || { echo "   (nothing to commit — deploying current HEAD)"; }
echo ">> push main";        $GIT push origin main
echo ">> rebuild gh-pages"; $GIT branch -D gh-pages 2>/dev/null || true
$GIT subtree split --prefix=site -b gh-pages >/dev/null
echo ">> push gh-pages";    $GIT push -f origin gh-pages
echo ">> DONE — live at https://thepurvangmehta.com (Pages rebuild ~30s)"
