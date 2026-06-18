from decimal import Decimal, InvalidOperation
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Max, Prefetch, Q, Sum
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import BaiDang, ChiNhanh, DatSan, HoiThoaiKhachHang, HoTro, NguoiDung, SanCauLong, ThongBao
from .security import normalize_plain_text, validate_uploaded_file
from .support_chat import create_admin_message, serialize_conversation, serialize_message


ADMIN_ROLES = {"staff", "manager"}


def can_use_console(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser or user.role in ADMIN_ROLES)


def has_global_scope(user):
    return user.is_superuser or (user.is_staff and not user.chi_nhanh_quan_ly)


def can_manage_user_accounts(user):
    return has_global_scope(user)


def console_required(view_func):
    @login_required(login_url="login")
    def wrapper(request, *args, **kwargs):
        if not can_use_console(request.user):
            return HttpResponseForbidden("Bạn không có quyền truy cập trang quản trị.")
        return view_func(request, *args, **kwargs)

    return wrapper


def managed_branch(request):
    if has_global_scope(request.user):
        return None
    return request.user.chi_nhanh_quan_ly


def branch_queryset(request):
    qs = ChiNhanh.objects.all().order_by("tenChiNhanh")
    branch = managed_branch(request)
    if branch:
        return qs.filter(id=branch.id)
    return qs if has_global_scope(request.user) else qs.none()


def court_queryset(request):
    qs = SanCauLong.objects.select_related("maChiNhanh").order_by("maChiNhanh__tenChiNhanh", "tenSan")
    branch = managed_branch(request)
    if branch:
        return qs.filter(maChiNhanh=branch)
    return qs if has_global_scope(request.user) else qs.none()


def booking_queryset(request):
    qs = DatSan.objects.select_related("nguoi_dat", "san", "san__maChiNhanh", "nguoi_duyet")
    branch = managed_branch(request)
    if branch:
        return qs.filter(san__maChiNhanh=branch)
    return qs if has_global_scope(request.user) else qs.none()


def conversation_queryset(request):
    qs = HoiThoaiKhachHang.objects.select_related("nguoi_dung", "chi_nhanh", "admin_phu_trach").prefetch_related(
        Prefetch("hotro_set", queryset=HoTro.objects.order_by("ngay_gui", "id"))
    )
    branch = managed_branch(request)
    if branch:
        qs = qs.filter(chi_nhanh=branch).filter(
            Q(admin_phu_trach__isnull=True) | Q(admin_phu_trach=request.user)
        ).distinct()
    elif not has_global_scope(request.user):
        qs = qs.none()
    return qs


def apply_admin_reply(conversation, admin_user, reply):
    if not conversation.admin_phu_trach:
        conversation.admin_phu_trach = admin_user
        conversation.can_admin = True
        conversation.save(update_fields=["admin_phu_trach", "can_admin"])

    pending_customer_message = (
        conversation.hotro_set.filter(nguoi_gui="customer", tra_loi__isnull=True)
        .order_by("-ngay_gui", "-id")
        .first()
    )
    if pending_customer_message:
        pending_customer_message.tra_loi = reply
        pending_customer_message.nguon_tra_loi = "admin"
        pending_customer_message.admin_tra_loi = admin_user
        pending_customer_message.ngay_tra_loi = timezone.now()
        pending_customer_message.da_xem = True
        pending_customer_message.save(
            update_fields=["tra_loi", "nguon_tra_loi", "admin_tra_loi", "ngay_tra_loi", "da_xem"]
        )
        return pending_customer_message
    return create_admin_message(conversation, admin_user, reply)


