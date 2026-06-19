from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0014_datsan_khach_xac_nhan_chuyen_khoan_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="hotro",
            name="nguoi_gui",
            field=models.CharField(
                choices=[("customer", "Khach hang"), ("admin", "Admin")],
                default="customer",
                max_length=20,
                verbose_name="Nguoi gui",
            ),
        ),
    ]
