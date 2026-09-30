from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="coldkey",
            name="kind",
            field=models.CharField(
                choices=[("cold", "Coldkey"), ("hot", "Hotkey")],
                default="cold",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="coldkey",
            name="nickname",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
