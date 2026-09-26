#!/usr/bin/env bash
# Run the full pipeline once (collect + enrich + score + detect new businesses)
# Usage: docker compose run --rm scheduler bash scripts/run_pipeline.sh
set -e
echo "=== Starting full pipeline run ==="
python -m app.scheduler.scheduler --once
echo "=== Pipeline run complete ==="
