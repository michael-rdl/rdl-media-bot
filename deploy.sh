#!/bin/bash
set -e

cd "$(dirname "$0")"

check_and_deploy() {
    git fetch origin main --quiet

    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)

    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "$(date): New changes detected, deploying..."

        CHANGED=$(git diff --name-only "$LOCAL" "$REMOTE")

        git pull origin main --quiet

        if echo "$CHANGED" | grep -qE "Dockerfile|requirements.txt|docker-compose"; then
            echo "$(date): Infrastructure changed, rebuilding images..."
            docker compose up -d --build
        else
            echo "$(date): Code-only change, restarting containers..."
            docker compose up -d --force-recreate --no-build
        fi

        echo "$(date): Deploy complete"
    fi
}

echo "$(date): Deploy watcher started (checking every 30s)"
while true; do
    check_and_deploy
    sleep 30
done
