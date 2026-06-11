import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pipeline', '0003_add_organisation_and_event'),
    ]

    operations = [
        # --- Driver & Sponsor (missing from prior migrations) ---
        migrations.CreateModel(
            name='Driver',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_name', models.CharField(max_length=100)),
                ('last_name', models.CharField(max_length=100)),
                ('car_number', models.CharField(max_length=10)),
                ('picture', models.ImageField(blank=True, upload_to='drivers/')),
                ('instagram', models.CharField(blank=True, max_length=200)),
                ('country', models.CharField(blank=True, max_length=100)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('spotter_first_name', models.CharField(blank=True, max_length=100)),
                ('spotter_last_name', models.CharField(blank=True, max_length=100)),
                ('spotter_instagram', models.CharField(blank=True, max_length=200)),
                ('spotter_email', models.EmailField(blank=True, max_length=254)),
                ('team_manager_first_name', models.CharField(blank=True, max_length=100)),
                ('team_manager_last_name', models.CharField(blank=True, max_length=100)),
                ('team_instagram', models.CharField(blank=True, max_length=200)),
                ('team_email', models.EmailField(blank=True, max_length=254)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['last_name', 'first_name']},
        ),
        migrations.CreateModel(
            name='Sponsor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('instagram', models.CharField(blank=True, max_length=200)),
                ('driver', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sponsors', to='pipeline.driver')),
            ],
            options={'ordering': ['name']},
        ),

        # --- Restructure Event: drop old flat model, create proper Event ---
        migrations.DeleteModel(name='Event'),
        migrations.CreateModel(
            name='Event',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rdl_event_id', models.PositiveIntegerField(unique=True)),
                ('name', models.CharField(max_length=200)),
                ('event_type', models.CharField(blank=True, max_length=50)),
                ('ig_highlight_pk', models.CharField(blank=True, max_length=255)),
                ('ig_highlight_url', models.URLField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['-created_at']},
        ),

        # --- New Session model ---
        migrations.CreateModel(
            name='Session',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rdl_session_id', models.PositiveIntegerField(unique=True)),
                ('name', models.CharField(max_length=200)),
                ('is_live', models.BooleanField(default=False)),
                ('last_run_seen_at', models.DateTimeField(blank=True, null=True)),
                ('last_polled_run_id', models.PositiveIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sessions', to='pipeline.event')),
            ],
            options={'ordering': ['name']},
        ),

        # --- Add session FK to Job ---
        migrations.AddField(
            model_name='job',
            name='session',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='jobs', to='pipeline.session'),
        ),
    ]
