from io import BytesIO
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None


WIDTH = 900
PADDING = 44
GREEN = "#0f766e"
DARK = "#111827"
TEXT = "#172033"
MUTED = "#667085"
BORDER = "#dbe3ee"
LIGHT = "#f6f8fb"


def ensure_pillow():
    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError("Pillow chưa sẵn sàng nên không thể xuất hóa đơn dạng ảnh.")


def find_font(size, bold=False):
    ensure_pillow()
    candidates = []
    if bold:
        candidates.extend([
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ])
    else:
        candidates.extend([
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ])

    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


FONT_TITLE = None
FONT_SUBTITLE = None
FONT_LABEL = None
FONT_TEXT = None
FONT_TEXT_BOLD = None
FONT_SMALL = None
FONT_TOTAL = None


def load_fonts():
    global FONT_TITLE, FONT_SUBTITLE, FONT_LABEL, FONT_TEXT, FONT_TEXT_BOLD, FONT_SMALL, FONT_TOTAL
    if FONT_TITLE is not None:
        return
    FONT_TITLE = find_font(34, bold=True)
    FONT_SUBTITLE = find_font(18)
    FONT_LABEL = find_font(15, bold=True)
    FONT_TEXT = find_font(21)
    FONT_TEXT_BOLD = find_font(22, bold=True)
    FONT_SMALL = find_font(15)
    FONT_TOTAL = find_font(30, bold=True)


