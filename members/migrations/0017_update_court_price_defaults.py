from decimal import Decimal

from django.db import migrations, models


def update_existing_court_prices(apps, schema_editor):
    SanCauLong = apps.get_model("members", "SanCauLong")
    SanCauLong.objects.all().update(
        gia_vang=Decimal("50000"),
        gia_thuong=Decimal("80000"),
        gia_co_dinh=Decimal("40000"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0016_cauhinhhethong"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sancaulong",
            name="gia_vang",
            field=models.DecimalField(
                decimal_places=0,
                default=50000,
                help_text="Áp dụng cho khách vãng lai trước 17h",
                max_digits=10,
                verbose_name="Giá giờ VÀNG",
            ),
        ),
        migrations.AlterField(
            model_name="sancaulong",
            name="gia_thuong",
            field=models.DecimalField(
                decimal_places=0,
                default=80000,
                help_text="Áp dụng cho khách vãng lai từ 17h trở đi",
                max_digits=10,
                verbose_name="Giá giờ THƯỜNG",
            ),
        ),
        migrations.AlterField(
            model_name="sancaulong",
            name="gia_co_dinh",
            field=models.DecimalField(
                decimal_places=0,
                default=40000,
                help_text="Giá ưu đãi dành cho khách đặt lịch cố định/tháng",
                max_digits=10,
                verbose_name="Giá CỐ ĐỊNH",
            ),
        ),
        migrations.RunPython(update_existing_court_prices, migrations.RunPython.noop),
    ]
