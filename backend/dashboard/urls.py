from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.job_list, name="job-list"),
    path("jobs/<int:job_id>/", views.job_detail, name="job-detail"),
    path("jobs/<int:job_id>/retry/", views.job_retry, name="job-retry"),
    path("jobs/create/", views.job_create, name="job-create"),
    path("events/", views.event_list, name="event-list"),
    path("events/sync/", views.event_sync, name="event-sync"),
    path("organisations/", views.organisation_list, name="organisation-list"),
    path("organisations/<int:org_id>/", views.organisation_detail, name="organisation-detail"),
    path("organisations/<int:org_id>/update/", views.organisation_update, name="organisation-update"),
    path("organisations/<int:org_id>/sync/", views.organisation_sync, name="organisation-sync"),
    path("organisations/<int:org_id>/instagram/connect/", views.organisation_instagram_connect, name="organisation-instagram-connect"),
    path("organisations/<int:org_id>/instagram/test/", views.organisation_instagram_test, name="organisation-instagram-test"),
    path("organisations/<int:org_id>/instagram/disconnect/", views.organisation_instagram_disconnect, name="organisation-instagram-disconnect"),
    path("organisations/<int:org_id>/instagram/oauth/", views.instagram_oauth_start, name="instagram-oauth-start"),
    path("organisations/<int:org_id>/instagram/oauth/callback/", views.instagram_oauth_callback, name="instagram-oauth-callback"),
    path("events/<int:event_id>/", views.event_detail, name="event-detail"),
    path("events/<int:event_id>/audio/", views.event_update_audio, name="event-update-audio"),
    path("events/<int:event_id>/ads/", views.event_update_ads, name="event-update-ads"),
    path("events/<int:event_id>/sfx/", views.event_update_sfx, name="event-update-sfx"),
    path("events/<int:event_id>/create-highlight/", views.event_create_highlight, name="event-create-highlight"),
    path("sessions/<int:session_id>/", views.session_detail, name="session-detail"),
    path("sessions/<int:session_id>/toggle-live/", views.session_toggle_live, name="session-toggle-live"),
    path("streams/", views.stream_list, name="stream-list"),
    path("streams/add/", views.stream_add, name="stream-add"),
    path("streams/<int:pk>/toggle/", views.stream_toggle, name="stream-toggle"),
    path("streams/<int:pk>/delete/", views.stream_delete, name="stream-delete"),
    path("templates/", views.template_list, name="template-list"),
    path("test/", views.test_view, name="test"),
    path("test/generate/<int:run_id>/", views.test_generate, name="test-generate"),
    path("settings/", views.settings_view, name="settings"),
]
