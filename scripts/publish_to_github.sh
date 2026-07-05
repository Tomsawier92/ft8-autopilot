#!/usr/bin/env bash
# Push ft8-autopilot to GitHub (public). Requires valid PAT in ../pwd/github.txt or GH_TOKEN env.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TOKEN="${GH_TOKEN:-}"
if [[ -z "$TOKEN" && -f "$HOME/ai/pwd/github.txt" ]]; then
  TOKEN="$(tr -d '\n' < "$HOME/ai/pwd/github.txt")"
fi
if [[ -z "$TOKEN" ]]; then
  echo "Set GH_TOKEN or create ~/ai/pwd/github.txt with a GitHub Personal Access Token (repo scope)."
  exit 1
fi

export GH_TOKEN="$TOKEN"
echo "$TOKEN" | gh auth login --with-token

REPO="ft8-autopilot"
USER="$(gh api user -q .login)"

if gh repo view "$USER/$REPO" >/dev/null 2>&1; then
  echo "Repo exists — pushing..."
  git remote remove origin 2>/dev/null || true
  git remote add origin "https://github.com/$USER/$REPO.git"
  git push -u origin main
else
  gh repo create "$REPO" --public \
    --description "Open-source FT8 decoder, GUI, and automated operator (PyFT8, PRO scoring, ADIF, PTT)" \
    --source=. --remote=origin --push
fi

gh repo edit "$USER/$REPO" \
  --add-topic ft8 --add-topic amateur-radio --add-topic ham-radio \
  --add-topic pyft8 --add-topic wsjt-x --add-topic python

echo "Done: https://github.com/$USER/$REPO"
