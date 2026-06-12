from django.db import models


class Driver(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    car_number = models.CharField(max_length=10)
    picture = models.ImageField(upload_to="drivers/", blank=True)
    instagram = models.CharField(max_length=200, blank=True)
    country = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)

    spotter_first_name = models.CharField(max_length=100, blank=True)
    spotter_last_name = models.CharField(max_length=100, blank=True)
    spotter_instagram = models.CharField(max_length=200, blank=True)
    spotter_email = models.EmailField(blank=True)

    team_manager_first_name = models.CharField(max_length=100, blank=True)
    team_manager_last_name = models.CharField(max_length=100, blank=True)
    team_instagram = models.CharField(max_length=200, blank=True)
    team_email = models.EmailField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} (#{self.car_number})"


class Sponsor(models.Model):
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="sponsors")
    name = models.CharField(max_length=200)
    instagram = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (sponsor of {self.driver})"


class Organisation(models.Model):
    name = models.CharField(max_length=200)
    photo = models.ImageField(upload_to="organisations/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Event(models.Model):
    rdl_event_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=200)
    event_type = models.CharField(max_length=50, blank=True)
    ig_highlight_pk = models.CharField(max_length=255, blank=True)
    ig_highlight_url = models.URLField(blank=True)

    audio_file = models.FileField(upload_to="events/audio/", blank=True)

    ads_enabled = models.BooleanField(default=False)
    ad_video = models.FileField(upload_to="events/ads/", blank=True)
    ad_frequency = models.PositiveIntegerField(
        default=10,
        help_text="Publish an ad every N posts",
    )
    ad_instagram_handle = models.CharField(
        max_length=200,
        default="truedriftofficial",
        help_text="IG handle to tag in ad posts",
    )
    posts_since_last_ad = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Session(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="sessions")
    rdl_session_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=200)
    is_live = models.BooleanField(default=False)
    last_run_seen_at = models.DateTimeField(null=True, blank=True)
    last_polled_run_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.event.name} - {self.name}"


class Run(models.Model):
    """Cached run data from rdl-base, linked to a session."""
    rdl_run_id = models.PositiveIntegerField(unique=True)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="runs", null=True, blank=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="runs")
    description = models.CharField(max_length=500, blank=True)
    run_type = models.CharField(max_length=50, blank=True)
    run_number = models.PositiveIntegerField(null=True, blank=True)
    rdl_created_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-rdl_run_id"]

    def __str__(self):
        return f"Run {self.rdl_run_id}: {self.description}"


class StreamSource(models.Model):
    label = models.CharField(max_length=200)
    url = models.URLField(help_text="YouTube stream or VOD URL")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} ({'active' if self.active else 'inactive'})"


class ContentTemplate(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)

    output_width = models.PositiveIntegerField(default=1080)
    output_height = models.PositiveIntegerField(default=1920)
    output_fps = models.PositiveIntegerField(default=30)
    max_duration_seconds = models.PositiveIntegerField(
        default=60,
        help_text="Max output duration (60s for Stories, 90s for Reels)",
    )

    logo_path = models.CharField(max_length=500, blank=True)
    logo_position_x = models.FloatField(default=0.05, help_text="0-1 fraction from left")
    logo_position_y = models.FloatField(default=0.03, help_text="0-1 fraction from top")
    logo_scale = models.FloatField(default=0.15)

    show_driver_name = models.BooleanField(default=True)
    show_run_stats = models.BooleanField(default=True)
    show_speed_overlay = models.BooleanField(default=True)

    font_family = models.CharField(max_length=100, default="Arial")
    font_size = models.PositiveIntegerField(default=48)
    font_color = models.CharField(max_length=20, default="white")
    text_bg_color = models.CharField(max_length=20, default="rgba(0,0,0,0.6)")

    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Job(models.Model):
    class Status(models.TextChoices):
        TRIGGERED = "triggered", "Triggered"
        CAPTURING = "capturing", "Capturing Viz"
        CLIPPING = "clipping", "Clipping Stream"
        COMPOSING = "composing", "Composing Story"
        PUBLISHING = "publishing", "Publishing"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    rdl_run_id = models.IntegerField(db_index=True)
    event_session_id = models.IntegerField(null=True, blank=True)
    session = models.ForeignKey(
        "Session",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jobs",
    )
    driver_name = models.CharField(max_length=200, blank=True)
    run_number = models.CharField(max_length=50, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TRIGGERED,
        db_index=True,
    )
    status_message = models.CharField(
        max_length=255,
        blank=True,
        help_text="Live progress message for the current pipeline stage",
    )
    error_message = models.TextField(blank=True)
    failed_stage = models.CharField(max_length=50, blank=True)

    stream_source = models.ForeignKey(
        StreamSource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    template = models.ForeignKey(
        ContentTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    run_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Snapshot of run data from rdl-base API",
    )

    skip_youtube_clip = models.BooleanField(default=False)
    publish_as_reel = models.BooleanField(
        default=False,
        help_text="Publish as Reel instead of Story",
    )

    celery_task_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        driver = self.driver_name or "Unknown"
        return f"Job #{self.pk} - {driver} Run {self.run_number} [{self.status}]"


class ContentPiece(models.Model):
    class PieceType(models.TextChoices):
        VIZ_CAPTURE = "viz_capture", "Visualiser Capture"
        STREAM_CLIP = "stream_clip", "Stream Clip"
        AUDIO_EXTRACT = "audio_extract", "Audio Extract"
        COMPOSED_STORY = "composed_story", "Composed Story"

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="pieces")
    piece_type = models.CharField(max_length=30, choices=PieceType.choices)
    file = models.FileField(upload_to="jobs/pieces/")
    mime_type = models.CharField(max_length=100, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    file_size_bytes = models.BigIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_piece_type_display()} for Job #{self.job_id}"


class PublishResult(models.Model):
    class Platform(models.TextChoices):
        INSTAGRAM_STORY = "ig_story", "Instagram Story"
        INSTAGRAM_REEL = "ig_reel", "Instagram Reel"
        YOUTUBE_SHORT = "yt_short", "YouTube Short"
        YOUTUBE_VIDEO = "yt_video", "YouTube Video"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        UPLOADING = "uploading", "Uploading"
        PROCESSING = "processing", "Processing"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"

    content_piece = models.ForeignKey(
        ContentPiece,
        on_delete=models.CASCADE,
        related_name="publish_results",
    )
    platform = models.CharField(max_length=20, choices=Platform.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    platform_post_id = models.CharField(max_length=255, blank=True)
    platform_url = models.URLField(blank=True)
    caption = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_platform_display()} - {self.status}"
