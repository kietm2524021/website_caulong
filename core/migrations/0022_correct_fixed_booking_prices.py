from decimal import Decimal

from django.db import migrations


def correct_fixed_booking_prices(apps, schema_editor):
    DatSan = apps.get_model("members", "DatSan")
    DatSan.objects.filter(loaiDatSan=1).exclude(tongGiaTien=Decimal("10000")).update(
        tongGiaTien=Decimal("10000")
    )


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0021_add_time_to_transfer_content"),
    ]

    operations = [
        migrations.RunPython(correct_fixed_booking_prices, migrations.RunPython.noop),
    ]
