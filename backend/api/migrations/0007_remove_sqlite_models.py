from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0006_collected_race_data"),
    ]

    operations = [
        migrations.DeleteModel(name="CollectedAgentCells"),
        migrations.DeleteModel(name="CollectedAgent"),
        migrations.DeleteModel(name="CollectedRaceTable"),
        migrations.DeleteModel(name="CollectedRace"),
        migrations.DeleteModel(name="ColdKey"),
    ]