def paginate(request, queryset, per_page=20):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def prepare_booking_row(booking, group_items=None):
    items = list(group_items or [booking])
    booking.admin_is_group = len(items) > 1 or booking.loaiDatSan == 1
    booking.admin_group_count = len(items)
    booking.admin_group_total = sum((item.tongGiaTien or Decimal("0")) for item in items)
    booking.admin_group_deposit = sum((item.so_tien_coc or Decimal("0")) for item in items)
    booking.admin_group_first_date = items[0].ngayBatDau if items else booking.ngayBatDau
    booking.admin_group_last_date = items[-1].ngayBatDau if items else booking.ngayBatDau
    if booking.trangThai == "cancelled":
        booking.admin_flow_state = "cancelled"
        booking.admin_flow_label = "Đã hủy"
    elif booking.trangThai in {"confirmed", "completed"}:
        booking.admin_flow_state = "approved"
        booking.admin_flow_label = "Đã duyệt"
    elif booking.khach_xac_nhan_chuyen_khoan:
        booking.admin_flow_state = "deposited"
        booking.admin_flow_label = "Khách đã báo chuyển cọc"
    elif booking.yeu_cau_thanh_toan:
        booking.admin_flow_state = "waiting"
        booking.admin_flow_label = "Chờ khách đặt cọc"
    else:
        booking.admin_flow_state = "new"
        booking.admin_flow_label = "Yêu cầu mới - chưa cọc"
    return booking


def grouped_booking_rows(qs):
    rows = []
    seen_groups = set()
    for booking in qs:
        if booking.loaiDatSan == 1 and booking.nhom_dat_san:
            group_key = str(booking.nhom_dat_san)
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
            group_items = list(
                DatSan.objects.filter(nhom_dat_san=booking.nhom_dat_san)
                .select_related("nguoi_dat", "san", "san__maChiNhanh", "nguoi_duyet")
                .order_by("ngayBatDau", "gioBatDau", "id")
            )
            representative = group_items[0] if group_items else booking
            rows.append(prepare_booking_row(representative, group_items))
            continue
        rows.append(prepare_booking_row(booking))
    return rows


def apply_booking_filters(request, qs):
    status = request.GET.get("status", "")
    pay = request.GET.get("pay", "")
    branch_id = request.GET.get("branch", "")
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")
    query = request.GET.get("q", "").strip()

    if status:
        qs = qs.filter(trangThai=status)
    if pay == "paid":
        qs = qs.filter(daThanhToan=True)
    elif pay == "unpaid":
        qs = qs.filter(daThanhToan=False)
    if branch_id.isdigit() and not managed_branch(request):
        qs = qs.filter(san__maChiNhanh_id=int(branch_id))
    if date_from:
        qs = qs.filter(ngayBatDau__gte=date_from)
    if date_to:
        qs = qs.filter(ngayBatDau__lte=date_to)
    if query:
        qs = qs.filter(
            Q(tenNguoiDat__icontains=query)
            | Q(sdt__icontains=query)
            | Q(san__tenSan__icontains=query)
            | Q(noi_dung_chuyen_khoan__icontains=query)
        )
    return qs


def action_target_for_booking(booking):
    if booking.loaiDatSan == 1 and booking.nhom_dat_san:
        return DatSan.objects.filter(nhom_dat_san=booking.nhom_dat_san)
    return DatSan.objects.filter(id=booking.id)


def action_key_for_booking(booking):
    if booking.loaiDatSan == 1 and booking.nhom_dat_san:
        return ("group", str(booking.nhom_dat_san))
    return ("single", booking.id)


