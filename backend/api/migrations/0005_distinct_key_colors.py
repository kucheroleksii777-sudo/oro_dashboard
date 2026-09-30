from django.db import migrations

KEY_COLORS = (
    "#4ea1ff",
    "#3ecf8e",
    "#e89b25",
    "#f5d76e",
    "#e85d75",
    "#b57bff",
    "#2ec4d6",
    "#ff7eb6",
    "#9ad1ff",
    "#7ee081",
    "#ff9f68",
    "#c9a0dc",
)


def _next_color(used: set[str]) -> str:
    for color in KEY_COLORS:
        if color not in used:
            return color
    hue = (len(used) * 47) % 360
    sat = 0.68
    light = 0.58
    a = sat * min(light, 1 - light)

    def channel(n: float) -> str:
        k = (n + hue / 30) % 12
        value = light - a * max(min(k - 3, 9 - k, 1), -1)
        return f"{round(255 * value):02x}"

    return f"#{channel(0)}{channel(8)}{channel(4)}"


def assign_distinct_colors(apps, _schema_editor):
    ColdKey = apps.get_model("api", "ColdKey")
    used: set[str] = set()
    for item in ColdKey.objects.order_by("created_at", "id"):
        color = (item.color or "").strip().lower()
        if not color or color in used:
            color = _next_color(used)
            item.color = color
            item.save(update_fields=["color"])
        used.add(color)


def noop(_apps, _schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0004_coldkey_color"),
    ]

    operations = [
        migrations.RunPython(assign_distinct_colors, noop),
    ]
