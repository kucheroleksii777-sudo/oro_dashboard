from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0002_coldkey_kind_nickname"),
    ]

    operations = [
        migrations.AddField(
            model_name="coldkey",
            name="group",
            field=models.CharField(
                choices=[("mine", "My Keys"), ("other", "Other Keys")],
                default="mine",
                max_length=8,
            ),
        ),
    ]
