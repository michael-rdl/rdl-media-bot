#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

cd "$(dirname "$0")"

check_and_deploy() {
    git fetch origin main --quiet 2>/dev/null

    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)

    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "$(date): New changes detected, pulling..."
        git pull origin main --quiet
        echo "$(date): Updated. Django and Celery will auto-reload."
    fi
}

echo "$(date): Deploy watcher started (checking every 5s)"
while true; do
    check_and_deploy
    sleep 5
done
