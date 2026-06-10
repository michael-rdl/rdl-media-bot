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

        if echo "$CHANGED" | grep -qE "Dockerfile|requirements.txt"; then
            echo "$(date): Infrastructure changed, rebuilding images..."
            docker compose down
            docker compose up -d --build
        elif echo "$CHANGED" | grep -qE "docker-compose|\.env"; then
            echo "$(date): Config changed, recreating containers..."
            docker compose down
            docker compose up -d
        else
            echo "$(date): Code-only change, recreating workers..."
            docker compose up -d --force-recreate --no-build
        fi

        echo "$(date): Deploy complete"
    fi
}

echo "$(date): Deploy watcher started (checking every 5s)"
while true; do
    check_and_deploy
    sleep 5
done
