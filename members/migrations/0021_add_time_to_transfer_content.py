import re
import unicodedata

from django.db import migrations


def add_time_to_transfer_content(apps, schema_editor):
    DatSan = apps.get_model('members', 'DatSan')
    bookings = list(DatSan.objects.select_related('san', 'nguoi_dat').all())
    for booking in bookings:
        phone = booking.sdt or getattr(booking.nguoi_dat, 'sodienthoai', '')
        raw = f"DAT COC {phone} {booking.ngayBatDau:%d%m%Y} {booking.gioBatDau:%H%M} {booking.san.tenSan}"
        normalized = unicodedata.normalize('NFD', raw.replace('đ', 'd').replace('Đ', 'D'))
        without_accents = ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')
        booking.noi_dung_chuyen_khoan = re.sub(r'[^A-Za-z0-9]+', ' ', without_accents).strip().upper()
    if bookings:
        DatSan.objects.bulk_update(bookings, ['noi_dung_chuyen_khoan'])


class Migration(migrations.Migration):
    dependencies = [('members', '0020_normalize_transfer_content')]

    operations = [migrations.RunPython(add_time_to_transfer_content, migrations.RunPython.noop)]
