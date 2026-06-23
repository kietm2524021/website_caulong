import re
from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from .models import BaiDang, ChiNhanh, DatSan, HoiThoaiKhachHang, HoTro, NguoiDung, SanCauLong
from .notifications import notify_admins
from .support_ai import tao_phan_hoi_ho_tro, normalize_text, wants_admin_reply


OPEN_TIME = time(7, 0)
CLOSE_TIME = time(23, 0)


def format_time(value):
    return value.strftime("%H:%M")


def date_label(target_date):
    today = timezone.localdate()
    if target_date == today:
        return "hôm nay"
    if target_date == today + timedelta(days=1):
        return "ngày mai"
    return f"ngày {target_date:%d/%m/%Y}"


def target_dates_from_message(message):
    normalized = normalize_text(message)
    today = timezone.localdate()
    if "tuan nay" in normalized or "trong tuan" in normalized:
        end_of_week = today + timedelta(days=(6 - today.weekday()))
        return [today + timedelta(days=offset) for offset in range((end_of_week - today).days + 1)]
    if "cuoi tuan" in normalized or "thu 7" in normalized or "chu nhat" in normalized or "cn" in normalized.split():
        days_until_saturday = (5 - today.weekday()) % 7
        saturday = today + timedelta(days=days_until_saturday)
        return [saturday, saturday + timedelta(days=1)]
    return [target_date_from_message(message)]


def extract_time_request(message):
    normalized = normalize_text(message)
    time_pattern = r"(\d{1,2})(?:h|:00)?"
    after_match = re.search(rf"(?:sau|sau luc)\s*{time_pattern}", normalized)
    if after_match:
        start_hour = int(after_match.group(1))
        if 0 <= start_hour < 24:
            return time(start_hour, 0), CLOSE_TIME, False

    range_match = re.search(
        rf"{time_pattern}\s*(?:den|toi|-)\s*{time_pattern}",
        normalized,
    )
    if range_match:
        start_hour = int(range_match.group(1))
        end_hour = int(range_match.group(2))
        if 0 <= start_hour < 24 and 0 < end_hour <= 24 and start_hour < end_hour:
            return time(start_hour, 0), time(end_hour, 0), False

    single_match = re.search(rf"(?:luc|vao luc|dang luc)\s*{time_pattern}", normalized)
    if not single_match:
        single_match = re.search(rf"\b{time_pattern}\b", normalized) if "luc" in normalized else None
    if single_match:
        hour = int(single_match.group(1))
        if 0 <= hour < 24:
            return time(hour, 0), None, True

    if "sang" in normalized or "buoi sang" in normalized:
        return time(7, 0), time(12, 0), False
    if "trua" in normalized or "buoi trua" in normalized:
        return time(11, 0), time(14, 0), False
    if "chieu" in normalized or "buoi chieu" in normalized:
        return time(13, 0), time(17, 0), False
    if "toi nay" in normalized or "toi mai" in normalized or "buoi toi" in normalized:
        return time(18, 0), time(22, 0), False

    return None, None, False


def court_number_from_message(message):
    normalized = normalize_text(message)
    match = re.search(r"san\s*(?:so\s*)?(\d+)", normalized)
    return match.group(1) if match else None


def filter_courts_by_number(queryset, number):
    if not number:
        return queryset
    return [court for court in queryset if number in normalize_text(court.tenSan).split() or normalize_text(court.tenSan).endswith(number)]


def availability_intent(message):
    normalized = normalize_text(message)
    if recruitment_intent(message) or schedule_detail_intent(message):
        return False
    patterns = {
        "san trong",
        "cho trong",
        "con san",
        "co san",
        "san nao",
        "lich trong",
        "danh khong",
        "choi khong",
        "hom nay",
        "ngay mai",
        "toi nay",
        "toi mai",
        "kiem san",
        "khung gio",
        "dat san",
        "de dat",
        "phu hop",
        "2 tieng",
        "hai tieng",
    }
    return any(pattern in normalized for pattern in patterns) and any(
        word in normalized for word in {"san", "lich", "danh", "choi", "dat"}
    )


