from django.db.models import Q

from .models import NguoiDung, ThongBao


def admin_recipients(branch=None, global_only=False):
    global_admins = Q(is_superuser=True) | Q(is_staff=True, chi_nhanh_quan_ly__isnull=True)
    scope = global_admins
    if branch is not None and not global_only:
        scope |= Q(chi_nhanh_quan_ly=branch) & (Q(role__in=['manager', 'staff']) | Q(is_staff=True))
    return NguoiDung.objects.filter(scope, is_active=True).distinct()


def notify_admins(*, title, message, category, link, branch=None, global_only=False):
    notifications = [
        ThongBao(
            nguoi_nhan=recipient,
            tieu_de=title,
            noi_dung=message,
            loai=category,
            duong_dan=link,
        )
        for recipient in admin_recipients(branch=branch, global_only=global_only)
    ]
    if notifications:
        ThongBao.objects.bulk_create(notifications)
    return len(notifications)
