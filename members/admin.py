from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.db.models import Min, Sum
from .models import (
    NguoiDung, ChiNhanh, SanCauLong, 
    DatSan, BaiDang, HoiThoaiKhachHang, HoTro, 
    BinhLuan, ThongBao, CauHinhHeThong
)
from django.shortcuts import render, redirect
from .admin_forms import UpdatePriceForm

# =========================================================
# 1. BASE CLASSES
# =========================================================

class BranchBasedAdmin(admin.ModelAdmin):
    """Lọc dữ liệu dựa trên Chi nhánh mà Manager quản lý"""
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        
        if hasattr(request.user, 'chi_nhanh_quan_ly') and request.user.chi_nhanh_quan_ly:
            branch = request.user.chi_nhanh_quan_ly
            if self.model == ChiNhanh:
                return qs.filter(id=branch.id)
            if hasattr(self.model, 'maChiNhanh'):
                return qs.filter(maChiNhanh=branch)
            if hasattr(self.model, 'san'):
                return qs.filter(san__maChiNhanh=branch)
        return qs.none()

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and hasattr(request.user, 'chi_nhanh_quan_ly'):
            if hasattr(obj, 'maChiNhanh') and not obj.maChiNhanh:
                obj.maChiNhanh = request.user.chi_nhanh_quan_ly
        super().save_model(request, obj, form, change)


class ConsoleHiddenAdminMixin:
    def has_module_permission(self, request):
        return False


@admin.register(CauHinhHeThong)
class CauHinhHeThongAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Thương hiệu", {"fields": ("ten_website", "slogan", "mo_ta_trang_chu")}),
        ("Footer", {"fields": ("footer_dia_chi", "footer_hotline", "footer_email", "footer_ghi_chu")}),
        ("Hệ thống", {"fields": ("cap_nhat_luc",)}),
    )
    readonly_fields = ("cap_nhat_luc",)

    def has_add_permission(self, request):
        return not CauHinhHeThong.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

# =========================================================
# 2. QUẢN LÝ NGƯỜI DÙNG
# =========================================================

