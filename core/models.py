import os
import re
import unicodedata
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator

# =========================================
# 1. MODEL NGƯỜI DÙNG (CUSTOM USER)
# =========================================
def random_upload_path(prefix, filename):
    extension = os.path.splitext(filename or "")[1].lower()
    return f"{prefix}/{uuid.uuid4().hex}{extension}"


def avatar_upload_to(instance, filename):
    return random_upload_path("avatars", filename)


def branch_image_upload_to(instance, filename):
    return random_upload_path("chinhanh", filename)


def branch_qr_upload_to(instance, filename):
    return random_upload_path("payments/qr", filename)


def forum_image_upload_to(instance, filename):
    return random_upload_path("diendan/images", filename)


def forum_file_upload_to(instance, filename):
    return random_upload_path("diendan/files", filename)


class CauHinhHeThong(models.Model):
    ten_website = models.CharField("Tên website", max_length=120, default="Cầu Lông Bạc Liêu")
    slogan = models.CharField(
        "Slogan",
        max_length=255,
        default="Đặt sân nhanh, chơi cầu vui.",
    )
    mo_ta_trang_chu = models.TextField(
        "Mô tả trang chủ",
        default="Nền tảng đặt sân cầu lông tại Bạc Liêu, giúp khách hàng theo dõi lịch sân và kết nối với quản lý dễ dàng.",
    )
    footer_dia_chi = models.CharField("Địa chỉ footer", max_length=255, default="Bạc Liêu, Việt Nam")
    footer_hotline = models.CharField("Hotline footer", max_length=30, default="Đang cập nhật")
    footer_email = models.EmailField("Email footer", blank=True, default="")
    footer_ghi_chu = models.CharField(
        "Ghi chú footer",
        max_length=255,
        default="Hệ thống hỗ trợ đặt sân, quản lý lịch và chăm sóc khách hàng.",
    )
    cap_nhat_luc = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return None

    def __str__(self):
        return self.ten_website

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    class Meta:
        verbose_name = "Cấu hình hệ thống"
        verbose_name_plural = "Cấu hình hệ thống"


class NguoiDung(AbstractUser):
    VAI_TRO_CHOICES = [
        ('customer', 'Khách hàng'),
        ('staff', 'Nhân viên sân'),
        ('manager', 'Quản lý chi nhánh'),
    ]
    sodienthoai = models.CharField("Số điện thoại", max_length=15, unique=True)
    ten = models.CharField("Họ và tên", max_length=255)
    role = models.CharField("Vai trò", max_length=20, choices=VAI_TRO_CHOICES, default='customer')
    avatar = models.ImageField("Ảnh đại diện", upload_to=avatar_upload_to, null=True, blank=True)
    diem_thuong = models.IntegerField("Điểm thưởng", default=0)
    dia_chi = models.CharField("Địa chỉ", max_length=255, null=True, blank=True)
    is_phone_verified = models.BooleanField("Đã xác thực SĐT", default=False)
    failed_login_attempts = models.PositiveSmallIntegerField("Số lần đăng nhập sai", default=0)
    locked_until = models.DateTimeField("Khóa đến", null=True, blank=True)
    chi_nhanh_quan_ly = models.ForeignKey(
        'ChiNhanh', 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        verbose_name="Quản lý chi nhánh"
    )
    USERNAME_FIELD = 'sodienthoai'
    REQUIRED_FIELDS = ['username', 'ten']

    def __str__(self):
        return f"{self.ten} ({self.sodienthoai})"

    class Meta:
        verbose_name = "Người dùng"
        verbose_name_plural = "Quản lý Người dùng"


# =========================================
# 2. QUẢN LÝ SÂN BÃI
# =========================================
class ChiNhanh(models.Model):
    tenChiNhanh = models.CharField("Tên chi nhánh", max_length=255)
    diaChi = models.CharField("Địa chỉ", max_length=255)
    sdt = models.CharField("Hotline", max_length=15)
    tenQuanLy = models.CharField("Tên quản lý", max_length=100)
    hinhAnh = models.ImageField("Hình ảnh", upload_to=branch_image_upload_to, null=True, blank=True)
    moTa = models.TextField("Mô tả", null=True, blank=True)
    linkMap = models.URLField("Link Google Map", null=True, blank=True)
    ten_ngan_hang = models.CharField("Ngân hàng", max_length=100, blank=True)
    so_tai_khoan = models.CharField("Số tài khoản", max_length=50, blank=True)
    chu_tai_khoan = models.CharField("Chủ tài khoản", max_length=150, blank=True)
    qr_thanh_toan = models.ImageField("Mã QR thanh toán", upload_to=branch_qr_upload_to, null=True, blank=True)

    def __str__(self):
        return self.tenChiNhanh

    class Meta:
        verbose_name = "Chi nhánh"
        verbose_name_plural = "Quản lý Chi nhánh"