def active_court_intent(message):
    normalized = normalize_text(message)
    return any(pattern in normalized for pattern in {
        "dang hoat dong",
        "mo cua",
        "san nao mo",
        "san nao dang hoat dong",
        "cac san dang hoat dong",
    })


def recruitment_intent(message):
    normalized = normalize_text(message)
    patterns = {
        "tuyen thanh vien",
        "tuyen nguoi",
        "tuyen them",
        "tim thanh vien",
        "tim nguoi",
        "can thanh vien",
        "can nguoi",
        "can them",
        "thieu nguoi",
        "thieu thanh vien",
        "tim dong doi",
        "dong doi",
        "ru danh",
        "ru danh cau",
        "giao luu",
        "keo danh",
        "keo cau",
        "co keo",
        "keo nao",
        "danh chung",
        "choi chung",
        "tham gia",
        "nguoi moi",
        "moi choi",
        "trung binh",
        "nang cao",
        "trinh do",
    }
    return any(pattern in normalized for pattern in patterns)


def schedule_detail_intent(message):
    normalized = normalize_text(message)
    detail_patterns = {
        "ai dang",
        "dang tham gia",
        "chi tiet lich",
        "chi tiet san",
        "bao nhieu nguoi",
        "nguoi dang ky",
        "ghi chu",
        "dong nguoi",
        "dong nhat",
        "dang choi",
        "dang danh",
        "xem lich san",
        "lich san hom nay",
        "lich san ngay mai",
        "toan bo lich san",
        "lich san moi nhat",
        "vua duoc tao",
        "bi huy",
        "it nguoi",
        "gan day",
        "nguoi tao",
        "san nay",
    }
    return any(pattern in normalized for pattern in detail_patterns)


def forum_intent(message):
    normalized = normalize_text(message)
    return any(pattern in normalized for pattern in {
        "dien dan",
        "bai viet",
        "bai dang",
        "thao luan",
        "quan tam nhieu",
    })


def stats_intent(message):
    normalized = normalize_text(message)
    if court_number_from_message(message) or "san nay" in normalized or "lich nay" in normalized:
        return False
    return any(pattern in normalized for pattern in {
        "bao nhieu san",
        "bao nhieu lich",
        "bao nhieu nguoi",
        "he thong hien co",
        "san dang hoat dong",
    }) and "?" in (message or "")


def target_date_from_message(message):
    normalized = normalize_text(message)
    today = timezone.localdate()
    if "ngay mai" in normalized or "mai" in normalized:
        return today + timedelta(days=1)
    if "ngay kia" in normalized or "mot" in normalized or "mốt" in (message or "").lower():
        return today + timedelta(days=2)

    for token in normalized.replace("-", "/").split():
        try:
            parsed = datetime.strptime(token, "%d/%m/%Y").date()
            return parsed
        except ValueError:
            pass
        try:
            parsed = datetime.strptime(f"{token}/{today.year}", "%d/%m/%Y").date()
            return parsed
        except ValueError:
            pass
    return today


def bookings_for_dates(dates, branch=None):
    bookings = (
        DatSan.objects.filter(
            ngayBatDau__in=dates,
            trangThai__in=["pending", "confirmed", "completed"],
        )
        .select_related("san", "san__maChiNhanh", "nguoi_dat")
        .order_by("ngayBatDau", "san__maChiNhanh__tenChiNhanh", "san__tenSan", "gioBatDau")
    )
    if branch:
        bookings = bookings.filter(san__maChiNhanh=branch)
    return bookings


def apply_time_filter(bookings, start_time, end_time, exact_time=False):
    if not start_time:
        return bookings
    if exact_time:
        return bookings.filter(gioBatDau__lte=start_time, gioKetThuc__gt=start_time)
    return bookings.filter(gioBatDau__lt=end_time, gioKetThuc__gt=start_time)