def text_width(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def font_height(draw, font):
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    return bbox[3] - bbox[1]


def wrap_text(draw, text, font, max_width):
    words = str(text or "-").split()
    if not words:
        return ["-"]
    lines = []
    line = words[0]
    for word in words[1:]:
        candidate = f"{line} {word}"
        if text_width(draw, candidate, font) <= max_width:
            line = candidate
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def draw_rounded(draw, xy, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_label_value(draw, x, y, label, value, max_width):
    draw.text((x, y), label.upper(), fill=MUTED, font=FONT_LABEL)
    y += font_height(draw, FONT_LABEL) + 7
    for line in wrap_text(draw, value, FONT_TEXT_BOLD, max_width):
        draw.text((x, y), line, fill=TEXT, font=FONT_TEXT_BOLD)
        y += font_height(draw, FONT_TEXT_BOLD) + 6
    return y


def money(value):
    try:
        return f"{int(value):,}".replace(",", ".") + "đ"
    except (TypeError, ValueError):
        return "0đ"


def booking_code(booking):
    if booking.loaiDatSan == 1 and booking.nhom_dat_san:
        return f"#{str(booking.nhom_dat_san)[:8]}"
    return f"#{booking.id}"


def format_date(value):
    return value.strftime("%d/%m/%Y") if value else "-"


def format_time(value):
    return value.strftime("%H:%M") if value else "-"


def format_date_range(start, end):
    if not start:
        return "-"
    if not end or start == end:
        return format_date(start)
    return f"{format_date(start)} - {format_date(end)}"


def approver_name(approver):
    if not approver:
        return "Chưa duyệt"
    return getattr(approver, "ten", None) or getattr(approver, "username", None) or "Chưa duyệt"


def build_summary_from_items(booking, items, total_money):
    items = list(items)
    first_item = items[0] if items else booking
    last_item = items[-1] if items else booking
    is_group = booking.loaiDatSan == 1 and booking.nhom_dat_san
    statuses = {item.get_trangThai_display() for item in items}
    status_label = statuses.pop() if len(statuses) == 1 else booking.get_trangThai_display()
    return {
        "is_group": is_group,
        "title": "Lịch cố định" if is_group else "Đặt sân vãng lai",
        "so_buoi": len(items) or 1,
        "ngay_bat_dau": first_item.ngayBatDau,
        "ngay_ket_thuc": last_item.ngayBatDau,
        "gio_bat_dau": first_item.gioBatDau,
        "gio_ket_thuc": first_item.gioKetThuc,
        "lich_tap": first_item.get_lich_tap_display() if is_group and first_item.lich_tap else "-",
        "san": first_item.san,
        "trang_thai": status_label,
        "don_gia": first_item.tongGiaTien,
        "tong_tien": total_money,
    }


def render_invoice_png(booking, items, total_money, approver=None, summary=None):
    ensure_pillow()
    load_fonts()
    summary = summary or build_summary_from_items(booking, items, total_money)
    height = 1120
    image = Image.new("RGB", (WIDTH, height), "#ffffff")
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, WIDTH, 162), fill=DARK)
    draw.rectangle((0, 148, WIDTH, 162), fill=GREEN)
    draw.text((PADDING, 28), "Cầu Lông Bạc Liêu", fill="#d1fae5", font=FONT_SUBTITLE)
    draw.text((PADDING, 58), "HÓA ĐƠN ĐẶT SÂN", fill="#ffffff", font=FONT_TITLE)
    draw.text((PADDING, 105), f"Mã đơn {booking_code(booking)}", fill="#d1d5db", font=FONT_SUBTITLE)

    created = booking.ngay_tao.strftime("%d/%m/%Y %H:%M") if booking.ngay_tao else "-"
    right_label = f"Ngày tạo: {created}"
    draw.text((WIDTH - PADDING - text_width(draw, right_label, FONT_SUBTITLE), 42), right_label, fill="#e5e7eb", font=FONT_SUBTITLE)
    type_label = summary["title"]
    draw.text((WIDTH - PADDING - text_width(draw, type_label, FONT_SUBTITLE), 76), type_label, fill="#d1fae5", font=FONT_SUBTITLE)

    y = 196
    card_gap = 18
    card_width = (WIDTH - PADDING * 2 - card_gap) // 2
    row_height = 104
    fields = [
        ("Tên khách hàng", booking.tenNguoiDat),
        ("Số điện thoại", booking.sdt),
        ("Chi nhánh", summary["san"].maChiNhanh.tenChiNhanh),
        ("Sân", summary["san"].tenSan),
        ("Trạng thái", summary["trang_thai"]),
        ("Người duyệt", approver_name(approver)),
        ("Số buổi", f"{summary['so_buoi']} buổi"),
        ("Nội dung chuyển khoản", booking.noi_dung_chuyen_khoan or "-"),
    ]

    for idx, (label, value) in enumerate(fields):
        col = idx % 2
        row = idx // 2
        x = PADDING + col * (card_width + card_gap)
        yy = y + row * (row_height + 14)
        draw_rounded(draw, (x, yy, x + card_width, yy + row_height), 14, LIGHT, BORDER)
        draw_label_value(draw, x + 18, yy + 18, label, value, card_width - 36)

    y += 4 * (row_height + 14) + 6
    draw.text((PADDING, y), "TÓM TẮT ĐẶT SÂN", fill=TEXT, font=FONT_TEXT_BOLD)
    y += 38
    draw_rounded(draw, (PADDING, y, WIDTH - PADDING, y + 118), 16, "#ecfdf3", "#bbf7d0")
    summary_fields = [
        ("Khoảng ngày", format_date_range(summary["ngay_bat_dau"], summary["ngay_ket_thuc"])),
        ("Khung giờ", f"{format_time(summary['gio_bat_dau'])} - {format_time(summary['gio_ket_thuc'])}"),
        ("Lịch tập", summary["lich_tap"]),
    ]
    summary_width = (WIDTH - PADDING * 2 - 48) // 3
    for index, (label, value) in enumerate(summary_fields):
        x = PADDING + 18 + index * (summary_width + 24)
        draw.text((x, y + 22), label.upper(), fill=GREEN, font=FONT_LABEL)
        for line_index, line in enumerate(wrap_text(draw, value, FONT_TEXT_BOLD, summary_width)):
            draw.text((x, y + 50 + line_index * 28), line, fill="#064e3b", font=FONT_TEXT_BOLD)

    y += 150
    draw_rounded(draw, (PADDING, y, WIDTH - PADDING, y + 48), 10, GREEN)
    headers = ["Hạng mục", "Thời gian", "Sân", "Buổi", "Đơn giá", "Thành tiền"]
    xs = [PADDING + 18, PADDING + 205, PADDING + 395, PADDING + 535, PADDING + 610, PADDING + 730]
    for x, header in zip(xs, headers):
        draw.text((x, y + 13), header, fill="#ffffff", font=FONT_LABEL)
    y += 56

    draw_rounded(draw, (PADDING, y, WIDTH - PADDING, y + 86), 8, "#ffffff", "#edf1f7")
    date_range = format_date_range(summary["ngay_bat_dau"], summary["ngay_ket_thuc"])
    time_range = f"{format_time(summary['gio_bat_dau'])} - {format_time(summary['gio_ket_thuc'])}"
    draw.text((xs[0], y + 18), summary["title"], fill=TEXT, font=FONT_SMALL)
    if summary["is_group"]:
        draw.text((xs[0], y + 44), "Đã gộp lịch cố định", fill=MUTED, font=FONT_SMALL)
    draw.text((xs[1], y + 18), date_range, fill=TEXT, font=FONT_SMALL)
    draw.text((xs[1], y + 44), time_range, fill=MUTED, font=FONT_SMALL)
    draw.text((xs[2], y + 18), summary["san"].tenSan, fill=TEXT, font=FONT_SMALL)
    draw.text((xs[3], y + 18), str(summary["so_buoi"]), fill=TEXT, font=FONT_SMALL)
    draw.text((xs[4], y + 18), money(summary["don_gia"]), fill=TEXT, font=FONT_SMALL)
    draw.text((xs[5], y + 18), money(total_money), fill=TEXT, font=FONT_SMALL)
    y += 106

    draw_rounded(draw, (PADDING, y, WIDTH - PADDING, y + 96), 16, "#ecfdf3", "#bbf7d0")
    draw.text((PADDING + 24, y + 23), "TỔNG CỘNG", fill=GREEN, font=FONT_LABEL)
    total_label = money(total_money)
    draw.text((WIDTH - PADDING - 24 - text_width(draw, total_label, FONT_TOTAL), y + 38), total_label, fill=GREEN, font=FONT_TOTAL)

    y += 126
    footer = "Vui lòng giữ hóa đơn này để đối chiếu khi cần hỗ trợ."
    draw.text(((WIDTH - text_width(draw, footer, FONT_SMALL)) // 2, y), footer, fill=MUTED, font=FONT_SMALL)

    final_height = min(height, y + 64)
    output = BytesIO()
    image.crop((0, 0, WIDTH, final_height)).save(output, format="PNG", optimize=True)
    output.seek(0)
    return output.getvalue()
