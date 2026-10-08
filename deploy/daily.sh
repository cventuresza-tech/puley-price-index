#!/bin/sh
# One day's run: read the prices (AI apps daily, the rest on their weekday) through the engine, rebuild, commit, push, and ask
# jsDelivr to drop its copy of the latest files. Needs INFRARED_ENGINE(+_TOKEN) or PULEY_ENGINE_URL(+_TOKEN) and a git remote
# that this machine can push to.
set -eu
cd /index
python -m puley_price_index daily --workers 6
git add -A data README.md assets 2>/dev/null || git add -A data README.md
if git diff --cached --quiet; then echo "nothing new"; exit 0; fi
git -c user.name="Puley Price Index" -c user.email="hello@puley.com" commit -q -m "Prices for $(date -u +%F)"
git push -q origin HEAD:main
for f in index.json prices.csv; do curl -s -o /dev/null "https://purge.jsdelivr.net/gh/cventuresza-tech/puley-price-index@main/data/latest/$f"; done
for f in data/latest/apps/*.json; do curl -s -o /dev/null "https://purge.jsdelivr.net/gh/cventuresza-tech/puley-price-index@main/$f"; done
echo "pushed $(git rev-parse --short HEAD)"