def filter_recruitment_by_message(bookings, message):
    normalized = normalize_text(message)
    if "mot nguoi" in normalized or "1 nguoi" in normalized or "thieu mot" in normalized:
        bookings = bookings.filter(soLuongTuyen=1)
    if "nguoi moi" in normalized or "moi choi" in normalized or "de tham gia" in normalized:
        bookings = bookings.filter(trinh_do_can__in=["yeu", "tb"])
    elif "trung binh" in normalized:
        bookings = bookings.filter(trinh_do_can="tb")
    elif "nang cao" in normalized or "gioi" in normalized:
        bookings = bookings.filter(trinh_do_can__in=["kha", "gioi"])
    return bookings


def build_active_court_reply(message, branch):
    if not active_court_intent(message):
        return None

    dates = target_dates_from_message(message)
    courts = SanCauLong.objects.filter(is_active=True).select_related("maChiNhanh").order_by("maChiNhanh__tenChiNhanh", "tenSan")
    if branch:
        courts = courts.filter(maChiNhanh=branch)
    if not courts.exists():
        return "Hiện chưa có sân đang hoạt động ở chi nhánh này."

    branch_text = f" tại {branch.tenChiNhanh}" if branch else ""
    date_text = " và ".join(date_label(day) for day in dates)
    names = "; ".join(f"{court.maChiNhanh.tenChiNhanh} - {court.tenSan}" if not branch else court.tenSan for court in courts[:10])
    more = f" Còn {courts.count() - 10} sân khác." if courts.count() > 10 else ""
    return f"{date_text.capitalize()}{branch_text} có các sân đang hoạt động: {names}. Giờ mở cửa mặc định {format_time(OPEN_TIME)}-{format_time(CLOSE_TIME)}.{more}"


def build_recruitment_reply(message, branch):
    if not recruitment_intent(message):
        return None

    dates = target_dates_from_message(message)
    start_time, end_time, exact_time = extract_time_request(message)
    bookings = (
        DatSan.objects.filter(
            ngayBatDau__in=dates,
            tuyenThanhVien=True,
            soLuongTuyen__gt=0,
            trangThai__in=["pending", "confirmed", "completed"],
        )
        .select_related("san", "san__maChiNhanh", "nguoi_dat")
        .order_by("san__maChiNhanh__tenChiNhanh", "san__tenSan", "gioBatDau")
    )
    if branch:
        bookings = bookings.filter(san__maChiNhanh=branch)
    bookings = apply_time_filter(bookings, start_time, end_time, exact_time)
    bookings = filter_recruitment_by_message(bookings, message)

    branch_text = f" tại {branch.tenChiNhanh}" if branch else ""
    date_text = " và ".join(date_label(day) for day in dates)
    if not bookings.exists():
        return (
            f"{date_text.capitalize()}{branch_text} hiện chưa có lịch nào bật tuyển thành viên. "
            "Bạn có thể xem lại lịch cộng đồng hoặc tự đặt sân rồi bật tuyển thành viên cho kèo của mình."
        )

    lines = []
    for booking in bookings[:6]:
        level = booking.get_trinh_do_can_display() if booking.trinh_do_can else "không yêu cầu trình độ"
        note = f", ghi chú: {booking.ghi_chu_tuyen}" if booking.ghi_chu_tuyen else ""
        day_prefix = f"{booking.ngayBatDau:%d/%m} " if len(dates) > 1 else ""
        lines.append(
            f"{day_prefix}{booking.san.tenSan} {format_time(booking.gioBatDau)}-{format_time(booking.gioKetThuc)} "
            f"cần {booking.soLuongTuyen} người, {level}{note}"
        )
    more = f" Còn {bookings.count() - 6} kèo khác đang tuyển." if bookings.count() > 6 else ""
    join_hint = " Nếu muốn tham gia, bạn có thể mở lịch cộng đồng để xem chi tiết hoặc nhắn quản lý chi nhánh hỗ trợ."
    return f"{date_text.capitalize()}{branch_text} có lịch đang tuyển thành viên: {'; '.join(lines)}.{more}{join_hint}"