class SanCauLong(models.Model):
    maChiNhanh = models.ForeignKey(ChiNhanh, on_delete=models.CASCADE, verbose_name="Thuộc chi nhánh", related_name="ds_san")
    tenSan = models.CharField("Tên sân", max_length=100)
    
    # 3 LOẠI GIÁ CHÍNH (Đơn vị: VNĐ/Giờ)
    gia_vang = models.DecimalField(
        "Giá giờ VÀNG", max_digits=10, decimal_places=0, default=50000,
        help_text="Áp dụng cho khách vãng lai trước 17h"
    )
    
    gia_thuong = models.DecimalField(
        "Giá giờ THƯỜNG", max_digits=10, decimal_places=0, default=80000,
        help_text="Áp dụng cho khách vãng lai từ 17h trở đi"
    )
    
    gia_co_dinh = models.DecimalField(
        "Giá CỐ ĐỊNH", max_digits=10, decimal_places=0, default=40000,
        help_text="Giá ưu đãi dành cho khách đặt lịch cố định/tháng"
    )
    is_active = models.BooleanField("Đang hoạt động", default=True)
    moTa = models.TextField("Mô tả thêm", blank=True, null=True)
    
    def __str__(self):
        return f"{self.tenSan} - {self.maChiNhanh.tenChiNhanh}"

    class Meta:
        verbose_name = "Sân cầu lông"
        verbose_name_plural = "Quản lý Sân"