def perform_booking_action(request, booking, action):
    target = action_target_for_booking(booking)
    now = timezone.now()
    if action == "confirm":
        return "Không thể duyệt trực tiếp. Hãy gửi yêu cầu đặt cọc và xác nhận sau khi khách đã chuyển khoản."
    if action == "request_payment":
        if booking.trangThai != "pending":
            return "Chỉ có thể gửi yêu cầu đặt cọc cho đơn đang chờ xử lý."
        for item in target:
            item.so_tien_coc = item.tinh_tien_coc_mac_dinh()
            item.yeu_cau_thanh_toan = True
            item.ngay_gui_yeu_cau_thanh_toan = now
            item.ngay_khach_mo_thanh_toan = None
            item.khach_xac_nhan_chuyen_khoan = False
            item.ngay_khach_xac_nhan_ck = None
            item.daThanhToan = False
            item.nguoi_duyet = request.user
            item.save(update_fields=[
                "so_tien_coc", "yeu_cau_thanh_toan", "ngay_gui_yeu_cau_thanh_toan", "ngay_khach_mo_thanh_toan",
                "khach_xac_nhan_chuyen_khoan", "ngay_khach_xac_nhan_ck", "daThanhToan",
                "nguoi_duyet", "noi_dung_chuyen_khoan",
            ])
        ThongBao.objects.create(
            nguoi_nhan=booking.nguoi_dat,
            tieu_de="Quản lý đã gửi yêu cầu đặt cọc",
            noi_dung=f"Vui lòng mở thông tin đặt cọc cho sân {booking.san.tenSan} ngày {booking.ngayBatDau:%d/%m/%Y}. Thời gian 15 phút bắt đầu khi bạn mở yêu cầu.",
            loai="payment",
            duong_dan=reverse("lich_su_dat_san"),
        )
        return "Đã gửi yêu cầu đặt cọc. Đồng hồ 15 phút bắt đầu khi khách mở thông tin giao dịch."
    if action == "cancel":
        reason = (request.POST.get("ly_do_huy") or "").strip()
        if not reason:
            return "Vui lòng nhập lý do hủy đơn."
        target.update(
            trangThai="cancelled",
            nguoi_duyet=request.user,
            yeu_cau_thanh_toan=False,
            ngay_khach_mo_thanh_toan=None,
            khach_xac_nhan_chuyen_khoan=False,
            ly_do_huy=reason[:500],
        )
        ThongBao.objects.create(
            nguoi_nhan=booking.nguoi_dat,
            tieu_de="Đơn đặt sân đã bị hủy",
            noi_dung=f"Yêu cầu đặt sân {booking.san.tenSan} ngày {booking.ngayBatDau:%d/%m/%Y} đã bị hủy. Lý do: {reason[:500]}",
            loai="booking",
            duong_dan=reverse("lich_su_dat_san"),
        )
        return "Đã hủy đơn đặt sân."
    if action == "complete":
        target.update(trangThai="completed", nguoi_duyet=request.user)
        return "Đã đánh dấu hoàn thành."
    if action == "mark_transfer_received":
        if not booking.yeu_cau_thanh_toan or not booking.khach_xac_nhan_chuyen_khoan:
            return "Khách hàng chưa xác nhận đã chuyển khoản."
        target.update(daThanhToan=True, trangThai="confirmed", nguoi_duyet=request.user)
        ThongBao.objects.create(
            nguoi_nhan=booking.nguoi_dat,
            tieu_de="Quản lý đã xác nhận tiền cọc",
            noi_dung=f"Khoản cọc của đơn sân {booking.san.tenSan} ngày {booking.ngayBatDau:%d/%m/%Y} đã được xác nhận. Đơn đặt sân đã được duyệt.",
            loai="payment",
            duong_dan=reverse("lich_su_dat_san"),
        )
        return "Đã xác nhận tiền cọc và duyệt đơn."
    if action == "delete":
        if booking.trangThai == "cancelled":
            return "Đơn đã hủy phải được giữ lại trong lịch sử."
        target.delete()
        return "Đã xóa đơn đặt sân khỏi hệ thống."
    return "Hành động không hợp lệ."


