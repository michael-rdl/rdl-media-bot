FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    fonts-dejavu-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir yt-dlp

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir playwright \
    && playwright install --with-deps chromium

COPY backend/ .

RUN python manage.py collectstatic --noinput 2>/dev/null || true

RUN mkdir -p /app/media/jobs

EXPOSE 8000

CMD ["gunicorn", "media_bot.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