# =========================================
# 3. ĐẶT SÂN (KÈM TÍNH NĂNG TUYỂN QUÂN)
# =========================================
class DatSan(models.Model):
    TRANG_THAI_CHOICES = [
        ('pending', 'Chờ xác nhận'),
        ('confirmed', 'Đã xác nhận'),
        ('cancelled', 'Đã hủy'),
        ('completed', 'Đã hoàn thành'),
    ]
    LOAI_DAT_CHOICES = [(0, 'Vãng lai (Theo giờ)'), (1, 'Cố định (Theo tháng)')]
    PAYMENT_CHOICES = [
        ('cash', 'Tiền mặt'),
        ('qr', 'Quét mã QR'),
        ('bank', 'Chuyển khoản'),
        ('momo', 'Ví MoMo'),
    ]
    LICH_TAP_CHOICES = [
        ('246', 'Thứ 2 - 4 - 6'),
        ('357', 'Thứ 3 - 5 - 7'),
        ('full', 'Cả tuần (T2 - CN)'),
        ('246cn', 'Thứ 2 - 4 - 6 - CN'),
        ('357cn','Thứ 3 - 5- 7 - CN'),
    ]
    TRINH_DO_CHOICES = [
        ('yeu', 'Yếu / Mới chơi'),
        ('tb', 'Trung bình'),
        ('kha', 'Khá'),
        ('gioi', 'Giỏi / Chuyên nghiệp'),
    ]

    nguoi_dat = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="Khách hàng")
    san = models.ForeignKey(SanCauLong, on_delete=models.CASCADE, verbose_name="Sân đặt")
    nhom_dat_san = models.UUIDField("Mã nhóm", default=uuid.uuid4, editable=False, null=True, blank=True)
    
    # Thời gian
    ngayBatDau = models.DateField("Ngày chơi")
    ngayKetThuc = models.DateField("Ngày kết thúc đợt", null=True, blank=True)
    gioBatDau = models.TimeField("Giờ bắt đầu")
    gioKetThuc = models.TimeField("Giờ kết thúc")
    lich_tap = models.CharField("Lịch tập", max_length=20, choices=LICH_TAP_CHOICES, null=True, blank=True)
    
    # --- TÍNH NĂNG TUYỂN THÀNH VIÊN (TÍCH HỢP) ---
    tuyenThanhVien = models.BooleanField("Bật tuyển thành viên giao lưu", default=False)
    soLuongTuyen = models.IntegerField("Số lượng cần tuyển", 
                                       validators=[MinValueValidator(0), MaxValueValidator(10)], 
                                       default=0, null=True, blank=True)
    trinh_do_can = models.CharField("Trình độ mong muốn", max_length=20, 
                                    choices=TRINH_DO_CHOICES, default='tb', null=True, blank=True)
    ghi_chu_tuyen = models.TextField("Ghi chú tuyển (Phí/Kèo)", null=True, blank=True)

    # Thanh toán & Check-in
    tongGiaTien = models.DecimalField("Tổng tiền", max_digits=12, decimal_places=0)
    daThanhToan = models.BooleanField("Đã thanh toán", default=False)
    phuong_thuc_thanh_toan = models.CharField("Thanh toán qua", max_length=20, choices=PAYMENT_CHOICES, default='bank')
    noi_dung_chuyen_khoan = models.CharField("Nội dung chuyển khoản", max_length=255, blank=True)
    yeu_cau_thanh_toan = models.BooleanField("Đã gửi yêu cầu thanh toán", default=False)
    ngay_gui_yeu_cau_thanh_toan = models.DateTimeField("Ngày gửi yêu cầu thanh toán", null=True, blank=True)
    ngay_khach_mo_thanh_toan = models.DateTimeField("Ngày khách mở yêu cầu thanh toán", null=True, blank=True)
    khach_xac_nhan_chuyen_khoan = models.BooleanField("Khách đã bấm đã chuyển khoản", default=False)
    ngay_khach_xac_nhan_ck = models.DateTimeField("Ngày khách xác nhận chuyển khoản", null=True, blank=True)
    so_tien_coc = models.DecimalField("Số tiền cọc", max_digits=12, decimal_places=0, default=0)
    da_checkin = models.BooleanField("Khách đã đến sân", default=False)
    
    loaiDatSan = models.IntegerField("Loại hình đặt", choices=LOAI_DAT_CHOICES, default=0)
    trangThai = models.CharField("Trạng thái", max_length=20, choices=TRANG_THAI_CHOICES, default='pending')
    ly_do_huy = models.TextField("Lý do hủy (nếu có)", blank=True, null=True)
    ngay_tao = models.DateTimeField(auto_now_add=True)

    # Snapshot thông tin
    tenNguoiDat = models.CharField("Tên người đặt", max_length=255, blank=True)
    sdt = models.CharField("SĐT liên hệ", max_length=15, blank=True)
    nguoi_duyet = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='don_dat_san_da_duyet',
        verbose_name="Người duyệt",
    )

    def tao_noi_dung_chuyen_khoan(self, tien_coc=None):
        if not (self.ngayBatDau and self.gioBatDau and self.san_id):
            return ""

        source = self
        if self.pk and self.loaiDatSan == 1 and self.nhom_dat_san:
            source = (
                type(self).objects.filter(nhom_dat_san=self.nhom_dat_san)
                .select_related("san__maChiNhanh", "nguoi_dat")
                .order_by("ngayBatDau", "gioBatDau", "id")
                .first()
                or self
            )

        ten_khach = source.tenNguoiDat or (
            source.nguoi_dat.ten if source.nguoi_dat else "KHACH"
        )
        ten_san = source.san.tenSan
        ten_chi_nhanh = source.san.maChiNhanh.tenChiNhanh
        ngay_format = source.ngayBatDau.strftime("%d%m%y")
        gio_format = source.gioBatDau.strftime("%H%M")

        def normalize_part(value):
            normalized = unicodedata.normalize(
                "NFD", str(value).replace("đ", "d").replace("Đ", "D")
            )
            without_accents = "".join(
                char for char in normalized if unicodedata.category(char) != "Mn"
            )
            return re.sub(r"[^A-Za-z0-9]+", "", without_accents).upper()

        def abbreviate_branch(value):
            normalized = unicodedata.normalize(
                "NFD", str(value).replace("đ", "d").replace("Đ", "D")
            )
            without_accents = "".join(
                char for char in normalized if unicodedata.category(char) != "Mn"
            )
            tokens = re.findall(r"[A-Za-z]+|\d+", without_accents.upper())
            abbreviation = "".join(token if token.isdigit() else token[0] for token in tokens)
            return abbreviation or "CN"

        parts = (
            normalize_part(ten_khach),
            abbreviate_branch(ten_chi_nhanh),
            normalize_part(ten_san),
            gio_format,
            ngay_format,
        )
        return "_".join(parts)

    def tinh_tien_coc_mac_dinh(self):
        if self.loaiDatSan == 1:
            return Decimal("10000")
        start = datetime.combine(self.ngayBatDau, self.gioBatDau)
        end = datetime.combine(self.ngayBatDau, self.gioKetThuc)
        hours = Decimal(str((end - start).total_seconds())) / Decimal("3600")
        return (hours * Decimal("10000")).quantize(Decimal("1"))

    @property
    def han_thanh_toan(self):
        if not self.ngay_khach_mo_thanh_toan:
            return None
        return self.ngay_khach_mo_thanh_toan + timedelta(minutes=15)

    @property
    def yeu_cau_thanh_toan_het_han(self):
        return bool(
            self.yeu_cau_thanh_toan
            and not self.khach_xac_nhan_chuyen_khoan
            and self.han_thanh_toan
            and timezone.now() >= self.han_thanh_toan
        )

    @property
    def so_tien_con_lai(self):
        return max(Decimal(self.tongGiaTien or 0) - Decimal(self.so_tien_coc or 0), Decimal("0"))

    @property
    def trang_thai_coc(self):
        if self.trangThai == "cancelled":
            return "Đã hủy"
        if self.daThanhToan and self.trangThai in {"confirmed", "completed"}:
            return "Đã xác nhận cọc"
        if self.khach_xac_nhan_chuyen_khoan:
            return "Chờ quản lý xác nhận cọc"
        if self.yeu_cau_thanh_toan_het_han:
            return "Yêu cầu đặt cọc đã hết hạn"
        if self.yeu_cau_thanh_toan:
            return "Có yêu cầu đặt cọc mới" if not self.ngay_khach_mo_thanh_toan else "Chờ khách chuyển cọc"
        return "Chờ quản lý xem yêu cầu"

    def save(self, *args, **kwargs):
        if not self.tenNguoiDat and self.nguoi_dat:
            self.tenNguoiDat = self.nguoi_dat.ten
        if not self.sdt and self.nguoi_dat:
            self.sdt = self.nguoi_dat.sodienthoai
        if not self.so_tien_coc and self.tongGiaTien:
            self.so_tien_coc = self.tinh_tien_coc_mac_dinh()
        self.noi_dung_chuyen_khoan = self.tao_noi_dung_chuyen_khoan()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Đơn #{self.id} - {self.san} ({self.ngayBatDau})"

    class Meta:
        verbose_name = "Đơn đặt sân"
        verbose_name_plural = "Quản lý Đặt sân"
        ordering = ['-ngay_tao']


