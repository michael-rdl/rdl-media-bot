from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.job_list, name="job-list"),
    path("jobs/<int:job_id>/", views.job_detail, name="job-detail"),
    path("jobs/<int:job_id>/retry/", views.job_retry, name="job-retry"),
    path("jobs/create/", views.job_create, name="job-create"),
    path("streams/", views.stream_list, name="stream-list"),
    path("streams/add/", views.stream_add, name="stream-add"),
    path("streams/<int:pk>/toggle/", views.stream_toggle, name="stream-toggle"),
    path("streams/<int:pk>/delete/", views.stream_delete, name="stream-delete"),
    path("templates/", views.template_list, name="template-list"),
    path("settings/", views.settings_view, name="settings"),
]
