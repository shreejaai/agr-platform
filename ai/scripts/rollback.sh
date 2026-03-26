#!/bin/bash
set -e

echo "Rolling back last commit..."
git reset --hard HEAD~1

echo "Rebuilding containers after rollback..."
docker compose down
docker compose up -d --build

echo "Rollback complete"
