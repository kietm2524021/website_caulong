import re
import unicodedata

from django.db import migrations
from django.db.models import Sum


def normalize_part(value):
    normalized = unicodedata.normalize(
        "NFD", str(value).replace("đ", "d").replace("Đ", "D")
    )
    without_accents = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^A-Za-z0-9]+", "", without_accents).upper()


def fix_group_transfer_content(apps, schema_editor):
    DatSan = apps.get_model("members", "DatSan")
    group_ids = (
        DatSan.objects.filter(loaiDatSan=1, nhom_dat_san__isnull=False)
        .values_list("nhom_dat_san", flat=True)
        .distinct()
    )
    for group_id in group_ids.iterator():
        group = DatSan.objects.filter(nhom_dat_san=group_id)
        first = group.select_related("san", "nguoi_dat").order_by("ngayBatDau", "id").first()
        if not first:
            continue
        total_deposit = group.aggregate(total=Sum("so_tien_coc"))["total"] or 0
        customer_name = first.tenNguoiDat or getattr(first.nguoi_dat, "ten", "KHACH")
        parts = (
            "DATCOC",
            customer_name,
            first.san.tenSan,
            first.ngayBatDau.strftime("%d%m%y"),
            int(total_deposit),
        )
        group.update(noi_dung_chuyen_khoan="-".join(normalize_part(part) for part in parts))


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0022_correct_fixed_booking_prices"),
    ]

    operations = [
        migrations.RunPython(fix_group_transfer_content, migrations.RunPython.noop),
    ]