@console_required
def admin_dashboard(request):
    today = timezone.localdate()
    start_month = today.replace(day=1)
    bookings = booking_queryset(request)
    conversations = conversation_queryset(request)
    branch = managed_branch(request)
    customer_qs = NguoiDung.objects.filter(role="customer")
    if branch and not has_global_scope(request.user):
        customer_ids = bookings.values_list("nguoi_dat_id", flat=True)
        customer_qs = customer_qs.filter(id__in=customer_ids).distinct()

    stats = {
        "today_bookings": bookings.filter(ngayBatDau=today).count(),
        "pending_bookings": len(
            grouped_booking_rows(bookings.filter(trangThai="pending").order_by("-ngayBatDau", "-gioBatDau", "-ngay_tao"))
        ),
        "unpaid_bookings": len(
            grouped_booking_rows(
                bookings.filter(daThanhToan=False, trangThai__in=["pending", "confirmed"]).order_by(
                    "-ngayBatDau", "-gioBatDau", "-ngay_tao"
                )
            )
        ),
        "month_revenue": bookings.filter(
            ngayBatDau__gte=start_month,
            daThanhToan=True,
            trangThai__in=["confirmed", "completed"],
        ).aggregate(total=Sum("tongGiaTien"))["total"] or 0,
        "active_courts": court_queryset(request).filter(is_active=True).count(),
        "pending_posts": BaiDang.objects.filter(duyet_bai=False).count() if has_global_scope(request.user) else 0,
        "unread_support": HoTro.objects.filter(hoi_thoai__in=conversations, da_xem=False).count(),
        "customers": customer_qs.count(),
    }

    today_schedule = bookings.filter(ngayBatDau=today).order_by("gioBatDau")[:12]
    recent_bookings = grouped_booking_rows(bookings.order_by("-ngay_tao", "-ngayBatDau", "-gioBatDau"))[:10]
    support_threads = conversations.annotate(last_message=Max("hotro_set__ngay_gui")).order_by("-last_message")[:8]

    return render(
        request,
        "admin_console/dashboard.html",
        {
            "active_nav": "dashboard",
            "stats": stats,
            "today_schedule": today_schedule,
            "recent_bookings": recent_bookings,
            "support_threads": support_threads,
        },
    )


@console_required
def admin_bookings(request):
    qs = apply_booking_filters(request, booking_queryset(request)).order_by("-ngayBatDau", "-gioBatDau", "-ngay_tao")
    rows = grouped_booking_rows(qs)
    return render(
        request,
        "admin_console/bookings.html",
        {
            "active_nav": "bookings",
            "bookings": paginate(request, rows, 25),
            "branches": branch_queryset(request),
            "status_choices": DatSan.TRANG_THAI_CHOICES,
        },
    )


