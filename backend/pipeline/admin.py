from django.contrib import admin

from .models import ContentPiece, ContentTemplate, Driver, Job, PublishResult, Sponsor, StreamSource


class SponsorInline(admin.TabularInline):
    model = Sponsor
    extra = 1


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("__str__", "car_number", "country", "email", "updated_at")
    search_fields = ("first_name", "last_name", "car_number", "email")
    list_filter = ("country",)
    inlines = [SponsorInline]
    fieldsets = (
        (None, {
            "fields": ("first_name", "last_name", "car_number", "picture", "instagram", "country", "email"),
        }),
        ("Spotter", {
            "fields": ("spotter_first_name", "spotter_last_name", "spotter_instagram", "spotter_email"),
        }),
        ("Team Manager", {
            "fields": ("team_manager_first_name", "team_manager_last_name", "team_instagram", "team_email"),
        }),
    )


class ContentPieceInline(admin.TabularInline):
    model = ContentPiece
    extra = 0
    readonly_fields = ("piece_type", "file", "duration_seconds", "width", "height", "created_at")


class PublishResultInline(admin.TabularInline):
    model = PublishResult
    extra = 0
    readonly_fields = ("platform", "status", "platform_url", "published_at")


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "driver_name", "run_number", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("driver_name", "run_number")
    readonly_fields = ("celery_task_id", "created_at", "updated_at")
    inlines = [ContentPieceInline]


@admin.register(ContentPiece)
class ContentPieceAdmin(admin.ModelAdmin):
    list_display = ("id", "job", "piece_type", "duration_seconds", "created_at")
    list_filter = ("piece_type",)
    inlines = [PublishResultInline]


@admin.register(PublishResult)
class PublishResultAdmin(admin.ModelAdmin):
    list_display = ("id", "content_piece", "platform", "status", "published_at")
    list_filter = ("platform", "status")


@admin.register(StreamSource)
class StreamSourceAdmin(admin.ModelAdmin):
    list_display = ("label", "url", "active", "updated_at")
    list_filter = ("active",)


@admin.register(ContentTemplate)
class ContentTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "output_width", "output_height", "active", "updated_at")
    list_filter = ("active",)
