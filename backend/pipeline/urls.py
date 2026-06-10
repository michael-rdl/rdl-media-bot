from django.urls import path

from . import views

app_name = "pipeline"

urlpatterns = [
    path("webhook/run-complete/", views.run_complete_webhook, name="run-complete-webhook"),
    path("jobs/", views.job_list_api, name="job-list-api"),
    path("jobs/<int:job_id>/", views.job_detail_api, name="job-detail-api"),
    path("jobs/<int:job_id>/retry/", views.job_retry_api, name="job-retry-api"),
    path("drivers/", views.driver_list_api, name="driver-list-api"),
    path("drivers/<int:driver_id>/", views.driver_detail_api, name="driver-detail-api"),
]
