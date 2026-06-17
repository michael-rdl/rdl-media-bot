from django.contrib import admin

from .models import ContentPiece, ContentTemplate, Driver, Event, Job, Organisation, PublishResult, Run, Session, Sponsor, StreamSource


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


class SessionInline(admin.TabularInline):
    model = Session
    extra = 0
    readonly_fields = ("rdl_session_id", "is_live", "last_run_seen_at", "last_polled_run_id")


class EventInline(admin.TabularInline):
    model = Event
    extra = 0
    readonly_fields = ("rdl_event_id", "event_type", "created_at")
    show_change_link = True


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "instagram_handle", "rdl_base_url", "updated_at")
    search_fields = ("name", "code", "instagram_handle")
    readonly_fields = ("created_at", "updated_at")
    inlines = [EventInline]
    fieldsets = (
        (None, {
            "fields": ("name", "code", "instagram_handle"),
        }),
        ("rdl-base Server", {
            "fields": (
                "rdl_base_url",
                "rdl_base_api_url",
                "rdl_internal_api_key",
                "rdl_api_username",
                "rdl_api_password",
            ),
        }),
        ("Media Branding", {
            "fields": ("logo", "logo_position_x", "logo_position_y", "logo_scale"),
        }),
        ("Instagram Publishing", {
            "fields": (
                "instagram_auth_method",
                "instagram_user_id",
                "instagram_access_token",
                "instagram_username",
                "instagram_password",
                "instagram_account_name",
                "instagram_connected_at",
            ),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "organisation", "event_type", "rdl_event_id", "ig_highlight_pk", "created_at")
    search_fields = ("name", "organisation__name")
    list_filter = ("organisation", "event_type")
    inlines = [SessionInline]


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "rdl_session_id", "is_live", "last_run_seen_at", "created_at")
    list_filter = ("is_live", "event")
    search_fields = ("name", "event__name")


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ("rdl_run_id", "description", "session", "run_type", "run_number", "rdl_created_at")
    list_filter = ("event", "session", "run_type")
    search_fields = ("description", "rdl_run_id")


@admin.register(StreamSource)
class StreamSourceAdmin(admin.ModelAdmin):
    list_display = ("label", "url", "active", "updated_at")
    list_filter = ("active",)


@admin.register(ContentTemplate)
class ContentTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "output_width", "output_height", "active", "updated_at")
    list_filter = ("active",)
