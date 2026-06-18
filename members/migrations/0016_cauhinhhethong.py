# Generated manually for editable site branding/footer settings.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0015_hotro_nguoi_gui"),
    ]

    operations = [
        migrations.CreateModel(
            name="CauHinhHeThong",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ten_website", models.CharField(default="Cầu Lông Bạc Liêu", max_length=120, verbose_name="Tên website")),
                ("slogan", models.CharField(default="Đặt sân nhanh, chơi cầu vui.", max_length=255, verbose_name="Slogan")),
                (
                    "mo_ta_trang_chu",
                    models.TextField(
                        default="Nền tảng đặt sân cầu lông tại Bạc Liêu, giúp khách hàng theo dõi lịch sân và kết nối với quản lý dễ dàng.",
                        verbose_name="Mô tả trang chủ",
                    ),
                ),
                ("footer_dia_chi", models.CharField(default="Bạc Liêu, Việt Nam", max_length=255, verbose_name="Địa chỉ footer")),
                ("footer_hotline", models.CharField(default="Đang cập nhật", max_length=30, verbose_name="Hotline footer")),
                ("footer_email", models.EmailField(blank=True, default="", max_length=254, verbose_name="Email footer")),
                (
                    "footer_ghi_chu",
                    models.CharField(
                        default="Hệ thống hỗ trợ đặt sân, quản lý lịch và chăm sóc khách hàng.",
                        max_length=255,
                        verbose_name="Ghi chú footer",
                    ),
                ),
                ("cap_nhat_luc", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Cấu hình hệ thống",
                "verbose_name_plural": "Cấu hình hệ thống",
            },
        ),
    ]
