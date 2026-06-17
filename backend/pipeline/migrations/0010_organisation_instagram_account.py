from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pipeline", "0009_organisation_config_and_event_fk"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="instagram_access_token",
            field=models.CharField(
                blank=True,
                help_text="Page access token with instagram_content_publish (Graph API)",
                max_length=512,
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="instagram_account_name",
            field=models.CharField(
                blank=True,
                help_text="Cached @handle from last successful connection test",
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="instagram_auth_method",
            field=models.CharField(
                blank=True,
                choices=[("graph", "Instagram Graph API"), ("instagrapi", "Instagram Private API (instagrapi)")],
                help_text="How this organisation publishes to Instagram",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="instagram_connected_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="instagram_password",
            field=models.CharField(
                blank=True,
                help_text="Instagram login password (instagrapi)",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="instagram_user_id",
            field=models.CharField(
                blank=True,
                help_text="Instagram Business Account ID (Graph API)",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="instagram_username",
            field=models.CharField(
                blank=True,
                help_text="Instagram login username (instagrapi)",
                max_length=200,
            ),
        ),
    ]
