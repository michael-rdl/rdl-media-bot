import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "media_bot.settings")

app = Celery("media_bot")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