def build_stats_reply(message, branch):
    if not stats_intent(message):
        return None

    normalized = normalize_text(message)
    dates = target_dates_from_message(message)
    branch_text = f" tại {branch.tenChiNhanh}" if branch else ""
    date_text = " và ".join(date_label(day) for day in dates)

    active_courts = SanCauLong.objects.filter(is_active=True)
    if branch:
        active_courts = active_courts.filter(maChiNhanh=branch)

    if "bao nhieu san" in normalized or "he thong hien co" in normalized:
        return f"Hệ thống hiện có {active_courts.count()} sân đang hoạt động{branch_text}."

    bookings = bookings_for_dates(dates, branch)
    if "bao nhieu lich" in normalized:
        return f"{date_text.capitalize()}{branch_text} có {bookings.count()} lịch sân trong hệ thống."

    if "bao nhieu nguoi" in normalized:
        bookings = filter_recruitment_by_message(bookings, message)
        recruiting_total = sum(item.soLuongTuyen or 0 for item in bookings if item.tuyenThanhVien)
        court_names = ", ".join(dict.fromkeys(item.san.tenSan for item in bookings))
        court_text = f" tại {court_names}" if court_names else ""
        return (
            f"{date_text.capitalize()}{branch_text}{court_text} có {bookings.count()} lịch sân. "
            f"Hệ thống chưa lưu danh sách người tham gia thực tế, hiện chỉ ghi nhận tổng số người đang tuyển là {recruiting_total}."
        )

    return f"{date_text.capitalize()}{branch_text} có {active_courts.count()} sân đang hoạt động."


