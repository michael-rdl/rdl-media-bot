#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")"
source venv/bin/activate
cd backend

# Ensure databases are running
cd ..
docker compose up -d
cd backend

echo "Starting RDL Media Bot..."
echo "Dashboard: http://$(hostname):80"
echo ""

# Start Django dev server on port 80
python manage.py runserver 0.0.0.0:80 &
DJANGO_PID=$!

# Start Celery worker with auto-reload on code changes
watchmedo auto-restart --directory=. --pattern='*.py' --recursive -- \
    celery -A media_bot worker -l info -c 2 &
CELERY_PID=$!

trap "kill $DJANGO_PID $CELERY_PID 2>/dev/null; exit" EXIT INT TERM

wait
