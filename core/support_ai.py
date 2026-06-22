"""
AI support helper for the badminton court booking system.

Mục tiêu:
- Nhận diện câu hỏi trong/ngoài phạm vi hệ thống.
- Xử lý câu chào, cảm ơn, tạm biệt trước khi gọi AI.
- Phân loại intent rõ ràng.
- Cố gắng lấy dữ liệu thật từ database Django nếu model/field tồn tại.
- Chỉ đưa AI diễn đạt dữ liệu, không để AI tự bịa lịch sân.

Hàm public cần giữ cho view hiện tại:
    tao_phan_hoi_ho_tro(message) -> (reply, source, handoff_admin)
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Optional

import requests
from django.apps import apps
from django.conf import settings
from django.db.models import Q, QuerySet
from django.utils import timezone


logger = logging.getLogger("security")

HANDOFF_MARKER = "HANDOFF_ADMIN"
MAX_CONTEXT_ITEMS = 8

# Các cụm này nên là yêu cầu gặp người thật rõ ràng, tránh bắt nhầm câu "quản lý sân là gì".
ADMIN_KEYWORDS = {
    "admin",
    "gap admin",
    "goi admin",
    "nhan vien",
    "gap nhan vien",
    "nguoi that",
    "gap nguoi that",
    "goi lai",
    "lien he truc tiep",
    "gap truc tiep",
    "gap quan ly",
    "lien he quan ly",
    "noi chuyen voi quan ly",
    "khieu nai",
    "khan cap",
    "hoan tien",
}

ABBREVIATION_MAP = {
    "k": "khong",
    "ko": "khong",
    "kh": "khong",
    "hok": "khong",
    "hong": "khong",
    "dc": "duoc",
    "đc": "duoc",
    "hn": "hom nay",
    "hnay": "hom nay",
    "mai": "ngay mai",
    "tmr": "ngay mai",
    "ad": "admin",
}

# Từ khóa lõi liên quan hệ thống. Không đưa các từ thời gian đơn lẻ như "hôm nay" vào đây.
SYSTEM_ACTION_KEYWORDS = {
    "dat san",
    "dat lich",
    "lich san",
    "san trong",
    "con san",
    "het san",
    "san nao",
    "san so",
    "mo cua",
    "hoat dong",
    "danh khong",
    "choi khong",
    "dang choi",
    "dang danh",
    "chi tiet lich",
    "ghi chu",
    "nguoi dang ky",
    "dong nguoi",
    "trung lich",
    "gio vang",
    "gia san",
    "bang gia",
    "gia thue san",
    "thanh toan",
    "coc",
    "dat coc",
    "qr",
    "chuyen khoan",
    "hoa don",
    "dang ky",
    "dang nhap",
    "mat khau",
    "bai viet",
    "dien dan",
    "ho tro",
    "tai khoan",
    "tai khoan bi khoa",
    "anh dai dien",
    "thong tin ca nhan",
    "xoa tai khoan",
    "dang xuat",
    "tuyen",
    "tuyen thanh vien",
    "tuyen nguoi",
    "tim nguoi",
    "tim thanh vien",
    "can nguoi",
    "can thanh vien",
    "thieu nguoi",
    "giao luu",
    "keo danh",
    "keo cau",
    "danh chung",
    "choi chung",
    "co dinh",
    "vang lai",
    "check in",
    "huy san",
    "huy don",
    "xoa don",
    "duyet san",
    "chi nhanh",
    "quan ly san",
    "website",
    "chuc nang",
    "huong dan",
    "buoc dat san",
    "he thong hoat dong",
    "binh luan",
    "tim kiem bai viet",
}

GREETING_KEYWORDS = {"e", "alo", "hello", "hi", "chao", "xin chao", "ban oi", "chao ban"}
THANKS_KEYWORDS = {"cam on", "cam on nhe", "thanks", "thank you", "ok cam on"}
GOODBYE_KEYWORDS = {"tam biet", "bye", "gap lai sau"}
IDENTITY_KEYWORDS = {"ban la ai", "ban co the lam gi", "ai vay", "may la ai"}
IGNORE_KEYWORDS = {"bo qua", "nhap nham", "cau hoi truoc", "hoi nham"}

DATE_KEYWORDS = {"hom nay", "ngay mai", "ngay kia", "toi nay", "sang mai", "cuoi tuan", "tuan nay"}

OUT_OF_SCOPE_REPLY = (
    "Mình là AI hỗ trợ hệ thống đặt sân nên chỉ trả lời các câu hỏi liên quan đến đặt sân, lịch sân, "
    "giá sân, cọc chuyển khoản, hóa đơn, tài khoản và diễn đàn. Nếu bạn cần người thật hỗ trợ, hãy bấm "
    "nút gặp quản lý chi nhánh."
)

GENERIC_SYSTEM_REPLY = (
    "Mình có thể hỗ trợ các câu hỏi về đặt sân, kiểm tra trùng lịch, cọc sân, chuyển khoản QR, "
    "hóa đơn, tài khoản và diễn đàn. Bạn cứ nêu rõ chi nhánh, sân, ngày hoặc thao tác đang gặp vướng nhé."
)


# -----------------------------------------------------------------------------
# Text processing
# -----------------------------------------------------------------------------


def normalize_text(value: Any) -> str:
    """Chuẩn hóa tiếng Việt không dấu, viết thường, mở rộng viết tắt."""
    text = str(value or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^0-9a-zA-Z:/\s-]", " ", text.lower())
    text = re.sub(r"\s+", " ", text).strip()

    words = [ABBREVIATION_MAP.get(word, word) for word in text.split()]
    return " ".join(words)


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def is_smalltalk(message: str) -> bool:
    normalized = normalize_text(message)
    return (
        normalized in GREETING_KEYWORDS
        or any(normalized.startswith(f"{word} ") for word in GREETING_KEYWORDS)
        or contains_any(normalized, THANKS_KEYWORDS)
        or contains_any(normalized, GOODBYE_KEYWORDS)
        or contains_any(normalized, IDENTITY_KEYWORDS)
        or contains_any(normalized, IGNORE_KEYWORDS)
    )


def wants_admin_reply(message: str) -> bool:
    normalized = normalize_text(message)
    return contains_any(normalized, ADMIN_KEYWORDS)


def looks_system_related(message: str) -> bool:
    """Chỉ xem là liên quan hệ thống khi có từ khóa hành động/tài nguyên, không chỉ dựa vào ngày tháng."""
    normalized = normalize_text(message)

    if contains_any(normalized, SYSTEM_ACTION_KEYWORDS):
        return True

    # Trường hợp câu rất tự nhiên: "tối nay có sân không", "mai đánh không".
    has_date = contains_any(normalized, DATE_KEYWORDS)
    has_court_word = any(word in normalized for word in {"san", "cau", "danh", "choi", "keo"})
    return has_date and has_court_word


# -----------------------------------------------------------------------------
# Intent detection
# -----------------------------------------------------------------------------


def detect_intent(message: str) -> str:
    normalized = normalize_text(message)

    if wants_admin_reply(normalized):
        return "handoff_admin"

    if is_smalltalk(normalized):
        return "smalltalk"

    if not looks_system_related(normalized):
        return "out_of_scope"

    if contains_any(normalized, {"tuyen", "tuyen thanh vien", "tuyen nguoi", "tim nguoi", "can nguoi", "thieu nguoi", "giao luu", "keo danh", "keo cau", "danh chung", "choi chung"}):
        return "recruitment"

    if contains_any(normalized, {"san trong", "con san", "het san", "trong khong", "con trong", "chua duoc dat"}):
        return "availability"

    if contains_any(normalized, {"lich san", "chi tiet lich", "dang danh", "dang choi", "hom nay co san", "ngay mai co san", "san nao danh", "co san nao"}):
        return "schedule"

    if contains_any(normalized, {"dat san", "dat lich", "trung lich", "buoc dat san", "cach dat"}):
        return "booking_guide"

    if contains_any(normalized, {"gia san", "bang gia", "gia thue san", "gio vang", "vang lai"}):
        return "price"

    if contains_any(normalized, {"qr", "chuyen khoan", "thanh toan", "coc", "dat coc"}):
        return "payment"

    if contains_any(normalized, {"hoa don", "xuat hoa don", "tai hoa don"}):
        return "invoice"

    if contains_any(normalized, {"dang ky", "dang nhap", "mat khau", "tai khoan", "anh dai dien", "thong tin ca nhan", "xoa tai khoan", "dang xuat"}):
        return "account"

    if contains_any(normalized, {"bai viet", "dien dan", "dang bai", "binh luan", "tim kiem bai viet"}):
        return "forum"

    if contains_any(normalized, {"huy don", "xoa don", "huy san"}):
        return "cancel"

    if contains_any(normalized, {"website", "chuc nang", "huong dan", "he thong hoat dong", "dung de lam gi"}):
        return "system_guide"

    return "system_general"


# -----------------------------------------------------------------------------
# Date/time parsing
# -----------------------------------------------------------------------------


def parse_date_from_message(message: str) -> Optional[date]:
    normalized = normalize_text(message)
    today = timezone.localdate()

    if "ngay kia" in normalized:
        return today + timedelta(days=2)
    if "ngay mai" in normalized or "sang mai" in normalized:
        return today + timedelta(days=1)
    if "hom nay" in normalized or "toi nay" in normalized:
        return today

    # Bắt các dạng 20/6, 20-06, 20/06/2026.
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", normalized)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year_raw = match.group(3)
        year = today.year if not year_raw else int(year_raw)
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None

    return None


def parse_weekend_range(message: str) -> Optional[tuple[date, date]]:
    normalized = normalize_text(message)
    if "cuoi tuan" not in normalized:
        return None

    today = timezone.localdate()
    # weekday: Monday=0, Saturday=5, Sunday=6.
    days_to_saturday = (5 - today.weekday()) % 7
    saturday = today + timedelta(days=days_to_saturday)
    sunday = saturday + timedelta(days=1)
    return saturday, sunday


def parse_time_range_from_message(message: str) -> tuple[Optional[time], Optional[time]]:
    normalized = normalize_text(message)

    # 18h đến 20h, 18:30 den 20:00.
    match = re.search(r"\b(\d{1,2})(?:h|:)?(\d{0,2})\s*(?:den|toi|-)\s*(\d{1,2})(?:h|:)?(\d{0,2})\b", normalized)
    if match:
        start_hour = int(match.group(1))
        start_minute = int(match.group(2) or 0)
        end_hour = int(match.group(3))
        end_minute = int(match.group(4) or 0)
        try:
            return time(start_hour, start_minute), time(end_hour, end_minute)
        except ValueError:
            return None, None

    # Một mốc giờ đơn: 19h, lúc 19:30.
    match = re.search(r"\b(?:luc\s*)?(\d{1,2})(?:h|:)(\d{0,2})\b", normalized)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        try:
            return time(hour, minute), None
        except ValueError:
            return None, None

    if "toi" in normalized:
        return time(17, 0), time(22, 0)
    if "sang" in normalized:
        return time(5, 0), time(11, 0)
    if "chieu" in normalized:
        return time(13, 0), time(17, 0)

    return None, None


# -----------------------------------------------------------------------------
# Safe Django model helpers
# -----------------------------------------------------------------------------


def get_model(*model_names: str):
    """Lấy model theo tên nếu tồn tại, tránh import cứng làm vỡ project khi đổi tên model."""
    for model_name in model_names:
        try:
            return apps.get_model("members", model_name)
        except LookupError:
            continue
    return None


def field_names(model) -> set[str]:
    if not model:
        return set()
    return {field.name for field in model._meta.get_fields()}


def first_existing_field(model, candidates: Iterable[str]) -> Optional[str]:
    names = field_names(model)
    for candidate in candidates:
        if candidate in names:
            return candidate
    return None


def safe_order(qs: QuerySet, *fields: str) -> QuerySet:
    names = field_names(qs.model)
    valid_fields = []
    for field in fields:
        clean_name = field.lstrip("-")
        if clean_name in names:
            valid_fields.append(field)
    if not valid_fields:
        return qs
    try:
        return qs.order_by(*valid_fields)
    except Exception as exc:  # pragma: no cover - phòng lỗi field lạ/annotation.
        logger.info("AI support order_by skipped: %s", exc)
        return qs


def safe_filter(qs: QuerySet, *conditions: Q, **filters: Any) -> QuerySet:
    try:
        if conditions:
            qs = qs.filter(*conditions)
        if filters:
            qs = qs.filter(**filters)
        return qs
    except Exception as exc:  # pragma: no cover - phòng lỗi schema khác dự kiến.
        logger.info("AI support filter skipped: %s", exc)
        return qs


def apply_date_filter(qs: QuerySet, target_date: Optional[date], message: str) -> QuerySet:
    model = qs.model
    weekend = parse_weekend_range(message)
    date_field = first_existing_field(model, ["ngay_dat", "ngay", "ngay_su_dung", "booking_date", "date"])

    if not date_field:
        return qs

    if weekend:
        start_date, end_date = weekend
        return safe_filter(qs, **{f"{date_field}__range": (start_date, end_date)})

    if target_date:
        return safe_filter(qs, **{date_field: target_date})

    return qs


def apply_time_filter(qs: QuerySet, message: str) -> QuerySet:
    start, end = parse_time_range_from_message(message)
    if not start and not end:
        return qs

    model = qs.model
    start_field = first_existing_field(model, ["gio_bat_dau", "thoi_gian_bat_dau", "start_time", "bat_dau"])
    end_field = first_existing_field(model, ["gio_ket_thuc", "thoi_gian_ket_thuc", "end_time", "ket_thuc"])

    if start and end and start_field and end_field:
        # Lấy các lịch có giao với khoảng giờ người dùng hỏi.
        return safe_filter(qs, **{f"{start_field}__lt": end, f"{end_field}__gt": start})

    if start and start_field:
        return safe_filter(qs, **{f"{start_field}__lte": start})

    return qs


def apply_recruitment_filter(qs: QuerySet) -> QuerySet:
    model = qs.model
    names = field_names(model)

    for boolean_field in ["co_tuyen_thanh_vien", "tuyen_thanh_vien", "can_tuyen", "dang_tuyen", "is_recruiting"]:
        if boolean_field in names:
            return safe_filter(qs, **{boolean_field: True})

    text_conditions = Q()
    has_text_condition = False
    for text_field in ["ghi_chu", "mo_ta", "noi_dung", "tieu_de"]:
        if text_field in names:
            text_conditions |= Q(**{f"{text_field}__icontains": "tuyển"})
            text_conditions |= Q(**{f"{text_field}__icontains": "thiếu"})
            text_conditions |= Q(**{f"{text_field}__icontains": "cần người"})
            has_text_condition = True

    return safe_filter(qs, text_conditions) if has_text_condition else qs


def apply_status_filter(qs: QuerySet) -> QuerySet:
    """Cố gắng loại các lịch/đơn đã hủy nếu schema có field trạng thái."""
    model = qs.model
    status_field = first_existing_field(model, ["trang_thai", "status", "tinh_trang"])
    if not status_field:
        return qs
    try:
        return qs.exclude(**{f"{status_field}__icontains": "huy"})
    except Exception:
        return qs


def safe_value(obj: Any, candidates: Iterable[str], default: str = "") -> str:
    for name in candidates:
        try:
            value = getattr(obj, name, None)
        except Exception:
            value = None
        if value not in (None, ""):
            return str(value)
    return default


def related_value(obj: Any, relation_name: str, fields: Iterable[str]) -> str:
    try:
        relation = getattr(obj, relation_name, None)
    except Exception:
        relation = None
    if relation is None:
        return ""
    value = safe_value(relation, fields)
    return value or str(relation)


def format_booking_item(obj: Any) -> str:
    court = related_value(obj, "san", ["ten_san", "ten", "name"]) or related_value(obj, "court", ["ten_san", "ten", "name"])
    branch = related_value(obj, "chi_nhanh", ["ten_chi_nhanh", "ten", "name"]) or related_value(obj, "branch", ["ten_chi_nhanh", "ten", "name"])

    # Nếu chi nhánh nằm trong sân.
    if not branch:
        try:
            san = getattr(obj, "san", None) or getattr(obj, "court", None)
            branch = related_value(san, "chi_nhanh", ["ten_chi_nhanh", "ten", "name"]) if san else ""
        except Exception:
            branch = ""

    date_text = safe_value(obj, ["ngay_dat", "ngay", "ngay_su_dung", "booking_date", "date"])
    start = safe_value(obj, ["gio_bat_dau", "thoi_gian_bat_dau", "start_time", "bat_dau"])
    end = safe_value(obj, ["gio_ket_thuc", "thoi_gian_ket_thuc", "end_time", "ket_thuc"])
    status = safe_value(obj, ["trang_thai", "status", "tinh_trang"])
    note = safe_value(obj, ["ghi_chu", "mo_ta", "noi_dung"])
    creator = related_value(obj, "nguoi_dat", ["ho_ten", "username", "phone", "so_dien_thoai"]) or related_value(obj, "nguoi_tao", ["ho_ten", "username", "phone", "so_dien_thoai"])

    parts = []
    if court:
        parts.append(f"sân {court}")
    if branch:
        parts.append(f"chi nhánh {branch}")
    if date_text:
        parts.append(f"ngày {date_text}")
    if start or end:
        parts.append(f"giờ {start or '?'}-{end or '?'}")
    if status:
        parts.append(f"trạng thái {status}")
    if creator:
        parts.append(f"người tạo/đặt {creator}")
    if note:
        parts.append(f"ghi chú: {note[:120]}")

    return " - " + ", ".join(parts) if parts else f"- {obj}"


def format_forum_item(obj: Any) -> str:
    title = safe_value(obj, ["tieu_de", "title", "ten_bai_viet", "chu_de"], str(obj))
    created = safe_value(obj, ["created_at", "ngay_tao", "created", "thoi_gian_tao"])
    author = related_value(obj, "nguoi_dang", ["ho_ten", "username", "so_dien_thoai"]) or related_value(obj, "tac_gia", ["ho_ten", "username", "so_dien_thoai"])
    summary = safe_value(obj, ["noi_dung", "content", "mo_ta"])

    parts = [title]
    if created:
        parts.append(f"ngày {created}")
    if author:
        parts.append(f"người đăng {author}")
    if summary:
        parts.append(f"nội dung: {summary[:120]}")
    return "- " + ", ".join(parts)


def format_court_item(obj: Any) -> str:
    name = safe_value(obj, ["ten_san", "ten", "name"], str(obj))
    branch = related_value(obj, "chi_nhanh", ["ten_chi_nhanh", "ten", "name"])
    price_parts = []
    for field in ["gia", "gia_san", "gia_theo_gio", "gia_gio_vang", "gia_gio_thuong", "gia_vang_lai", "gia_co_dinh"]:
        if field in field_names(obj.__class__):
            value = safe_value(obj, [field])
            if value:
                price_parts.append(f"{field}: {value}")
    parts = [name]
    if branch:
        parts.append(f"chi nhánh {branch}")
    if price_parts:
        parts.append("; ".join(price_parts))
    return "- " + ", ".join(parts)


# -----------------------------------------------------------------------------
# Database context builder
# -----------------------------------------------------------------------------


def fetch_booking_context(intent: str, message: str) -> list[str]:
    Booking = get_model("DatSan", "LichSan", "Booking")
    if Booking is None:
        return []

    target_date = parse_date_from_message(message)
    qs = Booking.objects.all()
    qs = apply_status_filter(qs)
    qs = apply_date_filter(qs, target_date, message)
    qs = apply_time_filter(qs, message)

    if intent == "recruitment":
        qs = apply_recruitment_filter(qs)

    qs = safe_order(qs, "ngay_dat", "ngay", "gio_bat_dau", "thoi_gian_bat_dau", "created_at")

    try:
        return [format_booking_item(obj) for obj in qs[:MAX_CONTEXT_ITEMS]]
    except Exception as exc:
        logger.info("AI support could not fetch booking context: %s", exc)
        return []


def fetch_forum_context(message: str) -> list[str]:
    Post = get_model("BaiViet", "BaiDang", "ForumPost", "Post")
    if Post is None:
        return []

    qs = Post.objects.all()
    normalized = normalize_text(message)
    names = field_names(Post)

    if "tuyen" in normalized or "dong doi" in normalized or "giao luu" in normalized:
        q = Q()
        for field in ["tieu_de", "title", "noi_dung", "content", "mo_ta"]:
            if field in names:
                q |= Q(**{f"{field}__icontains": "tuyển"})
                q |= Q(**{f"{field}__icontains": "đồng đội"})
                q |= Q(**{f"{field}__icontains": "giao lưu"})
        if q:
            qs = safe_filter(qs, q)

    qs = safe_order(qs, "-created_at", "-ngay_tao", "-created", "-id")

    try:
        return [format_forum_item(obj) for obj in qs[:MAX_CONTEXT_ITEMS]]
    except Exception as exc:
        logger.info("AI support could not fetch forum context: %s", exc)
        return []


def fetch_price_context() -> list[str]:
    Court = get_model("San", "SanCau", "Court")
    if Court is None:
        return []

    qs = safe_order(Court.objects.all(), "ten_san", "ten", "name")
    try:
        return [format_court_item(obj) for obj in qs[:MAX_CONTEXT_ITEMS]]
    except Exception as exc:
        logger.info("AI support could not fetch court/price context: %s", exc)
        return []


def build_database_context(intent: str, message: str) -> str:
    """Lấy dữ liệu hệ thống phù hợp để đưa cho AI hoặc trả lời trực tiếp."""
    lines: list[str] = []

    if intent in {"schedule", "availability", "recruitment"}:
        booking_lines = fetch_booking_context(intent, message)
        if booking_lines:
            lines.append("Dữ liệu lịch/đơn đặt sân tìm thấy:")
            lines.extend(booking_lines)
        else:
            lines.append("Không tìm thấy lịch/đơn đặt sân phù hợp với câu hỏi trong database.")

    elif intent == "forum":
        forum_lines = fetch_forum_context(message)
        if forum_lines:
            lines.append("Dữ liệu bài viết diễn đàn tìm thấy:")
            lines.extend(forum_lines)
        else:
            lines.append("Không tìm thấy bài viết diễn đàn phù hợp trong database.")

    elif intent == "price":
        price_lines = fetch_price_context()
        if price_lines:
            lines.append("Dữ liệu sân/bảng giá tìm thấy:")
            lines.extend(price_lines)
        else:
            lines.append("Chưa tìm thấy dữ liệu bảng giá/sân trong database.")

    return "\n".join(lines).strip()


# -----------------------------------------------------------------------------
# Fallback replies
# -----------------------------------------------------------------------------


def smalltalk_reply(message: str) -> Optional[str]:
    normalized = normalize_text(message)

    if contains_any(normalized, IGNORE_KEYWORDS):
        return "Không sao, mình đã bỏ qua câu trước. Bạn cứ gửi lại câu hỏi mới khi cần hỗ trợ nhé."

    if normalized in THANKS_KEYWORDS or contains_any(normalized, THANKS_KEYWORDS):
        return "Không có gì. Mình luôn sẵn sàng hỗ trợ bạn về đặt sân, lịch sân, tuyển thành viên và tài khoản."

    if normalized in GOODBYE_KEYWORDS or contains_any(normalized, GOODBYE_KEYWORDS):
        return "Tạm biệt bạn. Khi cần kiểm tra sân trống hoặc hỗ trợ đặt sân, bạn cứ mở lại khung chat nhé."

    if contains_any(normalized, IDENTITY_KEYWORDS):
        return (
            "Mình là AI hỗ trợ của hệ thống đặt sân cầu lông. "
            "Mình có thể hỗ trợ kiểm tra lịch sân, sân trống, lịch tuyển thành viên, thanh toán, hóa đơn, tài khoản và diễn đàn."
        )

    if normalized in GREETING_KEYWORDS or any(normalized.startswith(f"{word} ") for word in GREETING_KEYWORDS):
        return (
            "Xin chào, mình là AI hỗ trợ. Bạn có thể hỏi về sân trống, lịch đang tuyển thành viên, "
            "đặt sân, tài khoản hoặc diễn đàn nhé."
        )

    return None


def static_system_reply(intent: str, message: str) -> Optional[str]:
    normalized = normalize_text(message)

    if intent == "system_guide":
        return (
            "Website dùng để xem chi nhánh, đặt sân, theo dõi lịch sử đặt sân, nhận yêu cầu đặt cọc, tải hóa đơn, "
            "đăng bài diễn đàn, tìm lịch đang tuyển thành viên và nhắn hỗ trợ. "
            "Luồng đặt sân là: chọn sân và khung giờ, gửi yêu cầu, quản lý gửi yêu cầu cọc, khách xác nhận chuyển khoản, rồi quản lý duyệt đơn."
        )

    if intent == "payment":
        return (
            "Sau khi quản lý gửi yêu cầu đặt cọc, hệ thống sẽ hiện thông tin đơn, mã QR và nội dung chuyển khoản để bạn sao chép nhanh. "
            "Bạn chuyển khoản xong thì bấm 'Đã chuyển khoản' để quản lý đối soát và duyệt đơn."
        )

    if intent == "booking_guide":
        return (
            "Khi bạn gửi yêu cầu đặt sân, hệ thống sẽ kiểm tra trùng lịch theo từng sân, ngày và khung giờ trước khi tạo đơn chờ duyệt. "
            "Sau đó đơn nằm trong lịch sử đặt sân để bạn theo dõi, xác nhận chuyển khoản, hủy hoặc xóa khi cần."
        )

    if intent == "invoice":
        return (
            "Sau khi đơn được quản lý xác nhận, bạn có thể xem và tải hóa đơn. "
            "Hóa đơn gồm thông tin khách hàng, chi nhánh, sân, khung giờ, trạng thái đặt và người duyệt."
        )

    if intent == "account":
        if "quen mat khau" in normalized:
            return "Nếu quên mật khẩu, bạn nên dùng chức năng đổi/khôi phục mật khẩu nếu hệ thống đã bật, hoặc nhắn quản lý để xác minh và hỗ trợ đặt lại mật khẩu."
        if "khong dang nhap" in normalized:
            return "Bạn hãy kiểm tra đúng số điện thoại và mật khẩu. Nếu nhập sai nhiều lần, tài khoản có thể bị khóa tạm thời để bảo mật."
        if "doi mat khau" in normalized:
            return "Bạn có thể đổi mật khẩu trong phần tài khoản/cá nhân nếu hệ thống đã bật chức năng này. Hãy dùng mật khẩu mạnh gồm chữ hoa, chữ thường, số và ký tự đặc biệt."
        if "anh dai dien" in normalized or "thong tin ca nhan" in normalized:
            return "Bạn có thể cập nhật ảnh đại diện hoặc thông tin cá nhân trong khu vực tài khoản nếu chức năng này được mở cho người dùng."
        if "xoa tai khoan" in normalized:
            return "Xóa tài khoản là thao tác nhạy cảm. Bạn nên yêu cầu quản trị viên hỗ trợ để xác minh trước khi xóa dữ liệu."
        if "dang xuat" in normalized:
            return "Bạn bấm nút đăng xuất trên thanh tài khoản để thoát phiên đăng nhập hiện tại."
        return "Bạn đăng nhập bằng số điện thoại đã đăng ký. Nếu tài khoản bị khóa tạm thời hoặc cần đổi thông tin, bạn hãy nhắn rõ tình trạng để hệ thống hướng dẫn tiếp."

    if intent == "cancel":
        return (
            "Đơn đang chờ duyệt có thể hủy, và các đơn chờ duyệt hoặc đã hủy có thể xóa để làm gọn danh sách. "
            "Nếu đơn đã được xác nhận mà cần thay đổi, bạn nên yêu cầu quản lý hỗ trợ trực tiếp."
        )

    return None


def direct_data_reply(intent: str, database_context: str) -> Optional[str]:
    """Trả lời trực tiếp khi không có API AI hoặc khi dữ liệu đã đủ rõ."""
    if not database_context:
        return None

    if database_context.startswith("Không tìm thấy") or database_context.startswith("Chưa tìm thấy"):
        if intent == "recruitment":
            return "Hiện mình chưa tìm thấy lịch sân nào đang tuyển thành viên phù hợp với câu hỏi của bạn. Bạn có thể thử chọn ngày hoặc chi nhánh cụ thể hơn."
        if intent == "availability":
            return "Hiện mình chưa tìm thấy dữ liệu sân trống phù hợp. Bạn hãy thử nêu rõ ngày, giờ hoặc chi nhánh cần đặt."
        if intent == "schedule":
            return "Hiện mình chưa tìm thấy lịch sân phù hợp với câu hỏi của bạn. Bạn có thể hỏi rõ hơn như 'hôm nay có sân nào đánh lúc 19h không'."
        if intent == "forum":
            return "Hiện mình chưa tìm thấy bài viết diễn đàn phù hợp với câu hỏi của bạn."
        if intent == "price":
            return "Hiện mình chưa tìm thấy dữ liệu bảng giá trong hệ thống. Bạn có thể liên hệ quản lý chi nhánh để được báo giá chính xác."

    # Nếu có dữ liệu thật nhưng không gọi AI, trả danh sách ngắn gọn.
    return database_context


def fallback_reply(message: str) -> Optional[str]:
    intent = detect_intent(message)

    if intent == "smalltalk":
        return smalltalk_reply(message)

    static_reply = static_system_reply(intent, message)
    if static_reply:
        return static_reply

    if looks_system_related(message):
        return GENERIC_SYSTEM_REPLY

    return None


# -----------------------------------------------------------------------------
# AI API
# -----------------------------------------------------------------------------


def extract_response_text(data: dict[str, Any]) -> str:
    """Hỗ trợ cả OpenAI Responses API và Chat Completions API."""
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()

    chunks: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)

    if chunks:
        return "\n".join(chunks).strip()

    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()

    return ""


def get_setting(name: str, default: Any = None) -> Any:
    env_value = os.getenv(name)
    if env_value is not None:
        return env_value
    return getattr(settings, name, default)


def get_int_setting(name: str, default: int) -> int:
    try:
        return int(get_setting(name, default))
    except (TypeError, ValueError):
        logger.warning("Invalid integer setting %s, fallback to %s", name, default)
        return default


def build_support_instructions() -> str:
    return (
        "Bạn là trợ lý hỗ trợ khách hàng cho website đặt sân cầu lông. "
        "Chỉ trả lời các câu hỏi liên quan đến hệ thống như đặt sân, lịch sân, kiểm tra trùng lịch, giờ vàng, giá, "
        "luồng cọc sân, chuyển khoản, QR, hóa đơn, tài khoản, diễn đàn, tuyển thành viên/giao lưu và hỗ trợ sử dụng website. "
        "Bạn chỉ được dùng dữ liệu hệ thống được cung cấp trong prompt. Không tự bịa sân, người chơi, giờ đánh, giá tiền hoặc bài viết. "
        "Nếu dữ liệu hệ thống nói không tìm thấy, hãy nói chưa có dữ liệu phù hợp và gợi ý người dùng nêu rõ ngày, giờ hoặc chi nhánh. "
        "Quy tắc hệ thống hiện tại: khách gửi yêu cầu đặt sân trước, quản lý gửi yêu cầu đặt cọc sau, "
        "khách bấm xác nhận đã chuyển khoản, rồi quản lý đối soát để duyệt đơn. "
        "Giá vãng lai: trước 17h là giờ vàng, từ 17h trở đi là giờ thường nếu hệ thống chưa có bảng giá cụ thể hơn. "
        f"Nếu khách yêu cầu người thật/admin, khiếu nại, hoàn tiền, hoặc hỏi ngoài phạm vi hệ thống thì chỉ trả về {HANDOFF_MARKER}. "
        "Trả lời ngắn gọn, lịch sự, bằng tiếng Việt, tối đa 4 câu."
    )


def build_ai_input(message: str, intent: str, database_context: str = "") -> str:
    today = timezone.localdate().isoformat()
    context = database_context or "Không có dữ liệu hệ thống bổ sung."
    return (
        f"Ngày hiện tại của hệ thống: {today}\n"
        f"Intent đã nhận diện: {intent}\n"
        f"Câu hỏi người dùng: {message}\n\n"
        f"Dữ liệu hệ thống:\n{context}\n\n"
        "Yêu cầu: trả lời dựa trên dữ liệu hệ thống ở trên. Nếu không có dữ liệu phù hợp, nói rõ là chưa tìm thấy."
    )


def call_ai_model(message: str, intent: str = "system_general", database_context: str = "") -> Optional[str]:
    enabled = str(get_setting("AI_SUPPORT_ENABLED", "True")).lower() in {"1", "true", "yes", "on"}
    api_key = get_setting("AI_SUPPORT_API_KEY") or get_setting("OPENAI_API_KEY")
    if not enabled:
        return None
    if not api_key:
        logger.info("AI support skipped because no API key is configured.")
        return None

    api_url = get_setting("AI_SUPPORT_API_URL", "https://api.openai.com/v1/responses")
    model = get_setting("AI_SUPPORT_MODEL", "gpt-4o-mini")
    timeout = get_int_setting("AI_SUPPORT_TIMEOUT", 12)

    payload = {
        "model": model,
        "instructions": build_support_instructions(),
        "input": build_ai_input(message, intent, database_context),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        reply = extract_response_text(response.json())
    except (requests.RequestException, ValueError) as exc:
        logger.warning("AI support request failed: %s", exc)
        return None

    if not reply or HANDOFF_MARKER in reply:
        return None
    return reply.strip()


# -----------------------------------------------------------------------------
# Public API used by views
# -----------------------------------------------------------------------------


def tao_phan_hoi_ho_tro(message: str):
    """
    Trả về tuple tương thích với view hiện tại:
        (noi_dung_tra_loi, nguon_tra_loi, can_chuyen_admin)

    - noi_dung_tra_loi: str hoặc None nếu cần admin xử lý.
    - nguon_tra_loi: "ai" hoặc "admin".
    - can_chuyen_admin: bool.
    """
    message = (message or "").strip()
    if not message:
        return "Bạn vui lòng nhập nội dung cần hỗ trợ nhé.", "ai", False

    intent = detect_intent(message)

    if intent == "handoff_admin":
        return None, "admin", True

    if intent == "smalltalk":
        return smalltalk_reply(message) or GENERIC_SYSTEM_REPLY, "ai", False

    if intent == "out_of_scope":
        return OUT_OF_SCOPE_REPLY, "ai", False

    # Các câu hướng dẫn tĩnh không cần gọi API AI.
    static_reply = static_system_reply(intent, message)
    if static_reply:
        return static_reply, "ai", False

    # Các câu cần dữ liệu thật: lịch sân, sân trống, tuyển thành viên, diễn đàn, bảng giá.
    database_context = build_database_context(intent, message)

    ai_reply = call_ai_model(message, intent=intent, database_context=database_context)
    if ai_reply:
        return ai_reply, "ai", False

    data_reply = direct_data_reply(intent, database_context)
    if data_reply:
        return data_reply, "ai", False

    return fallback_reply(message) or GENERIC_SYSTEM_REPLY, "ai", False