@console_required
@require_POST
def admin_notification_open(request, notification_id):
    notification = get_object_or_404(ThongBao, id=notification_id, nguoi_nhan=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    target = notification.duong_dan or reverse("admin_dashboard")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = reverse("admin_dashboard")
    return redirect(target)


@console_required
@require_POST
def admin_notifications_read_all(request):
    ThongBao.objects.filter(nguoi_nhan=request.user, is_read=False).update(is_read=True)
    target = request.POST.get("next") or reverse("admin_dashboard")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = reverse("admin_dashboard")
    return redirect(target)


@console_required
@require_POST
def admin_booking_action(request, booking_id):
    booking = get_object_or_404(booking_queryset(request), id=booking_id)
    message = perform_booking_action(request, booking, request.POST.get("action", ""))
    messages.success(request, message)
    next_url = request.POST.get("next") or reverse("admin_bookings")
    return redirect(next_url)


@console_required
@require_POST
def admin_booking_bulk_action(request):
    action = request.POST.get("action", "")
    selected_ids = request.POST.getlist("booking_ids")
    next_url = request.POST.get("next") or reverse("admin_bookings")

    allowed_actions = {"request_payment", "mark_transfer_received", "cancel", "delete"}
    if action not in allowed_actions:
        messages.error(request, "Hành động hàng loạt không hợp lệ.")
        return redirect(next_url)
    if not selected_ids:
        messages.warning(request, "Bạn chưa chọn đơn nào.")
        return redirect(next_url)
    if action == "delete" and request.POST.get("delete_confirmed") != "yes":
        messages.warning(request, "Vui lòng xác nhận đủ hai bước trước khi xóa các đơn đã chọn.")
        return redirect(next_url)

    bookings = list(booking_queryset(request).filter(id__in=selected_ids).order_by("id"))
    if not bookings:
        messages.warning(request, "Không tìm thấy đơn hợp lệ trong phạm vi quản lý của bạn.")
        return redirect(next_url)

    if action == "cancel" and not (request.POST.get("ly_do_huy") or "").strip():
        messages.warning(request, "Vui lòng nhập lý do hủy các đơn đã chọn.")
        return redirect(next_url)

    processed = set()
    done = 0
    skipped = 0
    for booking in bookings:
        key = action_key_for_booking(booking)
        if key in processed:
            continue
        processed.add(key)
        if action == "request_payment" and (
            booking.trangThai != "pending" or booking.khach_xac_nhan_chuyen_khoan
        ):
            skipped += 1
            continue
        if action == "mark_transfer_received" and (
            booking.trangThai != "pending"
            or not booking.yeu_cau_thanh_toan
            or not booking.khach_xac_nhan_chuyen_khoan
        ):
            skipped += 1
            continue
        if action == "cancel" and booking.trangThai != "pending":
            skipped += 1
            continue
        if action == "delete":
            if booking.loaiDatSan == 1 and booking.nhom_dat_san:
                DatSan.objects.filter(nhom_dat_san=booking.nhom_dat_san).delete()
            else:
                booking.delete()
        else:
            perform_booking_action(request, booking, action)
        done += 1

    action_labels = {
        "request_payment": "gửi yêu cầu cọc cho",
        "mark_transfer_received": "xác nhận cọc và duyệt",
        "cancel": "hủy",
        "delete": "xóa",
    }
    message = f"Đã {action_labels[action]} {done} đơn/nhóm đơn."
    if skipped:
        message += f" Bỏ qua {skipped} đơn không phù hợp trạng thái."
    messages.success(request, message)
    return redirect(next_url)


@console_required
def admin_courts(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_court":
            court = get_object_or_404(court_queryset(request), id=request.POST.get("court_id"))
            try:
                court.gia_vang = Decimal(request.POST.get("gia_vang", court.gia_vang))
                court.gia_thuong = Decimal(request.POST.get("gia_thuong", court.gia_thuong))
                court.gia_co_dinh = Decimal(request.POST.get("gia_co_dinh", court.gia_co_dinh))
            except InvalidOperation:
                messages.error(request, "Giá sân không hợp lệ.")
                return redirect("admin_courts")
            court.is_active = request.POST.get("is_active") == "on"
            court.moTa = request.POST.get("moTa", "")
            court.save()
            messages.success(request, f"Đã cập nhật {court.tenSan}.")
        elif action == "update_branch":
            branch = get_object_or_404(branch_queryset(request), id=request.POST.get("branch_id"))
            branch.ten_ngan_hang = request.POST.get("ten_ngan_hang", "")
            branch.so_tai_khoan = request.POST.get("so_tai_khoan", "")
            branch.chu_tai_khoan = request.POST.get("chu_tai_khoan", "")
            try:
                if request.FILES.get("qr_thanh_toan"):
                    branch.qr_thanh_toan = validate_uploaded_file(
                        request.FILES["qr_thanh_toan"],
                        allowed_extensions={".jpg", ".jpeg", ".png", ".webp"},
                        allowed_content_types={"image/jpeg", "image/png", "image/webp"},
                        max_size=5 * 1024 * 1024,
                        field_label="Mã QR thanh toán",
                    )
            except ValidationError as exc:
                messages.error(request, exc.messages[0])
                return redirect("admin_courts")
            branch.save()
            messages.success(request, f"Đã cập nhật thông tin thanh toán cho {branch.tenChiNhanh}.")
        return redirect("admin_courts")

    branches = branch_queryset(request).prefetch_related(
        Prefetch("ds_san", queryset=court_queryset(request).order_by("tenSan"))
    )
    return render(request, "admin_console/courts.html", {"active_nav": "courts", "branches": branches})


@console_required
def admin_posts(request):
    if not has_global_scope(request.user):
        return HttpResponseForbidden("Chỉ quản trị toàn hệ thống được duyệt bài viết.")
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    qs = BaiDang.objects.select_related("nguoi_dang").order_by("-ngay_dang")
    if status == "pending":
        qs = qs.filter(duyet_bai=False)
    elif status == "approved":
        qs = qs.filter(duyet_bai=True)
    if query:
        qs = qs.filter(Q(tieu_de__icontains=query) | Q(noi_dung__icontains=query) | Q(nguoi_dang__ten__icontains=query))
    return render(request, "admin_console/posts.html", {"active_nav": "posts", "posts": paginate(request, qs, 20)})


@console_required
@require_POST
def admin_post_action(request, post_id):
    if not has_global_scope(request.user):
        return HttpResponseForbidden("Chỉ quản trị toàn hệ thống được duyệt bài viết.")
    post = get_object_or_404(BaiDang, id=post_id)
    action = request.POST.get("action")
    if action == "approve":
        post.duyet_bai = True
        post.save(update_fields=["duyet_bai"])
        messages.success(request, "Đã duyệt bài viết.")
    elif action == "hide":
        post.duyet_bai = False
        post.save(update_fields=["duyet_bai"])
        messages.success(request, "Đã ẩn bài viết.")
    elif action == "delete":
        post.delete()
        messages.success(request, "Đã xóa bài viết.")
    return redirect(request.POST.get("next") or "admin_posts")


@console_required
def admin_support(request, conversation_id=None):
    conversations = conversation_queryset(request).annotate(
        unread_count=Count("hotro_set", filter=Q(hotro_set__da_xem=False)),
        last_message=Max("hotro_set__ngay_gui"),
    ).order_by("-last_message", "-ngay_tao")

    active_conversation = None
    if conversation_id:
        active_conversation = get_object_or_404(conversation_queryset(request), id=conversation_id)
    else:
        active_conversation = conversations.first()

    if request.method == "POST":
        if not active_conversation:
            raise Http404("Hội thoại không tồn tại.")
        try:
            reply = normalize_plain_text(request.POST.get("tra_loi"), max_length=1000, field_label="Phản hồi")
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
            return redirect("admin_support_detail", conversation_id=active_conversation.id)
        apply_admin_reply(active_conversation, request.user, reply)
        messages.success(request, "Đã gửi phản hồi cho khách.")
        return redirect("admin_support_detail", conversation_id=active_conversation.id)

    return render(
        request,
        "admin_console/support.html",
        {
            "active_nav": "support",
            "conversations": conversations,
            "active_conversation": active_conversation,
        },
    )


@console_required
def admin_users(request):
    qs = NguoiDung.objects.select_related("chi_nhanh_quan_ly").prefetch_related("groups").order_by("-date_joined")
    branch = managed_branch(request)
    if branch and not has_global_scope(request.user):
        branch_customer_ids = DatSan.objects.filter(san__maChiNhanh=branch).values_list("nguoi_dat_id", flat=True)
        qs = qs.filter(Q(id__in=branch_customer_ids) | Q(chi_nhanh_quan_ly=branch)).distinct()
    query = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    if query:
        qs = qs.filter(Q(ten__icontains=query) | Q(sodienthoai__icontains=query) | Q(username__icontains=query))
    if role:
        qs = qs.filter(role=role)
    return render(
        request,
        "admin_console/users.html",
        {
            "active_nav": "users",
            "users": paginate(request, qs, 25),
            "branches": branch_queryset(request),
            "groups": Group.objects.all().order_by("name"),
            "role_choices": NguoiDung.VAI_TRO_CHOICES,
            "can_manage_users": can_manage_user_accounts(request.user),
        },
    )


@console_required
@require_POST
def admin_user_update(request, user_id):
    if not can_manage_user_accounts(request.user):
        return HttpResponseForbidden("Quản lý chi nhánh chỉ được xem người dùng, không được sửa phân quyền.")
    target = get_object_or_404(NguoiDung, id=user_id)
    if request.POST.get("delete_user") == "1":
        if target == request.user:
            messages.error(request, "Không thể xóa chính tài khoản đang đăng nhập.")
            return redirect(request.POST.get("next") or "admin_users")
        if target.is_superuser and not request.user.is_superuser:
            return HttpResponseForbidden("Bạn không thể xóa tài khoản superuser.")
        target.delete()
        messages.success(request, "Đã xóa tài khoản.")
        return redirect(request.POST.get("next") or "admin_users")
    if target.is_superuser and not request.user.is_superuser:
        return HttpResponseForbidden("Bạn không thể sửa tài khoản superuser.")

    target.role = request.POST.get("role", target.role)
    target.is_active = request.POST.get("is_active") == "on"
    if request.user.is_superuser:
        target.is_staff = request.POST.get("is_staff") == "on"
    branch_id = request.POST.get("chi_nhanh_quan_ly")
    target.chi_nhanh_quan_ly = branch_queryset(request).filter(id=branch_id).first() if branch_id else None
    if request.user.is_superuser:
        target.groups.set(Group.objects.filter(id__in=request.POST.getlist("groups")))
    new_password = request.POST.get("new_password", "").strip()
    if new_password:
        target.set_password(new_password)
    target.save()
    messages.success(request, f"Đã cập nhật quyền cho {target.ten}.")
    return redirect(request.POST.get("next") or "admin_users")


@console_required
def admin_support_widget_state(request):
    conversations = conversation_queryset(request).filter(can_admin=True).annotate(
        unread_count=Count("hotro_set", filter=Q(hotro_set__da_xem=False)),
        last_message=Max("hotro_set__ngay_gui"),
    ).order_by("-unread_count", "-last_message", "-last_admin_request_at")

    active_id = request.GET.get("conversation_id")
    active_conversation = None
    if active_id:
        active_conversation = conversations.filter(id=active_id).first()
    if not active_conversation:
        active_conversation = conversations.first()

    messages_data = []
    active_data = None
    if active_conversation:
        active_data = serialize_conversation(active_conversation)
        messages_data = [serialize_message(item) for item in active_conversation.hotro_set.order_by("ngay_gui", "id")]

    return JsonResponse(
        {
            "unread_count": HoTro.objects.filter(hoi_thoai__in=conversations, da_xem=False).count(),
            "conversations": [serialize_conversation(item) for item in conversations[:20]],
            "active_conversation": active_data,
            "messages": messages_data,
        }
    )


@console_required
@require_POST
def admin_support_widget_reply(request):
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else request.POST
    except json.JSONDecodeError:
        return JsonResponse({"error": "Dữ liệu gửi không hợp lệ."}, status=400)

    conversation = get_object_or_404(conversation_queryset(request), id=payload.get("conversation_id"))
    try:
        reply = normalize_plain_text(payload.get("reply"), max_length=1000, field_label="Phản hồi")
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)

    if not conversation.hotro_set.exists():
        return JsonResponse({"error": "Hội thoại chưa có tin nhắn."}, status=400)

    apply_admin_reply(conversation, request.user, reply)
    return JsonResponse({"ok": True})


@console_required
@require_POST
def admin_support_widget_leave(request):
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else request.POST
    except json.JSONDecodeError:
        return JsonResponse({"error": "Dữ liệu gửi không hợp lệ."}, status=400)

    conversation = get_object_or_404(conversation_queryset(request), id=payload.get("conversation_id"))
    conversation.admin_phu_trach = None
    conversation.can_admin = True
    conversation.last_admin_request_at = timezone.now()
    conversation.save(update_fields=["admin_phu_trach", "can_admin", "last_admin_request_at"])
    return JsonResponse({"ok": True})


@console_required
@require_POST
def admin_support_widget_delete(request):
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else request.POST
    except json.JSONDecodeError:
        return JsonResponse({"error": "Dữ liệu gửi không hợp lệ."}, status=400)

    conversation = get_object_or_404(conversation_queryset(request), id=payload.get("conversation_id"))
    conversation.delete()
    return JsonResponse({"ok": True})
