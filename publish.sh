#!/usr/bin/env bash
# Збирає звіт з Databricks і публікує на GitHub Pages (loko-mbr-report).
set -euo pipefail
cd "$(dirname "$0")"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "→ Installing Python deps (if needed)..."
python3 -m pip install -q -r requirements.txt

echo "→ Generating index.html from Databricks..."
python3 generate_report.py

echo "→ Pushing to GitHub (main)..."
git add index.html report_data.json template.html generate_report.py 2>/dev/null || true
git add index.html report_data.json
if git diff --cached --quiet; then
  echo "Nothing to commit (report unchanged)."
else
  git commit -m "Оновлення звіту LOKO: $(date +'%Y-%m-%d %H:%M')"
fi
if ! git push origin main; then
  echo "✗ git push failed — налаштуйте SSH або gh auth login"
  exit 1
fi

echo "✓ Published: https://mykhailobrynchak-dev.github.io/loko-mbr-report/"
echo "  Refresh the page in ~30s (Cmd+Shift+R)."
