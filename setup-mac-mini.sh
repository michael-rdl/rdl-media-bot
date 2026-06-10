#!/bin/bash
#
# RDL Media Bot -- Mac Mini Setup (Native)
#
# Run on the Mac Mini:
#   curl -fsSL https://raw.githubusercontent.com/michael-rdl/rdl-media-bot/main/setup-mac-mini.sh | bash
#
set -e

echo "========================================="
echo "  RDL Media Bot - Mac Mini Setup"
echo "========================================="

REPO_DIR="$HOME/rdl-media-bot"

# ---- 1. Homebrew ----
echo ""
echo "[1/7] Checking Homebrew..."
if ! command -v brew &>/dev/null; then
    echo "  Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    eval "$(/opt/homebrew/bin/brew shellenv)"
else
    echo "  Already installed"
fi

# ---- 2. System deps ----
echo ""
echo "[2/7] Installing system dependencies..."
brew install ffmpeg python@3.11 git 2>/dev/null || true
pip3.11 install --upgrade pip 2>/dev/null || true

# ---- 3. Docker (for PostGIS + Redis only) ----
echo ""
echo "[3/7] Checking Docker..."
if ! command -v docker &>/dev/null; then
    echo "  Installing Docker Desktop..."
    brew install --cask docker
    echo "  *** Open Docker Desktop from Applications and complete setup ***"
    echo "  Press ENTER when Docker is running..."
    read -r
fi

# ---- 4. Clone repo ----
echo ""
echo "[4/7] Setting up repository..."
if [ -d "$REPO_DIR" ]; then
    cd "$REPO_DIR"
    git pull origin main
else
    git clone https://github.com/michael-rdl/rdl-media-bot.git "$REPO_DIR"
    cd "$REPO_DIR"
fi

# ---- 5. Python venv + deps ----
echo ""
echo "[5/7] Setting up Python environment..."
if [ ! -d "$REPO_DIR/venv" ]; then
    python3.11 -m venv "$REPO_DIR/venv"
fi
source "$REPO_DIR/venv/bin/activate"
pip install -r "$REPO_DIR/backend/requirements.txt"

# Install Playwright + Chromium with GPU support
playwright install chromium

# Install yt-dlp
pip install yt-dlp

# ---- 6. Start databases ----
echo ""
echo "[6/7] Starting PostGIS + Redis..."
cd "$REPO_DIR"
docker compose up -d

# Wait for PostGIS to be ready
echo "  Waiting for PostGIS..."
sleep 5

# Create database if needed
docker compose exec -T db psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'media_bot'" | grep -q 1 || \
    docker compose exec -T db psql -U postgres -c "CREATE DATABASE media_bot;"
docker compose exec -T db psql -U postgres -d media_bot -c "CREATE EXTENSION IF NOT EXISTS postgis;" 2>/dev/null || true

# Run migrations
cd "$REPO_DIR/backend"
python manage.py migrate

# ---- 7. Set up services ----
echo ""
echo "[7/7] Setting up auto-start services..."

# Create the run script
cat > "$REPO_DIR/run.sh" << 'RUNEOF'
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")"
source venv/bin/activate
cd backend

# Start Django dev server
python manage.py runserver 0.0.0.0:80 &
DJANGO_PID=$!

# Start Celery worker with auto-reload
watchmedo auto-restart --directory=. --pattern='*.py' --recursive -- \
    celery -A media_bot worker -l info -c 2 &
CELERY_PID=$!

echo "Django PID: $DJANGO_PID"
echo "Celery PID: $CELERY_PID"
echo "Dashboard: http://$(hostname):80"

trap "kill $DJANGO_PID $CELERY_PID 2>/dev/null" EXIT
wait
RUNEOF
chmod +x "$REPO_DIR/run.sh"

# Install watchdog for celery auto-reload
pip install watchdog[watchmedo]

echo ""
echo "========================================="
echo "  Setup Complete!"
echo "========================================="
echo ""
echo "  To start everything:"
echo "    cd ~/rdl-media-bot && sudo ./run.sh"
echo ""
echo "  Dashboard: http://$(hostname):80"
echo ""
echo "  The deploy watcher auto-pulls code changes."
echo "  Django auto-reloads on code changes."
echo "  Celery auto-restarts on code changes."
echo ""