def build_schedule_detail_reply(message, branch):
    if not schedule_detail_intent(message):
        return None

    normalized = normalize_text(message)
    if "san nay" in normalized or "lich san nay" in normalized:
        return "Bạn vui lòng nêu rõ sân số mấy, ngày và khung giờ để mình kiểm tra đúng lịch sân đó."

    dates = target_dates_from_message(message)
    start_time, end_time, exact_time = extract_time_request(message)
    if "bi huy" in normalized:
        bookings = DatSan.objects.filter(ngayBatDau__in=dates, trangThai="cancelled").select_related("san", "san__maChiNhanh", "nguoi_dat")
        if branch:
            bookings = bookings.filter(san__maChiNhanh=branch)
    else:
        bookings = bookings_for_dates(dates, branch)
        bookings = apply_time_filter(bookings, start_time, end_time, exact_time)

    court_number = court_number_from_message(message)
    if court_number:
        bookings = [booking for booking in bookings if court_number in normalize_text(booking.san.tenSan)]
    else:
        bookings = list(bookings)

    branch_text = f" tại {branch.tenChiNhanh}" if branch else ""
    date_text = " và ".join(date_label(day) for day in dates)
    if not bookings:
        return f"{date_text.capitalize()}{branch_text} chưa có lịch sân phù hợp với câu hỏi này."

    if "vua duoc tao" in normalized or "moi nhat" in normalized:
        latest = max(bookings, key=lambda item: item.ngay_tao)
        return (
            f"Lịch sân mới nhất{branch_text} là {latest.san.tenSan} ngày {latest.ngayBatDau:%d/%m/%Y} "
            f"{format_time(latest.gioBatDau)}-{format_time(latest.gioKetThuc)}, do {latest.tenNguoiDat} tạo."
        )

    if "dong nguoi" in normalized or "dong nhat" in normalized or "gan day" in normalized:
        top = max(bookings, key=lambda item: item.soLuongTuyen or 0)
        return (
            "Hệ thống hiện chưa lưu danh sách người tham gia thực tế, chỉ có người đặt và số lượng đang tuyển. "
            f"Lịch có nhu cầu tuyển nhiều nhất {date_text}{branch_text} là {top.san.tenSan} "
            f"{format_time(top.gioBatDau)}-{format_time(top.gioKetThuc)}, đang tuyển {top.soLuongTuyen or 0} người."
        )

    if "it nguoi" in normalized:
        lowest = min(bookings, key=lambda item: item.soLuongTuyen or 0)
        return (
            "Hệ thống hiện chưa lưu số người đã tham gia thực tế. "
            f"Lịch có nhu cầu tuyển ít nhất {date_text}{branch_text} là {lowest.san.tenSan} "
            f"{format_time(lowest.gioBatDau)}-{format_time(lowest.gioKetThuc)}, đang tuyển {lowest.soLuongTuyen or 0} người."
        )

    lines = []
    for booking in bookings[:6]:
        customer_name = booking.tenNguoiDat or (booking.nguoi_dat.ten if booking.nguoi_dat else "Khách hàng")
        recruit = f", đang tuyển {booking.soLuongTuyen} người" if booking.tuyenThanhVien and booking.soLuongTuyen else ""
        note = f", ghi chú: {booking.ghi_chu_tuyen}" if booking.ghi_chu_tuyen else ""
        day_prefix = f"{booking.ngayBatDau:%d/%m} " if len(dates) > 1 else ""
        lines.append(
            f"{day_prefix}{booking.san.tenSan} {format_time(booking.gioBatDau)}-{format_time(booking.gioKetThuc)} "
            f"do {customer_name} đặt, trạng thái {booking.get_trangThai_display()}{recruit}{note}"
        )
    more = f" Còn {len(bookings) - 6} lịch khác." if len(bookings) > 6 else ""
    return (
        f"Chi tiết lịch sân {date_text}{branch_text}: {'; '.join(lines)}.{more} "
        "Lưu ý: hệ thống chưa có danh sách người đăng ký tham gia riêng ngoài thông tin người đặt và số lượng tuyển."
    )


def available_ranges_for_court(court, target_date):
    bookings = (
        DatSan.objects.filter(
            san=court,
            ngayBatDau=target_date,
            trangThai__in=["pending", "confirmed", "completed"],
        )
        .order_by("gioBatDau", "gioKetThuc")
        .values_list("gioBatDau", "gioKetThuc")
    )
    ranges = []
    cursor = OPEN_TIME
    for start, end in bookings:
        if start > cursor:
            ranges.append((cursor, start))
        if end > cursor:
            cursor = end
    if cursor < CLOSE_TIME:
        ranges.append((cursor, CLOSE_TIME))
    return ranges


def range_contains_request(ranges, start_time, end_time, exact_time=False):
    if not start_time:
        return ranges
    matched = []
    for start, end in ranges:
        if exact_time and start <= start_time < end:
            matched.append((start, end))
        elif not exact_time and start <= start_time and end >= end_time:
            matched.append((start, end))
    return matched


