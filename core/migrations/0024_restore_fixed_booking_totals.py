from decimal import Decimal

from django.db import migrations


def restore_fixed_booking_totals(apps, schema_editor):
    DatSan = apps.get_model("members", "DatSan")
    bookings = DatSan.objects.filter(loaiDatSan=1).select_related("san")
    updates = []
    for booking in bookings.iterator():
        start_seconds = booking.gioBatDau.hour * 3600 + booking.gioBatDau.minute * 60
        end_seconds = booking.gioKetThuc.hour * 3600 + booking.gioKetThuc.minute * 60
        duration = Decimal(end_seconds - start_seconds) / Decimal("3600")
        booking.tongGiaTien = (duration * booking.san.gia_co_dinh).quantize(Decimal("1"))
        updates.append(booking)
    if updates:
        DatSan.objects.bulk_update(updates, ["tongGiaTien"])


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0023_fix_group_transfer_content"),
    ]

    operations = [
        migrations.RunPython(restore_fixed_booking_totals, migrations.RunPython.noop),
    ]
