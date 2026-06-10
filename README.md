# RDL Media Bot

Autonomous social media content pipeline for Race Data Labs. Captures telemetry visualisations from rdl-base, clips YouTube streams, composites 9:16 stories, and publishes to Instagram and YouTube.

## Quick Start

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env with your API credentials

# 2. Create the shared Docker network (if not already created by rdl-base)
docker network create rdl-network 2>/dev/null || true

# 3. Start services
docker compose up -d --build

# 4. Run migrations
docker compose exec backend python manage.py migrate

# 5. Create a superuser for the admin/dashboard
docker compose exec backend python manage.py createsuperuser

# 6. Install Playwright browsers (first run only)
docker compose exec celery-worker playwright install chromium
```

The dashboard is available at `http://localhost:8001` and Django admin at `http://localhost:8001/admin/`.

## Development

```bash
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml exec backend python manage.py migrate
```

## Architecture

```
Webhook (rdl-base run complete)
  → Capture (Playwright records Three.js visualiser replay)
  → Clip (yt-dlp downloads YouTube stream segment)
  → Compose (ffmpeg combines viz + audio into 9:16 story)
  → Publish (Instagram Graph API + YouTube Data API)
```

## rdl-base Integration

Add to rdl-base's `.env`:

```
MEDIA_BOT_WEBHOOK_URL=http://backend:8000/api/webhook/run-complete/
MEDIA_BOT_WEBHOOK_SECRET=your-shared-secret
```

The webhook fires automatically after `process_raw_session` completes.

## API Credentials

- **Instagram**: Meta Developer App with `instagram_content_publish` permission + Business account
- **YouTube**: Google Cloud project with YouTube Data API v3 + OAuth2 token
- **rdl-base**: Internal API key for fetching run metadata
