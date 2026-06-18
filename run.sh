#!/bin/bash
export PATH="/opt/homebrew/bin:/opt/homebrew/opt/python@3.11/libexec/bin:/usr/local/bin:$PATH"

cd "$(dirname "$0")"

if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# Create venv if missing
if [ ! -d "venv" ]; then
    python3.11 -m venv venv
    source venv/bin/activate
    pip install -r backend/requirements.txt
    pip install watchdog[watchmedo] yt-dlp
    playwright install chromium
else
    source venv/bin/activate
fi

# Ensure databases are running
docker compose up -d --remove-orphans

echo "Starting RDL Media Bot..."
echo "Dashboard: http://$(hostname):80"
echo ""

cd backend

# Start Django dev server on port 80
python manage.py runserver 0.0.0.0:80 &
DJANGO_PID=$!

# Start Celery worker with auto-reload
watchmedo auto-restart --directory=. --pattern='*.py' --recursive -- \
    celery -A media_bot worker -l info -c 2 &
CELERY_PID=$!

trap "kill $DJANGO_PID $CELERY_PID 2>/dev/null; exit" EXIT INT TERM

wait