def build_availability_reply(message, branch):
    if not availability_intent(message):
        return None

    dates = target_dates_from_message(message)
    start_time, end_time, exact_time = extract_time_request(message)
    normalized = normalize_text(message)
    if ("2 tieng" in normalized or "hai tieng" in normalized) and not start_time:
        start_time, end_time, exact_time = OPEN_TIME, time(9, 0), False
    courts = SanCauLong.objects.filter(is_active=True).select_related("maChiNhanh").order_by("tenSan")
    if branch:
        courts = courts.filter(maChiNhanh=branch)
    court_number = court_number_from_message(message)
    courts = filter_courts_by_number(list(courts), court_number)

    if not courts:
        return "Hiện chưa có sân đang hoạt động ở chi nhánh này."

    free_lines = []
    busy_lines = []
    for target_date in dates:
        for court in courts:
            ranges = range_contains_request(
                available_ranges_for_court(court, target_date),
                start_time,
                end_time,
                exact_time,
            )
            day_prefix = f"{target_date:%d/%m} " if len(dates) > 1 else ""
            if ranges:
                if start_time and end_time and not exact_time:
                    range_text = f"{format_time(start_time)}-{format_time(end_time)}"
                else:
                    range_text = ", ".join(f"{format_time(start)}-{format_time(end)}" for start, end in ranges[:3])
                suffix = "..." if len(ranges) > 3 else ""
                free_lines.append(f"{day_prefix}{court.tenSan}: {range_text}{suffix}")
            else:
                busy_lines.append(f"{day_prefix}{court.tenSan}")

    branch_text = f" tại {branch.tenChiNhanh}" if branch else ""
    date_text = " và ".join(date_label(day) for day in dates)
    if free_lines:
        preview = "; ".join(free_lines[:6])
        more = f" Còn {len(free_lines) - 6} sân/khung ngày khác cũng có giờ trống." if len(free_lines) > 6 else ""
        return f"Còn sân trống{branch_text} {date_text}. Khung giờ gợi ý: {preview}.{more}"

    busy_text = ", ".join(busy_lines[:6])
    if start_time and end_time:
        return f"{date_text.capitalize()}{branch_text} hiện chưa có sân trống trong khung {format_time(start_time)}-{format_time(end_time)}. Các sân bị bận: {busy_text}."
    if start_time and exact_time:
        return f"{date_text.capitalize()}{branch_text} hiện chưa có sân trống tại mốc {format_time(start_time)}. Các sân bị bận: {busy_text}."
    return f"{date_text.capitalize()}{branch_text} hiện các sân đang kín trong khung {format_time(OPEN_TIME)}-{format_time(CLOSE_TIME)}: {busy_text}."


def build_forum_reply(message):
    if not forum_intent(message):
        return None

    normalized = normalize_text(message)
    posts = list(BaiDang.objects.filter(duyet_bai=True).select_related("nguoi_dang").order_by("-luot_xem", "-ngay_dang")[:20])
    if "moi" in normalized or "hom nay" in normalized or "thao luan" in normalized:
        posts = list(BaiDang.objects.filter(duyet_bai=True).select_related("nguoi_dang").order_by("-ngay_dang")[:20])
    if "dong doi" in normalized or "tuyen" in normalized or "cau long" in normalized or "nguoi danh cau" in normalized:
        posts = [
            post for post in posts
            if any(keyword in normalize_text(f"{post.tieu_de} {post.noi_dung}") for keyword in {"dong doi", "tuyen", "cau long", "giao luu", "keo"})
        ]

    if not posts:
        return "Hiện chưa có bài viết phù hợp trên diễn đàn. Bạn có thể vào diễn đàn để đăng bài tìm đồng đội hoặc hỏi kinh nghiệm chơi cầu lông."

    lines = []
    for post in posts[:5]:
        author = post.nguoi_dang.ten if post.nguoi_dang else "Thành viên"
        lines.append(f"{post.tieu_de} - {author}")
    more = f" Còn {len(posts) - 5} bài khác." if len(posts) > 5 else ""
    return f"Diễn đàn đang có các bài mới/phù hợp: {'; '.join(lines)}.{more}"


def branch_admin_queryset(branch):
    if not branch:
        return NguoiDung.objects.none()
    return NguoiDung.objects.filter(chi_nhanh_quan_ly=branch).filter(
        Q(role__in=["staff", "manager"]) | Q(is_staff=True) | Q(is_superuser=True)
    ).order_by("-is_staff", "id")


def pick_branch_admin(branch):
    return branch_admin_queryset(branch).first()


