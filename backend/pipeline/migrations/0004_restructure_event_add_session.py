import django.db.models.deletion
from django.db import migrations, models


def create_driver_if_not_exists(apps, schema_editor):
    """Driver/Sponsor may already exist from a manually-applied migration."""
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_tables WHERE tablename = 'pipeline_driver'")
        if cursor.fetchone():
            return
    # If the table doesn't exist, let Django create it via the next operation
    raise Exception("NEEDS_CREATE")


class Migration(migrations.Migration):

    dependencies = [
        ('pipeline', '0003_add_organisation_and_event'),
    ]

    operations = [
        # --- Driver & Sponsor: create only if not already present ---
        migrations.RunSQL(
            sql=[
                """
                CREATE TABLE IF NOT EXISTS pipeline_driver (
                    id bigserial PRIMARY KEY,
                    first_name varchar(100) NOT NULL,
                    last_name varchar(100) NOT NULL,
                    car_number varchar(10) NOT NULL,
                    picture varchar(100) NOT NULL DEFAULT '',
                    instagram varchar(200) NOT NULL DEFAULT '',
                    country varchar(100) NOT NULL DEFAULT '',
                    email varchar(254) NOT NULL DEFAULT '',
                    spotter_first_name varchar(100) NOT NULL DEFAULT '',
                    spotter_last_name varchar(100) NOT NULL DEFAULT '',
                    spotter_instagram varchar(200) NOT NULL DEFAULT '',
                    spotter_email varchar(254) NOT NULL DEFAULT '',
                    team_manager_first_name varchar(100) NOT NULL DEFAULT '',
                    team_manager_last_name varchar(100) NOT NULL DEFAULT '',
                    team_instagram varchar(200) NOT NULL DEFAULT '',
                    team_email varchar(254) NOT NULL DEFAULT '',
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS pipeline_sponsor (
                    id bigserial PRIMARY KEY,
                    name varchar(200) NOT NULL,
                    instagram varchar(200) NOT NULL DEFAULT '',
                    driver_id bigint NOT NULL REFERENCES pipeline_driver(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
                );
                """,
                "CREATE INDEX IF NOT EXISTS pipeline_sponsor_driver_id_idx ON pipeline_sponsor(driver_id);",
            ],
            reverse_sql=[
                "DROP TABLE IF EXISTS pipeline_sponsor;",
                "DROP TABLE IF EXISTS pipeline_driver;",
            ],
            state_operations=[
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
            ],
        ),

        # --- Restructure Event: drop old flat table, create new schema ---
        migrations.RunSQL(
            sql=[
                "DROP TABLE IF EXISTS pipeline_event;",
                """
                CREATE TABLE pipeline_event (
                    id bigserial PRIMARY KEY,
                    rdl_event_id integer NOT NULL UNIQUE,
                    name varchar(200) NOT NULL,
                    event_type varchar(50) NOT NULL DEFAULT '',
                    ig_highlight_pk varchar(255) NOT NULL DEFAULT '',
                    ig_highlight_url varchar(200) NOT NULL DEFAULT '',
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                );
                """,
            ],
            reverse_sql=[
                "DROP TABLE IF EXISTS pipeline_event;",
            ],
            state_operations=[
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
            ],
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