# =========================================
# 4. HỆ THỐNG THÔNG BÁO
# =========================================
class ThongBao(models.Model):
    LOAI_CHOICES = [
        ('booking', 'Đặt sân'),
        ('post', 'Bài viết'),
        ('support', 'Hỗ trợ'),
        ('payment', 'Thanh toán'),
        ('system', 'Hệ thống'),
    ]
    nguoi_nhan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="thong_bao")
    tieu_de = models.CharField(max_length=255)
    noi_dung = models.TextField()
    loai = models.CharField("Loại thông báo", max_length=20, choices=LOAI_CHOICES, default='system')
    duong_dan = models.CharField("Đường dẫn xử lý", max_length=500, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Thông báo"
        verbose_name_plural = "Thông báo hệ thống"
        ordering = ['-created_at']


# =========================================
# 5. DIỄN ĐÀN & BÀI ĐĂNG
# =========================================
class BaiDang(models.Model):
    nguoi_dang = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="Người đăng")
    tieu_de = models.CharField("Tiêu đề", max_length=255)
    noi_dung = models.TextField("Nội dung chi tiết")
    hinh_anh = models.ImageField("Hình ảnh minh họa", upload_to=forum_image_upload_to, null=True, blank=True)
    file_dinh_kem = models.FileField("Tài liệu (PDF)", upload_to=forum_file_upload_to, null=True, blank=True)
    
    ngay_dang = models.DateTimeField("Ngày đăng", auto_now_add=True)
    duyet_bai = models.BooleanField("Đã duyệt", default=False)
    luot_xem = models.IntegerField("Lượt xem", default=0)
    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="liked_posts", blank=True)

    def __str__(self): return self.tieu_de

    class Meta:
        verbose_name = "Bài viết diễn đàn"
        verbose_name_plural = "Quản lý Diễn đàn"
        ordering = ['-ngay_dang']


class BinhLuan(models.Model):
    bai_dang = models.ForeignKey(BaiDang, on_delete=models.CASCADE, related_name='binh_luan_set', verbose_name="Bài viết")
    nguoi_binh_luan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="Người bình luận")
    noi_dung = models.TextField("Nội dung")
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies', verbose_name="Trả lời cho")
    ngay_tao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nguoi_binh_luan.ten}: {self.noi_dung[:20]}"

    class Meta:
        verbose_name = "Bình luận"
        verbose_name_plural = "Quản lý Bình luận"
        ordering = ['ngay_tao']


