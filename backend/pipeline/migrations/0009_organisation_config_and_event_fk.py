import os

from django.db import migrations, models
import django.db.models.deletion


def create_default_organisation(apps, schema_editor):
    Organisation = apps.get_model("pipeline", "Organisation")
    Event = apps.get_model("pipeline", "Event")

    org, _ = Organisation.objects.get_or_create(
        code="FD",
        defaults={
            "name": "Formula Drift",
            "rdl_base_url": os.environ.get("RDL_BASE_URL", "https://fd.racedatalabs.com"),
            "rdl_base_api_url": os.environ.get("RDL_BASE_API_URL", "https://fd.racedatalabs.com/api/v1"),
            "rdl_internal_api_key": os.environ.get("RDL_INTERNAL_API_KEY", ""),
            "rdl_api_username": os.environ.get("RDL_API_USERNAME", ""),
            "rdl_api_password": os.environ.get("RDL_API_PASSWORD", ""),
            "instagram_handle": "formulad",
        },
    )
    Event.objects.filter(organisation__isnull=True).update(organisation=org)


class Migration(migrations.Migration):

    dependencies = [
        ("pipeline", "0008_event_sfx_fields"),
    ]

    operations = [
        migrations.RenameField(
            model_name="organisation",
            old_name="photo",
            new_name="logo",
        ),
        migrations.AddField(
            model_name="organisation",
            name="code",
            field=models.CharField(default="FD", help_text="Short code, e.g. FD for Formula Drift", max_length=20, unique=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="organisation",
            name="instagram_handle",
            field=models.CharField(blank=True, help_text="Organisation IG handle to tag in published media", max_length=200),
        ),
        migrations.AddField(
            model_name="organisation",
            name="logo_position_x",
            field=models.FloatField(default=0.05, help_text="0-1 fraction from left"),
        ),
        migrations.AddField(
            model_name="organisation",
            name="logo_position_y",
            field=models.FloatField(default=0.03, help_text="0-1 fraction from top"),
        ),
        migrations.AddField(
            model_name="organisation",
            name="logo_scale",
            field=models.FloatField(default=0.15, help_text="Logo width as fraction of video width"),
        ),
        migrations.AddField(
            model_name="organisation",
            name="rdl_api_password",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="organisation",
            name="rdl_api_username",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="organisation",
            name="rdl_base_api_url",
            field=models.URLField(default="https://fd.racedatalabs.com/api/v1", help_text="rdl-base REST API base URL"),
        ),
        migrations.AddField(
            model_name="organisation",
            name="rdl_base_url",
            field=models.URLField(default="https://fd.racedatalabs.com", help_text="Web UI base URL for replay capture and review links"),
        ),
        migrations.AddField(
            model_name="organisation",
            name="rdl_internal_api_key",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="organisation",
            name="logo",
            field=models.ImageField(blank=True, upload_to="organisations/logos/"),
        ),
        migrations.AddField(
            model_name="event",
            name="organisation",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="events",
                to="pipeline.organisation",
            ),
        ),
        migrations.RunPython(create_default_organisation, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="event",
            name="organisation",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="events",
                to="pipeline.organisation",
            ),
        ),
        migrations.AlterField(
            model_name="event",
            name="rdl_event_id",
            field=models.PositiveIntegerField(),
        ),
        migrations.AlterField(
            model_name="session",
            name="rdl_session_id",
            field=models.PositiveIntegerField(),
        ),
        migrations.AlterField(
            model_name="run",
            name="rdl_run_id",
            field=models.PositiveIntegerField(),
        ),
        migrations.AddConstraint(
            model_name="event",
            constraint=models.UniqueConstraint(fields=("organisation", "rdl_event_id"), name="unique_event_per_organisation"),
        ),
        migrations.AddConstraint(
            model_name="session",
            constraint=models.UniqueConstraint(fields=("event", "rdl_session_id"), name="unique_session_per_event"),
        ),
        migrations.AddConstraint(
            model_name="run",
            constraint=models.UniqueConstraint(fields=("event", "rdl_run_id"), name="unique_run_per_event"),
        ),
    ]
