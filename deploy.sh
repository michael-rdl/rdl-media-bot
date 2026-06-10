#!/bin/bash
set -e

cd "$(dirname "$0")"

git fetch origin main --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date): New changes detected, deploying..."
    git pull origin main
    docker compose up -d --build
    echo "$(date): Deploy complete"
fi
