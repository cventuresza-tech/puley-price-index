#!/bin/sh
# Runs deploy/daily.sh once a day at 02:30 UTC (04:30 in South Africa), forever. A failed day is logged and retried next day.
while true; do
  now=$(date -u +%s); next=$(date -u -d "$(date -u +%F) 02:30" +%s)
  [ "$next" -le "$now" ] && next=$((next + 86400))
  echo "next run $(date -u -d @$next '+%F %H:%M') UTC"; sleep $((next - now))
  sh deploy/daily.sh || echo "daily run failed $(date -u '+%F %T')"
done
