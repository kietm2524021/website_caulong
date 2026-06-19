import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from core.models import ChiNhanh, SanCauLong


BRANCHES = (
    {
        "name": "Lê Giang 1",
        "address": "Lê Giang 1, Bạc Liêu",
        "address_env": "LE_GIANG_1_ADDRESS",
        "phone_env": "LE_GIANG_1_PHONE",
    },
    {
        "name": "Lê Giang 2",
        "address": "Lê Giang 2, Bạc Liêu",
        "address_env": "LE_GIANG_2_ADDRESS",
        "phone_env": "LE_GIANG_2_PHONE",
    },
)


def env_enabled(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


class Command(BaseCommand):
    help = "Tạo dữ liệu mặc định khi deploy mà không tạo bản ghi trùng."

    @transaction.atomic
    def handle(self, *args, **options):
        admin_name = os.getenv("DEFAULT_ADMIN_NAME", "Quản trị viên").strip()
        admin_phone = (
            os.getenv("DEFAULT_ADMIN_PHONE")
            or os.getenv("DJANGO_SUPERUSER_USERNAME")
            or ""
        ).strip()

        if env_enabled("CREATE_SUPERUSER"):
            self.seed_admin(admin_name, admin_phone)
        else:
            self.stdout.write(self.style.WARNING("Bỏ qua admin vì CREATE_SUPERUSER chưa được bật."))

        branch_phone = admin_phone or "0000000000"
        created_branches = 0
        created_courts = 0
        for definition in BRANCHES:
            branch, branch_created = ChiNhanh.objects.get_or_create(
                tenChiNhanh=definition["name"],
                defaults={
                    "diaChi": os.getenv(definition["address_env"], definition["address"]),
                    "sdt": os.getenv(definition["phone_env"], branch_phone),
                    "tenQuanLy": admin_name,
                },
            )
            created_branches += int(branch_created)
            for number in range(1, 8):
                _, court_created = SanCauLong.objects.get_or_create(
                    maChiNhanh=branch,
                    tenSan=f"Sân {number}",
                )
                created_courts += int(court_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed hoàn tất: thêm {created_branches} chi nhánh và {created_courts} sân."
            )
        )

    def seed_admin(self, admin_name, admin_phone):
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "").strip()
        if not admin_phone or not password:
            raise CommandError(
                "CREATE_SUPERUSER đã bật nhưng thiếu DEFAULT_ADMIN_PHONE "
                "(hoặc DJANGO_SUPERUSER_USERNAME) / DJANGO_SUPERUSER_PASSWORD."
            )

        User = get_user_model()
        matches = list(
            User.objects.filter(Q(sodienthoai=admin_phone) | Q(username=admin_phone)).distinct()
        )
        if len(matches) > 1:
            raise CommandError("Số điện thoại admin đang thuộc nhiều tài khoản khác nhau.")

        if matches:
            user = matches[0]
            changed_fields = []
            desired_values = {
                "username": admin_phone,
                "sodienthoai": admin_phone,
                "ten": admin_name,
                "email": email,
                "role": "manager",
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            }
            for field, value in desired_values.items():
                if getattr(user, field) != value:
                    setattr(user, field, value)
                    changed_fields.append(field)
            if changed_fields:
                user.save(update_fields=changed_fields)
            self.stdout.write("Admin đã tồn tại; giữ nguyên mật khẩu hiện tại.")
            return

        User.objects.create_superuser(
            username=admin_phone,
            sodienthoai=admin_phone,
            ten=admin_name,
            email=email,
            password=password,
            role="manager",
        )
        self.stdout.write(self.style.SUCCESS(f"Đã tạo admin {admin_phone}."))