@admin.register(NguoiDung)
class NguoiDungAdmin(UserAdmin):
    list_display = ('avatar_thumb', 'sodienthoai', 'ten', 'role', 'chi_nhanh_quan_ly', 'is_active')
    list_filter = ('role', 'is_active', 'is_staff', 'is_superuser', 'groups', 'chi_nhanh_quan_ly')
    search_fields = ('sodienthoai', 'ten', 'username', 'email')
    ordering = ('-date_joined',)
    actions = ['activate_users', 'deactivate_users']
    filter_horizontal = ('groups', 'user_permissions')

    fieldsets = (
        ('Thông tin cá nhân', {'fields': ('sodienthoai', 'ten', 'email', 'avatar', 'dia_chi', 'diem_thuong')}),
        ('Phân quyền', {'fields': ('role', 'chi_nhanh_quan_ly', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Lịch sử', {'fields': ('last_login', 'date_joined')}),
    )
    readonly_fields = ('last_login', 'date_joined')

    def avatar_thumb(self, obj):
        if obj.avatar:
            return format_html('<img src="{}" style="width:35px; height:35px; border-radius:50%; object-fit:cover;"/>', obj.avatar.url)
        return "-"
    avatar_thumb.short_description = "Ảnh"

    @admin.action(description="🔓 Kích hoạt tài khoản")
    def activate_users(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="🔒 Khóa tài khoản")
    def deactivate_users(self, request, queryset):
        queryset.update(is_active=False)

# =========================================================
# 3. CHI NHÁNH & SÂN
# =========================================================

class SanCauLongInline(admin.TabularInline):
    model = SanCauLong
    extra = 0
    fields = ('tenSan', 'gia_thuong', 'gia_vang', 'gia_co_dinh', 'is_active')





@admin.register(ChiNhanh)
class ChiNhanhAdmin(BranchBasedAdmin): 
    list_display = ('hinh_anh_thumb', 'tenChiNhanh', 'tenQuanLy', 'sdt', 'thong_tin_ngan_hang', 'qr_thumb')
    inlines = [SanCauLongInline]
    readonly_fields = ('qr_thumb',)
    fieldsets = (
        ('Thông tin chi nhánh', {'fields': ('tenChiNhanh', 'diaChi', 'sdt', 'tenQuanLy', 'hinhAnh', 'moTa', 'linkMap')}),
        ('Thanh toán QR / Chuyển khoản', {'fields': ('ten_ngan_hang', 'so_tai_khoan', 'chu_tai_khoan', 'qr_thanh_toan', 'qr_thumb')}),
    )

    def hinh_anh_thumb(self, obj):
        if obj.hinhAnh:
            return format_html('<img src="{}" style="width:50px; border-radius:4px;" />', obj.hinhAnh.url)
        return "No Image"

    def qr_thumb(self, obj):
        if obj.qr_thanh_toan:
            return format_html('<img src="{}" style="width:80px; border-radius:4px;" />', obj.qr_thanh_toan.url)
        return "Chưa tải QR"
    qr_thumb.short_description = "QR"

    def thong_tin_ngan_hang(self, obj):
        if obj.so_tai_khoan:
            return format_html('{}<br><small>{}</small>', obj.ten_ngan_hang or "-", obj.so_tai_khoan)
        return "-"
    thong_tin_ngan_hang.short_description = "Ngân hàng"

@admin.register(SanCauLong)
class SanCauLongAdmin(BranchBasedAdmin): 
    list_display = ('tenSan', 'maChiNhanh', 'gia_thuong', 'gia_vang', 'gia_co_dinh', 'is_active')
    list_editable = ('is_active',)
    list_filter = ('maChiNhanh', 'is_active')
    search_fields = ('tenSan',)
    actions = ['update_price_by_type']

    @admin.action(description="💰 Cập nhật giá theo khung giờ")
    def update_price_by_type(self, request, queryset):
        if 'apply' in request.POST:
            form = UpdatePriceForm(request.POST)
            if form.is_valid():
                price_type = form.cleaned_data['price_type']
                price_value = form.cleaned_data['price_value'] * 1000  # 80 → 80.000đ

                queryset.update(**{price_type: price_value})

                self.message_user(
                    request,
                    f"Đã cập nhật {queryset.count()} sân – {price_type} = {price_value:,}đ"
                )
                return None

        else:
            form = UpdatePriceForm(
                initial={
                    '_selected_action': queryset.values_list('id', flat=True)
                }
            )

        return render(
            request,
            'admin/update_price.html',
            {
                'items': queryset,
                'form': form,
                'title': 'Cập nhật giá nhanh cho sân cầu lông'
            }
        )

# =========================================================
# 4. ĐẶT SÂN
# =========================================================

class GroupFilter(admin.SimpleListFilter):
    title = 'Chế độ xem'
    parameter_name = 'view_mode'
    def lookups(self, request, model_admin):
        return (('grouped', 'Gom nhóm đơn cố định'), ('detailed', 'Xem chi tiết tất cả'))

    def queryset(self, request, queryset):
        if self.value() == 'grouped' or self.value() is None:
            nhom_ids = queryset.filter(loaiDatSan=1).values('nhom_dat_san').annotate(first_id=Min('id')).values_list('first_id', flat=True)
            le_ids = queryset.filter(loaiDatSan=0).values_list('id', flat=True)
            return queryset.filter(id__in=list(nhom_ids) + list(le_ids))
        return queryset

@admin.register(DatSan)
class DatSanAdmin(ConsoleHiddenAdminMixin, BranchBasedAdmin):
    list_display = ('ma_don_hien_thi', 'khach_hang_info', 'thong_tin_san', 'thoi_gian_info', 'thanh_toan_info', 'nguoi_duyet', 'trang_thai_pills')
    list_filter = (GroupFilter, 'trangThai', 'daThanhToan', 'phuong_thuc_thanh_toan', 'loaiDatSan', 'san__maChiNhanh')
    search_fields = ('tenNguoiDat', 'sdt', 'nhom_dat_san', 'noi_dung_chuyen_khoan')
    actions = ['xac_nhan_don', 'huy_don', 'set_paid', 'set_unpaid']
    readonly_fields = ('noi_dung_chuyen_khoan', 'nguoi_duyet')

    # --- LOGIC XÓA CẢ NHÓM ---
    def delete_model(self, request, obj):
        if obj.loaiDatSan == 1 and obj.nhom_dat_san:
            DatSan.objects.filter(nhom_dat_san=obj.nhom_dat_san).delete()
        else:
            obj.delete()

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            if obj.loaiDatSan == 1 and obj.nhom_dat_san:
                DatSan.objects.filter(nhom_dat_san=obj.nhom_dat_san).delete()
            else:
                obj.delete()

    # --- HIỂN THỊ ---
    def ma_don_hien_thi(self, obj):
        if obj.loaiDatSan == 1:
            return format_html('<b style="color:#2980b9;">CỐ ĐỊNH</b><br><small>#{}</small>', str(obj.nhom_dat_san)[:8])
        return format_html('<b style="color:#27ae60;">VÃNG LAI</b><br><small>#{}</small>', obj.id)

    def thanh_toan_info(self, obj):
        val = obj.tongGiaTien
        if obj.loaiDatSan == 1:
            val = DatSan.objects.filter(nhom_dat_san=obj.nhom_dat_san).aggregate(Sum('tongGiaTien'))['tongGiaTien__sum'] or 0
        formatted_price = "{:,.0f}".format(float(val))
        color = "#27ae60" if obj.daThanhToan else "#e74c3c"
        return format_html(
            '<b style="color: {};">{}đ</b><br><small>{}</small>',
            color,
            formatted_price,
            obj.get_phuong_thuc_thanh_toan_display(),
        )

    def trang_thai_pills(self, obj):
        colors = {'pending': '#f39c12', 'confirmed': '#27ae60', 'cancelled': '#e74c3c', 'completed': '#2980b9'}
        label = dict(DatSan.TRANG_THAI_CHOICES).get(obj.trangThai, 'N/A').upper()
        return format_html('<span style="background:{}; color:white; padding:3px 8px; border-radius:10px; font-size:10px; font-weight:bold;">{}</span>', colors.get(obj.trangThai, '#95a5a6'), label)

    # --- ACTIONS ---
    @admin.action(description="💳 Đã thanh toán")
    def set_paid(self, request, queryset):
        for obj in queryset:
            target = DatSan.objects.filter(nhom_dat_san=obj.nhom_dat_san) if obj.loaiDatSan == 1 else DatSan.objects.filter(id=obj.id)
            target.update(daThanhToan=True)

    @admin.action(description="⚠️ Chưa thanh toán")
    def set_unpaid(self, request, queryset):
        for obj in queryset:
            target = DatSan.objects.filter(nhom_dat_san=obj.nhom_dat_san) if obj.loaiDatSan == 1 else DatSan.objects.filter(id=obj.id)
            target.update(daThanhToan=False)

    @admin.action(description="✅ Duyệt đơn")
    def xac_nhan_don(self, request, queryset):
        for obj in queryset:
            target = DatSan.objects.filter(nhom_dat_san=obj.nhom_dat_san) if obj.loaiDatSan == 1 else DatSan.objects.filter(id=obj.id)
            target.update(trangThai='confirmed', nguoi_duyet=request.user)
            ThongBao.objects.create(nguoi_nhan=obj.nguoi_dat, tieu_de="Thành công", noi_dung=f"Sân {obj.san.tenSan} đã được duyệt.")

    def save_model(self, request, obj, form, change):
        if obj.trangThai == 'confirmed' and not obj.nguoi_duyet_id:
            obj.nguoi_duyet = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="❌ Hủy đơn")
    def huy_don(self, request, queryset):
        for obj in queryset:
            target = DatSan.objects.filter(nhom_dat_san=obj.nhom_dat_san) if obj.loaiDatSan == 1 else DatSan.objects.filter(id=obj.id)
            target.update(trangThai='cancelled')

    def khach_hang_info(self, obj):
        return format_html('<b>{}</b><br>{}', obj.tenNguoiDat, obj.sdt)
    
    def thong_tin_san(self, obj):
        return format_html('{}', obj.san.tenSan)

    def thoi_gian_info(self, obj):
        if obj.loaiDatSan == 0:
            return format_html('📅 {}<br>⏰ {}-{}', obj.ngayBatDau.strftime('%d/%m'), obj.gioBatDau.strftime('%H:%M'), obj.gioKetThuc.strftime('%H:%M'))
        count = DatSan.objects.filter(nhom_dat_san=obj.nhom_dat_san).count()
        return format_html('<b>Lịch cố định</b><br>({} buổi)', count)

# =========================================================
# 5. DIỄN ĐÀN & HỖ TRỢ
# =========================================================

class HoTroInline(admin.TabularInline):
    model = HoTro
    extra = 1
    fields = ('cau_hoi', 'ngay_gui', 'tra_loi', 'admin_tra_loi', 'nguon_tra_loi', 'yeu_cau_admin', 'ngay_tra_loi', 'da_xem')
    readonly_fields = ('ngay_gui', 'ngay_tra_loi')
    ordering = ('ngay_gui',)

@admin.register(HoiThoaiKhachHang)
class HoiThoaiKhachHangAdmin(ConsoleHiddenAdminMixin, admin.ModelAdmin):
    list_display = ('trang_thai_chat', 'ten', 'sodienthoai', 'chi_nhanh', 'admin_phu_trach', 'can_admin', 'so_tin_chua_doc', 'tin_cuoi', 'ngay_tao')
    search_fields = ('ten', 'sodienthoai', 'nguoi_dung__ten', 'nguoi_dung__sodienthoai', 'tieu_de', 'chi_nhanh__tenChiNhanh', 'admin_phu_trach__ten')
    list_filter = ('ngay_tao', 'can_admin', 'chi_nhanh', 'admin_phu_trach')
    ordering = ('-ngay_tao',)
    actions = ['mark_as_read']
    inlines = [HoTroInline]

    def trang_thai_chat(self, obj):
        has_new = obj.hotro_set.filter(da_xem=False).exists()
        return mark_safe('<b style="color:red;">● MỚI</b>') if has_new else "Đã xem"

    def so_tin_chua_doc(self, obj):
        return obj.hotro_set.filter(da_xem=False).count()
    so_tin_chua_doc.short_description = "Tin chưa đọc"

    def tin_cuoi(self, obj):
        last = obj.hotro_set.order_by('-ngay_gui').first()
        return last.ngay_gui if last else "-"
    tin_cuoi.short_description = "Tin cuối"

    @admin.action(description="✔️ Đánh dấu đã xem")
    def mark_as_read(self, request, queryset):
        for obj in queryset:
            obj.hotro_set.filter(da_xem=False).update(da_xem=True)

@admin.register(BaiDang)
class BaiDangAdmin(ConsoleHiddenAdminMixin, admin.ModelAdmin):
    list_display = ('tieu_de', 'nguoi_dang', 'duyet_bai', 'ngay_dang')
    list_editable = ('duyet_bai',)
    list_filter = ('duyet_bai',)

@admin.register(ThongBao)
class ThongBaoAdmin(ConsoleHiddenAdminMixin, admin.ModelAdmin):
    list_display = ('nguoi_nhan', 'tieu_de', 'is_read', 'created_at')