def latest_customer_branch(user):
    latest_booking = (
        DatSan.objects.filter(nguoi_dat=user)
        .select_related("san__maChiNhanh")
        .order_by("-ngay_tao")
        .first()
    )
    return latest_booking.san.maChiNhanh if latest_booking else None


def resolve_branch_for_message(user, message="", branch_id=None):
    if branch_id:
        branch = ChiNhanh.objects.filter(id=branch_id).first()
        if branch:
            return branch

    normalized = normalize_text(message)
    branches = list(ChiNhanh.objects.all().order_by("id"))
    for index, branch in enumerate(branches, start=1):
        branch_name = normalize_text(branch.tenChiNhanh)
        manager_name = normalize_text(branch.tenQuanLy)
        if branch_name and branch_name in normalized:
            return branch
        if manager_name and manager_name in normalized:
            return branch
        if f"chi nhanh {index}" in normalized or f"cn {index}" in normalized or f"chi nhanh so {index}" in normalized:
            return branch

    return latest_customer_branch(user) or (branches[0] if branches else None)


def get_customer_conversation(user, branch=None):
    qs = HoiThoaiKhachHang.objects.filter(nguoi_dung=user, da_dong=False)
    if branch:
        conversation = qs.filter(chi_nhanh=branch).order_by("-ngay_tao").first()
        if conversation:
            return conversation
        title = f"Hỗ trợ {user.ten} - {branch.tenChiNhanh}"
        return HoiThoaiKhachHang.objects.create(nguoi_dung=user, chi_nhanh=branch, tieu_de=title)

    conversation = qs.order_by("-ngay_tao").first()
    if conversation:
        return conversation

    title = f"Hỗ trợ {user.ten}"
    return HoiThoaiKhachHang.objects.create(nguoi_dung=user, chi_nhanh=branch, tieu_de=title)


def manager_label(conversation):
    if conversation.admin_phu_trach:
        return conversation.admin_phu_trach.ten or conversation.admin_phu_trach.username
    if conversation.chi_nhanh:
        return "Đang chờ quản lý nhận"
    return "Bộ phận hỗ trợ"


def mark_conversation_admin_request(conversation, branch):
    if branch:
        conversation.chi_nhanh = branch
    # Không gán cứng một quản lý khi chi nhánh có nhiều người trực.
    # Cuộc chat sẽ vào hàng chờ chung; quản lý đầu tiên phản hồi sẽ nhận phụ trách.
    conversation.admin_phu_trach = None
    conversation.can_admin = True
    conversation.last_admin_request_at = timezone.now()
    conversation.save(update_fields=["chi_nhanh", "admin_phu_trach", "can_admin", "last_admin_request_at"])


def create_customer_message(user, message, branch_id=None, force_admin=False):
    branch = resolve_branch_for_message(user, message, branch_id)
    conversation = get_customer_conversation(user, branch)
    wants_admin = force_admin or wants_admin_reply(message)

    if wants_admin:
        mark_conversation_admin_request(conversation, branch)
        reply, source, needs_admin = None, "admin", True
    else:
        forum_reply = build_forum_reply(message)
        stats_reply = None if forum_reply else build_stats_reply(message, branch)
        schedule_reply = None if forum_reply or stats_reply else build_schedule_detail_reply(message, branch)
        recruitment_reply = None if forum_reply or stats_reply or schedule_reply else build_recruitment_reply(message, branch)
        active_court_reply = None if forum_reply or stats_reply or schedule_reply or recruitment_reply else build_active_court_reply(message, branch)
        availability_reply = None if forum_reply or stats_reply or schedule_reply or recruitment_reply or active_court_reply else build_availability_reply(message, branch)
        if stats_reply:
            reply, source, needs_admin = stats_reply, "ai", False
        elif schedule_reply:
            reply, source, needs_admin = schedule_reply, "ai", False
        elif recruitment_reply:
            reply, source, needs_admin = recruitment_reply, "ai", False
        elif active_court_reply:
            reply, source, needs_admin = active_court_reply, "ai", False
        elif availability_reply:
            reply, source, needs_admin = availability_reply, "ai", False
        elif forum_reply:
            reply, source, needs_admin = forum_reply, "ai", False
        else:
            reply, source, needs_admin = tao_phan_hoi_ho_tro(message)
        if needs_admin:
            mark_conversation_admin_request(conversation, branch)

    support_message = HoTro.objects.create(
        hoi_thoai=conversation,
        nguoi_dung=user,
        nguoi_gui="customer",
        cau_hoi=message,
        tra_loi=reply,
        nguon_tra_loi=source,
        yeu_cau_admin=needs_admin,
    )
    if needs_admin:
        notify_admins(
            title=f"{user.ten} muốn trao đổi với quản lý",
            message=f"Tin nhắn mới: {message[:160]}",
            category="support",
            link=f"/quan-tri/ho-tro/{conversation.id}/",
            branch=branch,
        )
    return conversation, support_message


