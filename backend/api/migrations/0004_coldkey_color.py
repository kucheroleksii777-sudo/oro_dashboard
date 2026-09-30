from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0003_coldkey_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="coldkey",
            name="color",
            field=models.CharField(blank=True, default="#4ea1ff", max_length=7),
        ),
    ]
