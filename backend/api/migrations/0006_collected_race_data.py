from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0005_distinct_key_colors"),
    ]

    operations = [
        migrations.CreateModel(
            name="CollectedRace",
            fields=[
                ("race_id", models.CharField(max_length=128, primary_key=True, serialize=False)),
                ("race_number", models.IntegerField(blank=True, null=True)),
                ("status", models.CharField(blank=True, default="", max_length=32)),
                ("agent_count", models.IntegerField(default=0)),
                ("completed_at", models.CharField(blank=True, default="", max_length=64)),
                ("overall_agent", models.CharField(blank=True, default="", max_length=256)),
                ("overall_score", models.FloatField(blank=True, null=True)),
                ("race_agent", models.CharField(blank=True, default="", max_length=256)),
                ("race_score", models.FloatField(blank=True, null=True)),
                ("collected_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-race_number"],
            },
        ),
        migrations.CreateModel(
            name="CollectedRaceTable",
            fields=[
                ("race_id", models.CharField(max_length=128, primary_key=True, serialize=False)),
                ("race_number", models.IntegerField(blank=True, null=True)),
                ("rows", models.JSONField(default=list)),
                ("enriched", models.BooleanField(default=False)),
                ("collected_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="CollectedAgent",
            fields=[
                ("agent_version_id", models.CharField(max_length=128, primary_key=True, serialize=False)),
                ("code", models.CharField(default="private", max_length=16)),
                ("submitted_at", models.CharField(blank=True, default="", max_length=64)),
                ("lines", models.IntegerField(blank=True, null=True)),
                ("race_count", models.IntegerField(blank=True, null=True)),
                ("collected_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="CollectedAgentCells",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("agent_version_id", models.CharField(max_length=128)),
                ("race_id", models.CharField(max_length=128)),
                ("product", models.JSONField(default=list)),
                ("shop", models.JSONField(default=list)),
                ("voucher", models.JSONField(default=list)),
                ("collected_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="collectedagentcells",
            constraint=models.UniqueConstraint(
                fields=("agent_version_id", "race_id"),
                name="uniq_collected_agent_race_cells",
            ),
        ),
    ]
