from django.db import OperationalError, ProgrammingError

from .models import CauHinhHeThong, ThongBao


class DefaultSiteConfig:
    ten_website = "Cầu Lông Bạc Liêu"
    slogan = "Đặt sân nhanh, chơi cầu vui."
    mo_ta_trang_chu = (
        "Nền tảng đặt sân cầu lông tại Bạc Liêu, giúp khách hàng theo dõi lịch sân "
        "và kết nối với quản lý dễ dàng."
    )
    footer_dia_chi = "Bạc Liêu, Việt Nam"
    footer_hotline = "Đang cập nhật"
    footer_email = ""
    footer_ghi_chu = "Hệ thống hỗ trợ đặt sân, quản lý lịch và chăm sóc khách hàng."


def site_config(request):
    try:
        config = CauHinhHeThong.load()
    except (OperationalError, ProgrammingError):
        config = DefaultSiteConfig()
    context = {"site_config": config}
    user = getattr(request, "user", None)
    if user and user.is_authenticated and (
        user.is_superuser or user.is_staff or user.role in {"manager", "staff"}
    ):
        notifications = ThongBao.objects.filter(nguoi_nhan=user)
        context.update({
            "admin_notifications": notifications[:10],
            "admin_unread_notifications": notifications.filter(is_read=False).count(),
        })
    return context