def create_admin_message(conversation, admin_user, message):
    return HoTro.objects.create(
        hoi_thoai=conversation,
        nguoi_dung=conversation.nguoi_dung,
        nguoi_gui="admin",
        cau_hoi=message,
        tra_loi=None,
        nguon_tra_loi="admin",
        admin_tra_loi=admin_user,
        ngay_tra_loi=timezone.now(),
        da_xem=True,
        yeu_cau_admin=False,
    )


def serialize_message(message):
    admin_name = ""
    if message.admin_tra_loi:
        admin_name = message.admin_tra_loi.ten or message.admin_tra_loi.username
    elif message.nguon_tra_loi == "ai":
        admin_name = "AI hỗ trợ"
    return {
        "id": message.id,
        "sender": getattr(message, "nguoi_gui", "customer"),
        "question": message.cau_hoi,
        "reply": message.tra_loi or "",
        "reply_source": message.nguon_tra_loi,
        "admin_name": admin_name,
        "needs_admin": message.yeu_cau_admin,
        "sent_at": message.ngay_gui.strftime("%H:%M %d/%m") if message.ngay_gui else "",
        "replied_at": message.ngay_tra_loi.strftime("%H:%M %d/%m") if message.ngay_tra_loi else "",
    }


def serialize_conversation(conversation):
    unread = conversation.hotro_set.filter(da_xem=False).count()
    last = conversation.hotro_set.order_by("-ngay_gui").first()
    return {
        "id": conversation.id,
        "customer_name": conversation.ten,
        "customer_phone": conversation.sodienthoai,
        "branch_name": conversation.chi_nhanh.tenChiNhanh if conversation.chi_nhanh else "Chưa chọn chi nhánh",
        "manager_name": manager_label(conversation),
        "needs_admin": conversation.can_admin,
        "unread_count": unread,
        "last_message": last.cau_hoi[:80] if last else "",
        "last_at": last.ngay_gui.strftime("%H:%M %d/%m") if last and last.ngay_gui else "",
    }


def serialize_customer_state(user):
    conversation = HoiThoaiKhachHang.objects.filter(nguoi_dung=user, da_dong=False).order_by("-ngay_tao").first()
    messages = [serialize_message(item) for item in conversation.hotro_set.order_by("ngay_gui", "id")] if conversation else []
    state_version = ""
    if conversation:
        state_version = "|".join(
            f"{item['id']}:{item['sender']}:{item['reply_source']}:{item['sent_at']}:{item['replied_at']}"
            for item in messages
        )
    branches = [
        {"id": branch.id, "name": branch.tenChiNhanh, "manager": branch.tenQuanLy}
        for branch in ChiNhanh.objects.all().order_by("tenChiNhanh")
    ]
    return {
        "conversation": serialize_conversation(conversation) if conversation else None,
        "messages": messages,
        "branches": branches,
        "state_version": state_version,
    }
