#!/bin/bash
# Takes a real PNG screenshot of the "Claude Agents Activity Perso"
# Grafana dashboard (anonymous Viewer access, no auth needed) and
# commits+pushes it if it changed. Meant to run on a schedule (cron)
# on the host — Chrome isn't available inside the docker-compose
# containers, Grafana's port is published to the host at :3002.
set -euo pipefail

REPO_DIR="/home/james/docker/miami-vice"
DASHBOARD_URL="http://localhost:3002/d/ag5cdhxrs7ojkf/claude-agents-activity-perso"
OUT_FILE="$REPO_DIR/doc/monitoring/grafana-dashboard.png"

mkdir -p "$(dirname "$OUT_FILE")"

google-chrome --headless=new --disable-gpu --window-size=1920,1080 \
  --screenshot="$OUT_FILE" --virtual-time-budget=6000 \
  "$DASHBOARD_URL" >/tmp/grafana-snapshot-chrome.log 2>&1

cd "$REPO_DIR"
git add "$OUT_FILE"
if ! git diff --cached --quiet -- "$OUT_FILE"; then
  git commit -m "monitoring: update Grafana dashboard snapshot ($(date '+%Y-%m-%d %H:%M'))" >/tmp/grafana-snapshot-commit.log 2>&1
  git push >/tmp/grafana-snapshot-push.log 2>&1
fi
