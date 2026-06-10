#!/bin/bash
#
# RDL Media Bot -- Mac Mini Setup Script
#
# Run this directly on the Mac Mini:
#   curl -fsSL https://raw.githubusercontent.com/michael-rdl/rdl-media-bot/main/setup-mac-mini.sh | bash
#
# Or copy this file over and run: bash setup-mac-mini.sh
#
set -e

echo "========================================="
echo "  RDL Media Bot - Mac Mini Setup"
echo "========================================="

# ---- 1. Enable SSH (Remote Login) ----
echo ""
echo "[1/6] Enabling SSH (Remote Login)..."
sudo systemsetup -setremotelogin on 2>/dev/null || echo "  SSH may already be enabled or requires System Settings"
echo "  SSH enabled. You can now access this machine via: ssh $(whoami)@$(hostname)"

# ---- 2. Install Homebrew (if not present) ----
echo ""
echo "[2/6] Checking Homebrew..."
if ! command -v brew &>/dev/null; then
    echo "  Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    eval "$(/opt/homebrew/bin/brew shellenv)"
else
    echo "  Homebrew already installed"
fi

# ---- 3. Install Tailscale (remote access from anywhere) ----
echo ""
echo "[3/6] Installing Tailscale for remote access..."
if ! command -v tailscale &>/dev/null; then
    brew install --cask tailscale
    echo ""
    echo "  *** IMPORTANT: Open Tailscale from Applications and sign in ***"
    echo "  After signing in, you can SSH from anywhere using your Tailscale IP."
    echo "  Install Tailscale on your other machines too: https://tailscale.com/download"
    echo ""
    echo "  Press ENTER after you've signed into Tailscale..."
    read -r
else
    echo "  Tailscale already installed"
fi

# Show Tailscale IP if connected
if command -v tailscale &>/dev/null; then
    TS_IP=$(tailscale ip -4 2>/dev/null || echo "not connected yet")
    echo "  Tailscale IP: $TS_IP"
    echo "  SSH from anywhere: ssh $(whoami)@$TS_IP"
fi

# ---- 4. Install Docker ----
echo ""
echo "[4/6] Checking Docker..."
if ! command -v docker &>/dev/null; then
    echo "  Installing Docker Desktop..."
    brew install --cask docker
    echo ""
    echo "  *** IMPORTANT: Open Docker Desktop from Applications and complete setup ***"
    echo "  Press ENTER after Docker Desktop is running..."
    read -r
else
    echo "  Docker already installed"
fi

# Verify Docker is running
if ! docker info &>/dev/null; then
    echo "  Waiting for Docker to start..."
    echo "  Please open Docker Desktop if it's not running."
    echo "  Press ENTER when Docker is ready..."
    read -r
fi
echo "  Docker is running: $(docker --version)"

# ---- 5. Clone the repo ----
echo ""
echo "[5/6] Cloning rdl-media-bot..."
REPO_DIR="$HOME/rdl-media-bot"
if [ -d "$REPO_DIR" ]; then
    echo "  Directory exists, pulling latest..."
    cd "$REPO_DIR"
    git pull origin main
else
    git clone https://github.com/michael-rdl/rdl-media-bot.git "$REPO_DIR"
    cd "$REPO_DIR"
fi

# Create .env from example if it doesn't exist
if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo ""
    echo "  Created .env from .env.example"
    echo "  *** IMPORTANT: Edit ~/rdl-media-bot/.env with your credentials ***"
    echo "  nano ~/rdl-media-bot/.env"
    echo ""
fi

# ---- 6. Set up auto-deploy cron ----
echo ""
echo "[6/6] Setting up auto-deploy watcher..."
CRON_CMD="* * * * * $REPO_DIR/deploy.sh >> $REPO_DIR/deploy.log 2>&1"
(crontab -l 2>/dev/null | grep -v "rdl-media-bot/deploy.sh"; echo "$CRON_CMD") | crontab -
echo "  Cron job installed (checks for updates every 60 seconds)"

# ---- Done ----
echo ""
echo "========================================="
echo "  Setup Complete!"
echo "========================================="
echo ""
echo "  Next steps:"
echo "  1. Edit credentials:  nano ~/rdl-media-bot/.env"
echo "  2. First run:         cd ~/rdl-media-bot && docker compose up -d --build"
echo "  3. Run migrations:    docker compose exec backend python manage.py migrate"
echo "  4. Create admin user: docker compose exec backend python manage.py createsuperuser"
echo ""
if command -v tailscale &>/dev/null; then
    TS_IP=$(tailscale ip -4 2>/dev/null || echo "<tailscale-ip>")
    echo "  Dashboard:  http://$TS_IP:8001"
    echo "  SSH access: ssh $(whoami)@$TS_IP"
else
    echo "  Dashboard:  http://$(hostname -I 2>/dev/null || hostname):8001"
fi
echo ""
echo "  Auto-deploy is active. Push to GitHub and the Mac Mini"
echo "  will pull and rebuild within 60 seconds."
echo ""
