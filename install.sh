#!/usr/bin/env bash
# Book Chapter Editor — one-command installer
# Usage: bash install.sh

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
RESET="\033[0m"

step() { echo -e "\n${BOLD}$1${RESET}"; }
ok()   { echo -e "  ${GREEN}✓${RESET} $1"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
fail() { echo -e "  ${RED}✗${RESET}  $1"; exit 1; }

echo -e "${BOLD}Book Chapter Editor — installer${RESET}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Python check ───────────────────────────────────────────────────────────
step "Checking Python..."
if ! command -v python3 &>/dev/null; then
  fail "Python 3 not found. Install it from https://python.org"
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 11 ) ]]; then
  fail "Python 3.11+ required (found $PY_VER). Download from https://python.org"
fi
ok "Python $PY_VER"

# ── 2. Install dependencies ───────────────────────────────────────────────────
step "Installing Python dependencies..."
if python3 -m pip install -q -r requirements.txt; then
  ok "Dependencies installed"
else
  fail "pip install failed. Try: python3 -m pip install --user -r requirements.txt"
fi

# ── 3. .env file ──────────────────────────────────────────────────────────────
step "Setting up environment..."
if [[ ! -f .env ]]; then
  cp .env.example .env
  warn ".env file created — you must add your ANTHROPIC_API_KEY before starting"
  echo ""
  echo "  Edit .env and paste your key:"
  echo "    ANTHROPIC_API_KEY=sk-ant-api03-..."
  echo ""
  echo "  Get your key at: https://console.anthropic.com"
else
  ok ".env file already exists"
fi

# ── 4. Uploads directory ──────────────────────────────────────────────────────
mkdir -p uploads
ok "uploads/ directory ready"

# ── 5. Claude Code skill (optional) ──────────────────────────────────────────
step "Installing Claude Code skill..."
SKILL_SRC=".claude/skills/book-editor/SKILL.md"
SKILL_DST="$HOME/.claude/skills/book-editor/SKILL.md"
if [[ -f "$SKILL_SRC" ]]; then
  mkdir -p "$(dirname "$SKILL_DST")"
  cp "$SKILL_SRC" "$SKILL_DST"
  ok "Skill installed at $SKILL_DST"
  ok "/book-editor is now available in all Claude Code sessions"
else
  warn "Skill file not found — skipping"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
echo ""

if grep -q "^ANTHROPIC_API_KEY=sk-ant-" .env 2>/dev/null; then
  echo -e "  Start the server:  ${BOLD}uvicorn backend.main:app --reload${RESET}"
  echo -e "  Open in browser:   ${BOLD}http://localhost:8000${RESET}"
else
  echo -e "  ${YELLOW}Next step:${RESET} Add your API key to ${BOLD}.env${RESET}"
  echo ""
  echo "  Then start:  uvicorn backend.main:app --reload"
  echo "  Open:        http://localhost:8000"
fi
echo ""
