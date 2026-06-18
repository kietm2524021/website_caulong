# create_admin.py
import os
import django


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_badminton.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

if os.getenv("CREATE_SUPERUSER", "").lower() not in {"1", "true", "yes"}:
    print("ℹ️ CREATE_SUPERUSER != 1 → bỏ qua tạo admin.")
    exit(0)


username = os.getenv('DJANGO_SUPERUSER_USERNAME')
email = os.getenv('DJANGO_SUPERUSER_EMAIL', '')
password = os.getenv('DJANGO_SUPERUSER_PASSWORD')

if not username or not password:
    print("❌ Thiếu DJANGO_SUPERUSER_USERNAME hoặc DJANGO_SUPERUSER_PASSWORD")
    exit(0)


if (
    User.objects.filter(username=username).exists()
    or User.objects.filter(sodienthoai=username).exists()
):
    print("ℹ️ Superuser đã tồn tại → bỏ qua.")
else:
    print(f"🚀 Đang tạo superuser: {username}")
    User.objects.create_superuser(
        username=username,
        email=email,
        password=password,
        sodienthoai=username
    )
    print("✅ Tạo superuser thành công!")
