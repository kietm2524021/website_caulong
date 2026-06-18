from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import (
    NguoiDung, BaiDang, DatSan, HoTro, 
    SanCauLong, BinhLuan
)
from .security import normalize_plain_text, validate_uploaded_file

# =========================================
# 1. FORM ĐĂNG KÝ (Đã bỏ Email)
# =========================================
class DangKyForm(UserCreationForm):
    class Meta:
        model = NguoiDung
        # Chỉ hiển thị Tên và SĐT (Email & Username tự động xử lý ở View)
        fields = ('ten', 'sodienthoai')
        widgets = {
            'ten': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập họ và tên đầy đủ'}),
            'sodienthoai': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập số điện thoại (10-11 số)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Loại bỏ help text mặc định của Django cho đỡ rối
        if 'sodienthoai' in self.fields:
            self.fields['sodienthoai'].help_text = None

    def clean_ten(self):
        ten = normalize_plain_text(self.cleaned_data.get("ten"), max_length=120, field_label="Họ và tên")
        if len(ten) < 2:
            raise forms.ValidationError("Họ và tên phải có ít nhất 2 ký tự.")
        return ten

    def clean_sodienthoai(self):
        sodienthoai = "".join((self.cleaned_data.get("sodienthoai") or "").split())
        if not sodienthoai.isdigit() or not 10 <= len(sodienthoai) <= 11:
            raise forms.ValidationError("Số điện thoại phải gồm 10-11 chữ số.")
        return sodienthoai

# =========================================
# 2. FORM ĐĂNG NHẬP
# =========================================
class DangNhapForm(forms.Form):
    sodienthoai = forms.CharField(
        label="Số điện thoại",
        max_length=15,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập SĐT đã đăng ký', 'autofocus': 'True'})
    )
    matkhau = forms.CharField(
        label="Mật khẩu",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Nhập mật khẩu'})
    )

    def clean_sodienthoai(self):
        sodienthoai = "".join((self.cleaned_data.get("sodienthoai") or "").split())
        if not sodienthoai.isdigit() or not 10 <= len(sodienthoai) <= 11:
            raise forms.ValidationError("Số điện thoại không hợp lệ.")
        return sodienthoai

# =========================================
# 3. FORM ĐẶT SÂN (NÂNG CẤP TÍNH NĂNG TUYỂN)
# =========================================
class DatSanForm(forms.ModelForm):
    # --- CÁC TRƯỜNG THỜI GIAN (Flatpickr) ---
    ngayBatDau = forms.DateField(
        widget=forms.TextInput(attrs={
            'class': 'form-control readonly-input', 
            'id': 'id_ngayBatDau', 
            'placeholder': 'Chọn ngày bắt đầu...', 
            'readonly': 'readonly'
        })
    )
    ngayKetThuc = forms.DateField(
        required=False, 
        widget=forms.TextInput(attrs={
            'class': 'form-control readonly-input', 
            'id': 'id_ngayKetThuc', 
            'placeholder': 'Ngày kết thúc chu kỳ...', 
            'readonly': 'readonly'
        })
    )
    gioBatDau = forms.TimeField(
        widget=forms.TextInput(attrs={
            'class': 'form-control readonly-input', 
            'id': 'id_gioBatDau', 
            'placeholder': '-- : --', 
            'readonly': 'readonly'
        })
    )
    gioKetThuc = forms.TimeField(
        widget=forms.TextInput(attrs={
            'class': 'form-control readonly-input', 
            'id': 'id_gioKetThuc', 
            'placeholder': '-- : --', 
            'readonly': 'readonly'
        })
    )

    # --- TÍNH NĂNG TUYỂN THÀNH VIÊN ---
    tuyenThanhVien = forms.BooleanField(
        required=False,
        label="Bật tìm người giao lưu",
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input', 
            'role': 'switch',
            'id': 'id_tuyenThanhVien'
        })
    )
    soLuongTuyen = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=10,
        label="Số lượng cần",
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 
            'id': 'id_soLuongTuyen',
            'placeholder': 'VD: 1'
        })
    )
    ghi_chu_tuyen = forms.CharField(
        required=False,
        label="Ghi chú (Kèo/Phí)",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'VD: Giao lưu vui vẻ, chia đều tiền sân.'
        })
    )

    class Meta:
        model = DatSan
        fields = [
            'san', 'loaiDatSan', 'lich_tap', 'ngayBatDau', 
            'ngayKetThuc', 'gioBatDau', 'gioKetThuc',
            'tuyenThanhVien', 'soLuongTuyen', 'trinh_do_can', 'ghi_chu_tuyen'
        ]
        widgets = {
            'san': forms.Select(attrs={'class': 'form-select', 'id': 'id_san'}),
            'loaiDatSan': forms.Select(attrs={'class': 'form-select', 'id': 'id_loaiDatSan'}),
            'lich_tap': forms.Select(attrs={'class': 'form-select', 'id': 'id_lich_tap'}),
            'trinh_do_can': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['san'].queryset = SanCauLong.objects.filter(is_active=True).select_related('maChiNhanh')
        if not self.is_bound:
            self.fields['soLuongTuyen'].initial = 1
            self.fields['trinh_do_can'].initial = 'yeu'
            self.fields['ghi_chu_tuyen'].initial = 'Giao lưu vui vẻ, chia đều tiền sân.'

    def clean(self):
        cleaned_data = super().clean()
        tuyen = cleaned_data.get("tuyenThanhVien")
        so_luong = cleaned_data.get("soLuongTuyen")
        loai_dat = cleaned_data.get("loaiDatSan")
        lich_tap = cleaned_data.get("lich_tap")
        ngay_bat_dau = cleaned_data.get("ngayBatDau")
        ngay_ket_thuc = cleaned_data.get("ngayKetThuc")
        gio_bat_dau = cleaned_data.get("gioBatDau")
        gio_ket_thuc = cleaned_data.get("gioKetThuc")

        if gio_bat_dau and gio_ket_thuc:
            start_minutes = gio_bat_dau.hour * 60 + gio_bat_dau.minute
            end_minutes = gio_ket_thuc.hour * 60 + gio_ket_thuc.minute
            if end_minutes - start_minutes < 30:
                self.add_error('gioKetThuc', "Giờ kết thúc phải sau giờ bắt đầu ít nhất 30 phút.")

        if loai_dat == 1:
            if not lich_tap:
                self.add_error('lich_tap', "Vui lòng chọn lịch tập cố định.")
            if not ngay_ket_thuc:
                self.add_error('ngayKetThuc', "Vui lòng chọn ngày kết thúc.")
            elif ngay_bat_dau and ngay_ket_thuc < ngay_bat_dau:
                self.add_error('ngayKetThuc', "Ngày kết thúc không được trước ngày bắt đầu.")

        # Nếu bật tuyển thành viên thì bắt buộc phải nhập số lượng
        if tuyen and not so_luong:
            self.add_error('soLuongTuyen', "Vui lòng nhập số lượng người cần tuyển.")
        elif not tuyen:
            cleaned_data["soLuongTuyen"] = 0
        
        return cleaned_data

# =========================================
# 4. FORM DIỄN ĐÀN
# =========================================
class BaiDangForm(forms.ModelForm):
    class Meta:
        model = BaiDang
        fields = ['tieu_de', 'noi_dung', 'hinh_anh', 'file_dinh_kem']
        widgets = {
            'tieu_de': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Tiêu đề bài viết...'}),
            'noi_dung': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Nội dung chi tiết...'}),
            'hinh_anh': forms.FileInput(attrs={'class': 'form-control'}),
            'file_dinh_kem': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def clean_tieu_de(self):
        return normalize_plain_text(self.cleaned_data.get("tieu_de"), max_length=200, field_label="Tiêu đề")

    def clean_noi_dung(self):
        return normalize_plain_text(self.cleaned_data.get("noi_dung"), max_length=5000, field_label="Nội dung")

    def clean_hinh_anh(self):
        return validate_uploaded_file(
            self.cleaned_data.get("hinh_anh"),
            allowed_extensions={".jpg", ".jpeg", ".png", ".webp"},
            allowed_content_types={"image/jpeg", "image/png", "image/webp"},
            max_size=5 * 1024 * 1024,
            field_label="Ảnh minh họa",
        )

    def clean_file_dinh_kem(self):
        return validate_uploaded_file(
            self.cleaned_data.get("file_dinh_kem"),
            allowed_extensions={".pdf"},
            allowed_content_types={"application/pdf"},
            max_size=10 * 1024 * 1024,
            field_label="Tài liệu đính kèm",
        )

# =========================================
# 5. FORM HỖ TRỢ (Chat)
# =========================================
class HoTroForm(forms.ModelForm):
    class Meta:
        model = HoTro
        fields = ['cau_hoi']
        widgets = {
            'cau_hoi': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập tin nhắn hỗ trợ...',
                'autocomplete': 'off'
            })
        }

    def clean_cau_hoi(self):
        return normalize_plain_text(self.cleaned_data.get("cau_hoi"), max_length=1000, field_label="Tin nhắn hỗ trợ")

# =========================================
# 6. FORM BÌNH LUẬN
# =========================================
class BinhLuanForm(forms.ModelForm):
    class Meta:
        model = BinhLuan
        fields = ['noi_dung']
        widgets = {
            'noi_dung': forms.Textarea(attrs={
                'class': 'form-control shadow-sm',
                'rows': 2,
                'placeholder': 'Viết bình luận...',
                'style': 'resize: none; border-radius: 15px;'
            })
        }

    def clean_noi_dung(self):
        return normalize_plain_text(self.cleaned_data.get("noi_dung"), max_length=1000, field_label="Bình luận")

# =========================================
# 7. FORM ĐĂNG TIN TUYỂN QUÂN (Dùng cho trang Tuyển riêng)
# =========================================