# =========================================
# 6. HỖ TRỢ KHÁCH HÀNG
# =========================================
class HoiThoaiKhachHang(models.Model):
    nguoi_dung = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="Khách hàng")
    tieu_de = models.CharField("Chủ đề", max_length=255, default="Hỗ trợ chung")
    chi_nhanh = models.ForeignKey(
        ChiNhanh,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hoi_thoai_ho_tro',
        verbose_name="Chi nhánh hỗ trợ",
    )
    admin_phu_trach = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hoi_thoai_phu_trach',
        verbose_name="Admin phụ trách",
    )
    can_admin = models.BooleanField("Cần admin chi nhánh xử lý", default=False)
    da_dong = models.BooleanField("Đã đóng hội thoại", default=False)
    last_admin_request_at = models.DateTimeField("Lần yêu cầu admin gần nhất", null=True, blank=True)
    ngay_tao = models.DateTimeField(auto_now_add=True)
    ten = models.CharField(max_length=255, blank=True)
    sodienthoai = models.CharField(max_length=15, blank=True)

    def save(self, *args, **kwargs):
        if self.nguoi_dung:
            self.ten = self.nguoi_dung.ten
            self.sodienthoai = self.nguoi_dung.sodienthoai
        super().save(*args, **kwargs)
    
    def __str__(self): return f"Hỗ trợ: {self.ten}"

    class Meta:
        verbose_name = "Hội thoại hỗ trợ"
        verbose_name_plural = "Danh sách Hội thoại"


class HoTro(models.Model):
    NGUON_TRA_LOI_CHOICES = [
        ('admin', 'Admin'),
        ('ai', 'AI'),
    ]
    NGUOI_GUI_CHOICES = [
        ('customer', 'Khach hang'),
        ('admin', 'Admin'),
    ]

    hoi_thoai = models.ForeignKey(HoiThoaiKhachHang, on_delete=models.CASCADE, related_name='hotro_set')
    nguoi_dung = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    nguoi_gui = models.CharField("Nguoi gui", max_length=20, choices=NGUOI_GUI_CHOICES, default='customer')
    cau_hoi = models.TextField("Tin nhắn")
    tra_loi = models.TextField("Phản hồi Admin", null=True, blank=True)
    admin_tra_loi = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='phan_hoi_ho_tro',
        verbose_name="Admin trả lời",
    )
    nguon_tra_loi = models.CharField("Nguồn phản hồi", max_length=20, choices=NGUON_TRA_LOI_CHOICES, default='admin')
    yeu_cau_admin = models.BooleanField("Khách yêu cầu admin", default=False)
    ngay_gui = models.DateTimeField(auto_now_add=True)
    ngay_tra_loi = models.DateTimeField(null=True, blank=True)
    da_xem = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.tra_loi and not self.ngay_tra_loi:
            self.ngay_tra_loi = timezone.now()
            self.da_xem = True
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Tin nhắn chi tiết"
        verbose_name_plural = "Chi tiết Tin nhắn"


# =========================================
# 7. TUYỂN THÀNH VIÊN (MODEL RIÊNG - RAO VẶT)
# =========================================
class TuyenThanhVien(models.Model):
    TRINH_DO_CHOICES = [
        ('yeu', 'Yếu / Mới chơi'),
        ('tb', 'Trung bình'),
        ('kha', 'Khá'),
        ('gioi', 'Giỏi / Chuyên nghiệp'),
    ]
    
    nguoi_dang = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="Người đăng")
    tieu_de = models.CharField("Tiêu đề", max_length=255)
    khu_vuc = models.CharField("Khu vực", max_length=255, blank=True, null=True)
    san_choi = models.CharField("Sân chơi (nếu có)", max_length=255, blank=True, null=True)
    
    trinh_do = models.CharField("Trình độ yêu cầu", max_length=20, choices=TRINH_DO_CHOICES, default='tb')
    thoi_gian = models.CharField("Thời gian", max_length=255, blank=True, null=True)
    chi_phi = models.CharField("Chi phí", max_length=255, blank=True, null=True)
    so_luong_can = models.IntegerField("Số lượng cần tuyển", default=1)
    
    sdt_lien_he = models.CharField("SĐT liên hệ", max_length=15)
    mo_ta = models.TextField("Mô tả thêm", blank=True, null=True)
    
    ngay_dang = models.DateTimeField(auto_now_add=True)
    da_du = models.BooleanField("Đã đủ người", default=False)

    def __str__(self): return self.tieu_de

    class Meta:
        verbose_name = "Tin tuyển thành viên"
        verbose_name_plural = "Quản lý Tuyển quân (Rao vặt)"
        ordering = ['-ngay_dang']
