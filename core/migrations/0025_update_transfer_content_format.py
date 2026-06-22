import re
import unicodedata

from django.db import migrations


def normalize_part(value):
    normalized = unicodedata.normalize(
        "NFD", str(value).replace("đ", "d").replace("Đ", "D")
    )
    without_accents = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^A-Za-z0-9]+", "", without_accents).upper()


def abbreviate_branch(value):
    normalized = unicodedata.normalize(
        "NFD", str(value).replace("đ", "d").replace("Đ", "D")
    )
    without_accents = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    tokens = re.findall(r"[A-Za-z]+|\d+", without_accents.upper())
    return "".join(token if token.isdigit() else token[0] for token in tokens) or "CN"


def transfer_content(booking):
    customer_name = booking.tenNguoiDat or getattr(booking.nguoi_dat, "ten", "KHACH")
    return "_".join(
        (
            normalize_part(customer_name),
            abbreviate_branch(booking.san.maChiNhanh.tenChiNhanh),
            normalize_part(booking.san.tenSan),
            booking.gioBatDau.strftime("%H%M"),
            booking.ngayBatDau.strftime("%d%m%y"),
        )
    )


def update_transfer_content(apps, schema_editor):
    DatSan = apps.get_model("members", "DatSan")
    related = ("san__maChiNhanh", "nguoi_dat")

    group_ids = (
        DatSan.objects.filter(nhom_dat_san__isnull=False)
        .values_list("nhom_dat_san", flat=True)
        .distinct()
    )
    for group_id in group_ids.iterator():
        group = DatSan.objects.filter(nhom_dat_san=group_id)
        first = group.select_related(*related).order_by(
            "ngayBatDau", "gioBatDau", "id"
        ).first()
        if first:
            group.update(noi_dung_chuyen_khoan=transfer_content(first))

    individual_bookings = DatSan.objects.filter(
        nhom_dat_san__isnull=True
    ).select_related(*related)
    for booking in individual_bookings.iterator():
        DatSan.objects.filter(pk=booking.pk).update(
            noi_dung_chuyen_khoan=transfer_content(booking)
        )


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0024_restore_fixed_booking_totals"),
    ]

    operations = [
        migrations.RunPython(update_transfer_content, migrations.RunPython.noop),
    ]
