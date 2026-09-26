#!/usr/bin/env bash
# Runs every configured connector once, synchronously. Useful for a first
# manual run, cron fallback, or CI smoke test.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m app.scheduler.scheduler --once
