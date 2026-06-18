import logging
import os
import unicodedata

import requests
from django.conf import settings


logger = logging.getLogger("security")

HANDOFF_MARKER = "HANDOFF_ADMIN"

ADMIN_KEYWORDS = {
    "admin",
    "nhan vien",
    "nguoi that",
    "quan ly",
    "goi lai",
    "lien he truc tiep",
    "gap truc tiep",
    "khieu nai",
    "khan",
    "khan cap",
    "hoan tien",
}

ABBREVIATION_MAP = {
    "k": "khong",
    "ko": "khong",
    "kh": "khong",
    "hok": "khong",
    "dc": "duoc",
    "đc": "duoc",
    "hn": "hom nay",
    "hnay": "hom nay",
    "tmr": "ngay mai",
    "ad": "admin",
}

SYSTEM_KEYWORDS = {
    "dat san",
    "dat lich",
    "lich san",
    "san trong",
    "con san",
    "co san",
    "san nao",
    "mo cua",
    "hoat dong",
    "toi nay",
    "cuoi tuan",
    "danh khong",
    "choi khong",
    "dang choi",
    "dang danh",
    "chi tiet lich",
    "ghi chu",
    "nguoi dang ky",
    "dong nguoi",
    "hom nay",
    "ngay mai",
    "trung lich",
    "gio vang",
    "gia san",
    "bang gia",
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
THANKS_KEYWORDS = {"cam on", "cam on nhe", "thanks", "thank you"}
GOODBYE_KEYWORDS = {"tam biet", "bye", "gap lai sau"}
IDENTITY_KEYWORDS = {"ban la ai", "ban co the lam gi"}
IGNORE_KEYWORDS = {"bo qua", "nhap nham", "cau hoi truoc"}

GENERIC_SYSTEM_REPLY = (
    "Mình có thể hỗ trợ các câu hỏi về đặt sân, kiểm tra trùng lịch, cọc sân, chuyển khoản QR, "
    "hóa đơn, tài khoản và diễn đàn. Bạn cứ nêu rõ chi nhánh, sân, ngày hoặc thao tác đang gặp vướng nhé."
)

OUT_OF_SCOPE_REPLY = (
    "Mình là AI hỗ trợ hệ thống đặt sân nên chỉ trả lời các câu hỏi liên quan đến đặt sân, lịch sân, "
    "giá sân, cọc chuyển khoản, hóa đơn, tài khoản và diễn đàn. Nếu bạn cần người thật hỗ trợ, hãy bấm "
    "nút gặp quản lý chi nhánh."
)


def normalize_text(value):
    text = (value or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    words = []
    for word in text.lower().strip().split():
        words.append(ABBREVIATION_MAP.get(word, word))
    return " ".join(words)


def wants_admin_reply(message):
    normalized = normalize_text(message)
    return any(keyword in normalized for keyword in ADMIN_KEYWORDS)


def looks_system_related(message):
    normalized = normalize_text(message)
    return any(keyword in normalized for keyword in SYSTEM_KEYWORDS)


def fallback_reply(message):
    normalized = normalize_text(message)

    if any(keyword in normalized for keyword in IGNORE_KEYWORDS):
        return "Không sao, mình đã bỏ qua câu trước. Bạn cứ gửi lại câu hỏi mới khi cần hỗ trợ nhé."

    if normalized in THANKS_KEYWORDS or any(keyword in normalized for keyword in THANKS_KEYWORDS):
        return "Không có gì. Mình luôn sẵn sàng hỗ trợ bạn về đặt sân, lịch sân, tuyển thành viên và tài khoản."

    if normalized in GOODBYE_KEYWORDS or any(keyword in normalized for keyword in GOODBYE_KEYWORDS):
        return "Tạm biệt bạn. Khi cần kiểm tra sân trống hoặc hỗ trợ đặt sân, bạn cứ mở lại khung chat nhé."

    if any(keyword in normalized for keyword in IDENTITY_KEYWORDS):
        return (
            "Mình là AI hỗ trợ của hệ thống Cầu Lông Bạc Liêu. "
            "Mình có thể kiểm tra sân trống, lịch sân, lịch tuyển thành viên, hướng dẫn đặt sân, tài khoản và diễn đàn."
        )

    if normalized in GREETING_KEYWORDS or any(normalized.startswith(f"{word} ") for word in GREETING_KEYWORDS):
        return (
            "Mình đây. Bạn có thể hỏi nhanh như: hôm nay còn sân trống không, giá sân bao nhiêu, "
            "cách đặt cọc, cách hủy đơn hoặc cần gặp quản lý chi nhánh."
        )

    if any(word in normalized for word in {"website", "chuc nang", "huong dan", "buoc dat san", "he thong hoat dong", "dung de lam gi"}):
        return (
            "Website dùng để xem chi nhánh, đặt sân, theo dõi lịch sử đặt sân, nhận yêu cầu đặt cọc, tải hóa đơn, "
            "đăng bài diễn đàn, tìm lịch đang tuyển thành viên và nhắn hỗ trợ. "
            "Luồng đặt sân là: chọn sân và khung giờ, gửi yêu cầu, quản lý gửi yêu cầu cọc, khách xác nhận chuyển khoản, rồi quản lý duyệt đơn."
        )

    if any(word in normalized for word in {"qr", "chuyen khoan", "thanh toan", "coc", "dat coc"}):
        return (
            "Sau khi quản lý gửi yêu cầu đặt cọc, hệ thống sẽ hiện thông tin đơn, mã QR và nội dung chuyển khoản để bạn sao chép nhanh. "
            "Bạn chuyển khoản xong thì bấm 'Đã chuyển khoản' để quản lý đối soát và duyệt đơn."
        )

    if any(word in normalized for word in {"dat san", "dat lich", "trung lich", "lich san"}):
        return (
            "Khi bạn gửi yêu cầu đặt sân, hệ thống sẽ kiểm tra trùng lịch đúng theo từng sân, ngày và khung giờ trước khi tạo đơn chờ duyệt. "
            "Đơn sau đó sẽ nằm trong lịch sử đặt sân để bạn theo dõi hoặc hủy/xóa khi cần."
        )

    if any(word in normalized for word in {"gio vang", "gia san", "gia", "vang lai"}):
        return (
            "Giá vãng lai đang tính theo mốc trước 17h là giờ vàng, từ 17h trở đi là giờ thường. "
            "Lịch cố định dùng mức giá cố định riêng của sân."
        )

    if any(word in normalized for word in {"hoa don", "xuat hoa don"}):
        return (
            "Sau khi đơn được quản lý xác nhận, bạn có thể xem và tải hóa đơn. "
            "Hóa đơn gồm tên khách hàng, chi nhánh, sân, khung giờ, trạng thái đặt và người duyệt."
        )

    if any(word in normalized for word in {
        "dang ky", "dang nhap", "mat khau", "tai khoan", "anh dai dien",
        "thong tin ca nhan", "xoa tai khoan", "dang xuat"
    }):
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
        return (
            "Bạn đăng nhập bằng số điện thoại đã đăng ký. "
            "Nếu tài khoản bị khóa tạm thời do nhập sai nhiều lần hoặc cần đổi thông tin, bạn hãy nhắn rõ tình trạng để hệ thống hướng dẫn tiếp."
        )

    if any(word in normalized for word in {"dang bai", "binh luan", "tim kiem bai viet"}):
        return (
            "Bạn vào diễn đàn để đăng bài, xem bài viết và bình luận. "
            "Nếu muốn tìm bài, hãy dùng ô tìm kiếm theo tiêu đề hoặc nội dung liên quan như đồng đội, giao lưu, tuyển thành viên."
        )

    if any(word in normalized for word in {
        "bai viet", "dien dan", "tuyen", "tuyen thanh vien", "tuyen nguoi",
        "tim nguoi", "tim thanh vien", "can nguoi", "giao luu", "keo danh",
        "danh chung", "choi chung"
    }):
        return (
            "Các lịch có bật tuyển thành viên sẽ hiển thị trong lịch cộng đồng. "
            "Bạn có thể hỏi theo ngày hoặc chi nhánh, ví dụ 'ngày mai có sân nào tuyển thành viên không', "
            "hoặc tự đặt sân rồi bật tuyển thành viên cho kèo của mình."
        )

    if any(word in normalized for word in {"huy don", "xoa don", "huy san"}):
        return (
            "Đơn đang chờ duyệt có thể hủy, và các đơn chờ duyệt hoặc đã hủy có thể xóa để làm gọn danh sách. "
            "Nếu đơn đã được xác nhận mà cần thay đổi, bạn nên yêu cầu quản lý hỗ trợ trực tiếp."
        )

    if looks_system_related(message):
        return GENERIC_SYSTEM_REPLY

    return None


def is_greeting(message):
    normalized = normalize_text(message)
    return normalized in GREETING_KEYWORDS or any(normalized.startswith(f"{word} ") for word in GREETING_KEYWORDS)


def extract_response_text(data):
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()

    chunks = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def get_setting(name, default=None):
    env_value = os.getenv(name)
    if env_value is not None:
        return env_value
    return getattr(settings, name, default)


def build_support_instructions():
    return (
        "Bạn là trợ lý hỗ trợ khách hàng cho website đặt sân cầu lông. "
        "Chỉ trả lời các câu hỏi liên quan đến hệ thống như đặt sân, lịch sân, kiểm tra trùng lịch, giờ vàng, giá, "
        "luồng cọc sân, chuyển khoản, QR, hóa đơn, tài khoản, diễn đàn, tuyển thành viên/giao lưu và hỗ trợ sử dụng website. "
        "Quy tắc hệ thống hiện tại: khách gửi yêu cầu đặt sân trước, quản lý gửi yêu cầu đặt cọc sau, "
        "khách bấm xác nhận đã chuyển khoản, rồi quản lý đối soát để duyệt đơn. "
        "Giá vãng lai: trước 17h là giờ vàng, từ 17h trở đi là giờ thường. "
        f"Nếu khách yêu cầu người thật/admin, khiếu nại, hoàn tiền, hoặc hỏi ngoài phạm vi hệ thống thì chỉ trả về {HANDOFF_MARKER}. "
        "Trả lời ngắn gọn, lịch sự, bằng tiếng Việt, tối đa 4 câu."
    )


def call_ai_model(message):
    enabled = str(get_setting("AI_SUPPORT_ENABLED", "True")).lower() in {"1", "true", "yes", "on"}
    api_key = get_setting("AI_SUPPORT_API_KEY") or get_setting("OPENAI_API_KEY")
    if not enabled:
        return None
    if not api_key:
        logger.info("AI support skipped because no API key is configured.")
        return None

    api_url = get_setting("AI_SUPPORT_API_URL", "https://api.openai.com/v1/responses")
    model = get_setting("AI_SUPPORT_MODEL", "gpt-5.5")
    timeout = int(get_setting("AI_SUPPORT_TIMEOUT", 12))
    payload = {
        "model": model,
        "instructions": build_support_instructions(),
        "input": message,
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
    return reply


def tao_phan_hoi_ho_tro(message):
    if wants_admin_reply(message):
        return None, "admin", True

    if is_greeting(message):
        return fallback_reply(message), "ai", False

    if not looks_system_related(message):
        return OUT_OF_SCOPE_REPLY, "ai", False

    return call_ai_model(message) or fallback_reply(message), "ai", False
