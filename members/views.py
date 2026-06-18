import uuid
import json
import re
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from datetime import datetime, date, timedelta
from django.db import transaction
from django.db.models import Q, Min, Max, Sum, Prefetch
from django.http import JsonResponse, Http404, HttpResponse
from django.views.decorators.http import require_POST
from decimal import Decimal

from .models import (
    SanCauLong, DatSan, BaiDang, HoiThoaiKhachHang, 
    HoTro, ChiNhanh, BinhLuan, NguoiDung, ThongBao
)
from .forms import (
    DangNhapForm, DangKyForm, DatSanForm, 
    BaiDangForm, HoTroForm, BinhLuanForm
)
from .invoice_image import render_invoice_png
from .notifications import notify_admins
from .security import (
    build_lockout_message,
    get_client_ip,
    is_user_locked,
    normalize_plain_text,
    register_failed_login,
    reset_login_failures,
)
from .support_chat import create_customer_message, serialize_customer_state


logger = logging.getLogger("security")

# ==========================================
# LOGIC TÍNH TIỀN THEO 3 LOẠI GIÁ MỚI
# ==========================================
def natural_sort_key(value):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', value or '')]


def tinh_tien_chi_tiet(san, loai_dat, gio_bd, gio_kt):
    """
    Tính tiền dựa trên 3 loại giá:
    - loai_dat = 1 (Cố định): Áp dụng san.gia_co_dinh (đơn giá ưu đãi).
    - loai_dat = 0 (Vãng lai): Phân loại Giờ Vàng (7h-17h) và giờ Thường.
    """
    start = Decimal(gio_bd.hour) + Decimal(gio_bd.minute) / 60
    end = Decimal(gio_kt.hour) + Decimal(gio_kt.minute) / 60
    duration = end - start
    if duration <= 0: return 0
    
    # 1. TRƯỜNG HỢP ĐẶT CỐ ĐỊNH: Một mức giá duy nhất cho mọi khung giờ
    if int(loai_dat) == 1:
        return duration * san.gia_co_dinh

    # 2. TRƯỜNG HỢP ĐẶT VÃNG LAI: Bóc tách giờ cao điểm
    GOLD_START, GOLD_END = Decimal(0), Decimal(17)
    
    overlap_start = max(start, GOLD_START)
    overlap_end = min(end, GOLD_END)
    thoi_gian_vang = max(Decimal(0), overlap_end - overlap_start)
    
    thoi_gian_thuong = duration - thoi_gian_vang
    
    tong = (thoi_gian_vang * san.gia_vang) + (thoi_gian_thuong * san.gia_thuong)
    return tong


LICH_TAP_DAY_MAP = {
    '246': [0, 2, 4],
    '357': [1, 3, 5],
    'full': [0, 1, 2, 3, 4, 5, 6],
    '246cn': [0, 2, 4, 6],
    '357cn': [1, 3, 5, 6],
}


def tao_danh_sach_ngay_co_dinh(ngay_bd, ngay_kt, lich_tap):
    target_days = LICH_TAP_DAY_MAP.get(lich_tap, [])
    ds_ngay = []
    curr = ngay_bd
    while curr <= ngay_kt:
        if curr.weekday() in target_days:
            ds_ngay.append(curr)
        curr += timedelta(days=1)
    return ds_ngay


def tim_lich_trung(san, ds_ngay, gio_bd, gio_kt):
    return DatSan.objects.select_for_update().filter(
        san=san,
        ngayBatDau__in=ds_ngay,
        trangThai__in=['confirmed', 'pending'],
    ).filter(Q(gioBatDau__lt=gio_kt) & Q(gioKetThuc__gt=gio_bd))


def dat_san_context(form, san_chon):
    return {'form': form, 'san_chon': san_chon}


def booking_target_queryset(booking):
    if booking.loaiDatSan == 1 and booking.nhom_dat_san:
        return DatSan.objects.filter(nhom_dat_san=booking.nhom_dat_san)
    return DatSan.objects.filter(id=booking.id)

# ==========================================
# TRANG CHỦ & AUTHENTICATION
# ==========================================
def home(request):
    ds_chinhanh = list(ChiNhanh.objects.prefetch_related(
        Prefetch('ds_san', queryset=SanCauLong.objects.filter(is_active=True), to_attr='san_hien_thi')
    ).all())
    ds_chinhanh.sort(key=lambda branch: natural_sort_key(branch.tenChiNhanh))
    for branch in ds_chinhanh:
        branch.san_hien_thi = sorted(branch.san_hien_thi, key=lambda court: natural_sort_key(court.tenSan))
    
    ds_bai_dang = BaiDang.objects.filter(duyet_bai=True).order_by('-ngay_dang')[:3]
    
    ds_don_gan_day = []
    if request.user.is_authenticated:
        today = timezone.now().date()
        all_user_orders = DatSan.objects.filter(
            nguoi_dat=request.user, 
            ngayBatDau__gte=today,
            trangThai__in=['confirmed', 'pending'] 
        ).select_related('san').order_by('ngayBatDau', 'gioBatDau')[:30] 

        seen_groups = set()
        for item in all_user_orders:
            if len(ds_don_gan_day) >= 3: break 
            
            if item.loaiDatSan == 0:
                ds_don_gan_day.append({
                    'is_group': False, 'san_ten': item.san.tenSan, 
                    'ngay_hien_thi': item.ngayBatDau, 'gio_hien_thi': item.gioBatDau, 
                    'trang_thai': item.get_trangThai_display(), 'status_code': item.trangThai
                })
            else:
                if item.nhom_dat_san in seen_groups: continue
                next_slot = DatSan.objects.filter(nhom_dat_san=item.nhom_dat_san, ngayBatDau__gte=today, trangThai__in=['confirmed', 'pending']).order_by('ngayBatDau', 'gioBatDau').first()
                if not next_slot: continue
                ds_don_gan_day.append({
                    'is_group': True, 'san_ten': item.san.tenSan, 'ngay_hien_thi': next_slot.ngayBatDau, 'gio_hien_thi': next_slot.gioBatDau, 
                    'lich_tap': item.get_lich_tap_display(), 'trang_thai': item.get_trangThai_display(), 'status_code': item.trangThai, 
                })
                seen_groups.add(item.nhom_dat_san)

    return render(request, 'home.html', {'ds_chinhanh': ds_chinhanh, 'ds_bai_dang': ds_bai_dang, 'ds_don_gan_day': ds_don_gan_day})

def login_view(request):
    if request.user.is_authenticated: return redirect('home')
    form_login = DangNhapForm(prefix='login')
    form_register = DangKyForm(prefix='register')
    active_tab = 'login'
    client_ip = get_client_ip(request)
    
    if request.method == 'POST':
        if 'btn_login' in request.POST:
            form_login = DangNhapForm(request.POST, prefix='login')
            if form_login.is_valid():
                sodienthoai = form_login.cleaned_data['sodienthoai']
                matkhau = form_login.cleaned_data['matkhau']
                existing_user = NguoiDung.objects.filter(sodienthoai=sodienthoai).first()
                if existing_user and is_user_locked(existing_user):
                    logger.warning("Locked account login attempt user=%s ip=%s", existing_user.pk, client_ip)
                    messages.error(request, build_lockout_message(existing_user))
                    return render(request, 'login.html', {'form_login': form_login, 'form_register': form_register, 'active_tab': active_tab})

                user = authenticate(request, username=sodienthoai, password=matkhau)
                if user: 
                    reset_login_failures(user)
                    login(request, user)
                    request.session['last_activity_ts'] = int(timezone.now().timestamp())
                    logger.info("Successful login user=%s ip=%s", user.pk, client_ip)
                    messages.success(request, f"Chào mừng {user.ten}!")
                    return redirect('home')
                if existing_user:
                    locked = register_failed_login(existing_user)
                    logger.warning("Failed login user=%s ip=%s", existing_user.pk, client_ip)
                    if locked:
                        messages.error(request, build_lockout_message(existing_user))
                    else:
                        messages.error(request, "Sai số điện thoại hoặc mật khẩu.")
                else:
                    logger.warning("Failed login unknown_phone=%s ip=%s", sodienthoai, client_ip)
                    messages.error(request, "Sai số điện thoại hoặc mật khẩu.")
        elif 'btn_register' in request.POST:
            active_tab = 'register'
            form_register = DangKyForm(request.POST, prefix='register')
            if form_register.is_valid():
                user = form_register.save(commit=False)
                user.username = user.sodienthoai
                user.email = f"{user.sodienthoai}@gmail.com" 
                user.save()
                logger.info("Account registered user=%s ip=%s", user.pk, client_ip)
                messages.success(request, "Đăng ký thành công! Vui lòng đăng nhập.")
                return redirect(reverse('login') + f"?registered_sdt={user.sodienthoai}")
            else:
                messages.error(request, "Lỗi đăng ký. Vui lòng kiểm tra lại.")
    return render(request, 'login.html', {'form_login': form_login, 'form_register': form_register, 'active_tab': active_tab})

def logout_view(request):
    logout(request)
    request.session.flush()
    return redirect('login')

# ==========================================
# QUẢN LÝ ĐẶT SÂN
# ==========================================
@login_required(login_url='login')
def dat_san_view(request):
    san_id = request.GET.get('san_id') or request.POST.get('san')
    if not san_id:
        messages.error(request, "Vui lòng chọn sân trước khi đặt.")
        return redirect('home')
    if san_id and not san_id.isdigit():
        messages.error(request, "Sân không hợp lệ.")
        return redirect('home')
    san_chon = get_object_or_404(
        SanCauLong.objects.select_related('maChiNhanh'),
        id=int(san_id),
        is_active=True,
    )
    
    if request.method == 'POST':
        form = DatSanForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            san = data['san']; loai = int(data['loaiDatSan']); ngay_bd = data['ngayBatDau']
            gio_bd = data['gioBatDau']; gio_kt = data['gioKetThuc']
            phuong_thuc = 'bank'
            if san.id != san_chon.id:
                messages.error(request, "Sân đặt không khớp với sân đang chọn.")
                return render(request, 'dat_san.html', dat_san_context(form, san_chon))

            with transaction.atomic():
                if loai == 0:
                    tien_1_buoi = tinh_tien_chi_tiet(san, 0, gio_bd, gio_kt)
                    conflicts = tim_lich_trung(san, [ngay_bd], gio_bd, gio_kt)
                    if conflicts.exists():
                        messages.error(request, "Khung giờ này đã có người đặt.")
                        return render(request, 'dat_san.html', dat_san_context(form, san_chon))

                    booking = DatSan.objects.create(
                        nguoi_dat=request.user,
                        san=san,
                        ngayBatDau=ngay_bd,
                        gioBatDau=gio_bd,
                        gioKetThuc=gio_kt,
                        tongGiaTien=tien_1_buoi,
                        loaiDatSan=0,
                        nhom_dat_san=uuid.uuid4(),
                        tenNguoiDat=request.user.ten,
                        sdt=request.user.sodienthoai,
                        phuong_thuc_thanh_toan=phuong_thuc,
                        tuyenThanhVien=data.get('tuyenThanhVien', False),
                        soLuongTuyen=data.get('soLuongTuyen', 0),
                        trinh_do_can=data.get('trinh_do_can'),
                        ghi_chu_tuyen=data.get('ghi_chu_tuyen', ''),
                    )
                    notify_admins(
                        title=f"{request.user.ten} đã gửi yêu cầu đặt sân",
                        message=f"{san.tenSan}, ngày {ngay_bd:%d/%m/%Y}, {gio_bd:%H:%M}-{gio_kt:%H:%M}.",
                        category="booking",
                        link=f"{reverse('admin_bookings')}?q={request.user.sodienthoai}",
                        branch=san.maChiNhanh,
                    )
                    messages.success(request, "Đã gửi yêu cầu đặt sân vãng lai đến quản lý.")
                    return redirect('lich_su_dat_san')

                ngay_kt = data.get('ngayKetThuc')
                if not ngay_kt:
                    messages.error(request, "Vui lòng chọn ngày kết thúc.")
                    return render(request, 'dat_san.html', dat_san_context(form, san_chon))

                ds_ngay = tao_danh_sach_ngay_co_dinh(ngay_bd, ngay_kt, data.get('lich_tap'))
                if not ds_ngay:
                    messages.error(request, "Không có ngày nào phù hợp.")
                    return render(request, 'dat_san.html', dat_san_context(form, san_chon))

                conflicts = tim_lich_trung(san, ds_ngay, gio_bd, gio_kt)
                if conflicts.exists():
                    ngay_trung = sorted({c.ngayBatDau.strftime('%d/%m') for c in conflicts})
                    messages.error(request, f"Trùng lịch các ngày: {', '.join(ngay_trung)}")
                    return render(request, 'dat_san.html', dat_san_context(form, san_chon))
                
                nhom_id = uuid.uuid4()
                tien_co_dinh = tinh_tien_chi_tiet(san, 1, gio_bd, gio_kt)
                objs = []
                for ngay_dat in ds_ngay:
                    don = DatSan(
                        nguoi_dat=request.user,
                        san=san,
                        ngayBatDau=ngay_dat,
                        gioBatDau=gio_bd,
                        gioKetThuc=gio_kt,
                        tongGiaTien=tien_co_dinh,
                        loaiDatSan=1,
                        nhom_dat_san=nhom_id,
                        tenNguoiDat=request.user.ten,
                        sdt=request.user.sodienthoai,
                        lich_tap=data.get('lich_tap'),
                        phuong_thuc_thanh_toan=phuong_thuc,
                        tuyenThanhVien=data.get('tuyenThanhVien', False),
                        soLuongTuyen=data.get('soLuongTuyen', 0),
                        trinh_do_can=data.get('trinh_do_can'),
                        ghi_chu_tuyen=data.get('ghi_chu_tuyen', ''),
                    )
                    don.noi_dung_chuyen_khoan = don.tao_noi_dung_chuyen_khoan()
                    objs.append(don)

                DatSan.objects.bulk_create(objs)
                notify_admins(
                    title=f"{request.user.ten} đã gửi yêu cầu đặt sân cố định",
                    message=f"{san.tenSan}, {len(objs)} buổi từ {ngay_bd:%d/%m/%Y} đến {ngay_kt:%d/%m/%Y}.",
                    category="booking",
                    link=f"{reverse('admin_bookings')}?q={request.user.sodienthoai}",
                    branch=san.maChiNhanh,
                )
                messages.success(request, f"Đã gửi yêu cầu cho {len(objs)} buổi cố định. Tổng tạm tính: {int(tien_co_dinh * len(objs)):,}đ")
                return redirect('lich_su_dat_san')
    else:
        form = DatSanForm(initial={'san': san_chon, 'loaiDatSan': 0})
    return render(request, 'dat_san.html', dat_san_context(form, san_chon))

@login_required(login_url='login')
def lich_su_dat_san(request):  
    raw_orders = DatSan.objects.filter(nguoi_dat=request.user).select_related('san', 'san__maChiNhanh').order_by('ngayBatDau', 'gioBatDau') 
    grouped_history = []; seen_groups = set(); today = timezone.now().date()
    for item in raw_orders:
        if item.loaiDatSan == 0:
            is_upcoming = item.ngayBatDau >= today and item.trangThai in ['confirmed', 'pending']
            grouped_history.append({
                'is_group': False,
                'obj': item,
                'invoice_id': item.id,
                'sort_date': item.ngayBatDau,
                'sort_branch': item.san.maChiNhanh.tenChiNhanh,
                'sort_court': item.san.tenSan,
                'sort_time': item.gioBatDau,
                'is_upcoming': is_upcoming,
                'ngay_bat_dau': item.ngayBatDau,
                'san': item.san,
                'tong_tien': item.tongGiaTien,
                'trang_thai': item.trangThai,
                'trang_thai_coc': item.trang_thai_coc,
                'so_tien_coc': item.so_tien_coc,
                'so_tien_con_lai': item.so_tien_con_lai,
                'co_the_huy': item.trangThai == 'pending',
                'co_the_mo_thanh_toan': item.trangThai == 'pending' and item.yeu_cau_thanh_toan and not item.khach_xac_nhan_chuyen_khoan and not item.yeu_cau_thanh_toan_het_han,
                'show_invoice': item.trangThai in {'confirmed', 'completed'},
            })
        elif item.nhom_dat_san not in seen_groups:
            group_items = DatSan.objects.filter(nhom_dat_san=item.nhom_dat_san).select_related('san', 'san__maChiNhanh')
            first_date = group_items.aggregate(Min('ngayBatDau'))['ngayBatDau__min']; last_date = group_items.aggregate(Max('ngayBatDau'))['ngayBatDau__max']; total_money = group_items.aggregate(Sum('tongGiaTien'))['tongGiaTien__sum']; total_deposit = group_items.aggregate(Sum('so_tien_coc'))['so_tien_coc__sum'] or Decimal('0'); count = group_items.count()
            is_upcoming = last_date >= today and item.trangThai in ['confirmed', 'pending']
            first_item = group_items.order_by('ngayBatDau', 'gioBatDau').first()
            grouped_history.append({
                'is_group': True,
                'ma_don': str(item.nhom_dat_san)[:8],
                'invoice_id': first_item.id if first_item else item.id,
                'sort_date': first_date,
                'sort_branch': item.san.maChiNhanh.tenChiNhanh,
                'sort_court': item.san.tenSan,
                'sort_time': item.gioBatDau,
                'is_upcoming': is_upcoming,
                'san': item.san,
                'ngay_bat_dau': first_date,
                'ngay_ket_thuc': last_date,
                'gio_bat_dau': item.gioBatDau,
                'gio_ket_thuc': item.gioKetThuc,
                'tong_tien': total_money,
                'so_buoi': count,
                'trang_thai': item.trangThai,
                'lich_tap': item.get_lich_tap_display(),
                'noi_dung_chuyen_khoan': item.noi_dung_chuyen_khoan,
                'trang_thai_coc': item.trang_thai_coc,
                'so_tien_coc': total_deposit,
                'so_tien_con_lai': max(total_money - total_deposit, Decimal('0')),
                'co_the_huy': item.trangThai == 'pending',
                'co_the_mo_thanh_toan': item.trangThai == 'pending' and item.yeu_cau_thanh_toan and not item.khach_xac_nhan_chuyen_khoan and not item.yeu_cau_thanh_toan_het_han,
                'show_invoice': item.trangThai in {'confirmed', 'completed'},
            })
            seen_groups.add(item.nhom_dat_san)
    grouped_history.sort(key=lambda x: (x['sort_date'].toordinal(), x['sort_branch'], x['sort_court'], x['sort_time']))
    return render(request, 'lich_su.html', {'grouped_history': grouped_history})


@login_required(login_url='login')
@require_POST
def mo_yeu_cau_dat_coc(request, booking_id):
    booking = get_object_or_404(DatSan, id=booking_id, nguoi_dat=request.user)
    if booking.trangThai != 'pending' or not booking.yeu_cau_thanh_toan or booking.khach_xac_nhan_chuyen_khoan:
        messages.error(request, "Yêu cầu đặt cọc này không còn khả dụng.")
        return redirect('lich_su_dat_san')
    if booking.yeu_cau_thanh_toan_het_han:
        messages.error(request, "Yêu cầu đặt cọc đã hết hạn. Vui lòng chờ quản lý gửi lại yêu cầu mới.")
        return redirect('lich_su_dat_san')
    target = booking_target_queryset(booking)
    if not booking.ngay_khach_mo_thanh_toan:
        target.update(ngay_khach_mo_thanh_toan=timezone.now())
    return redirect('chi_tiet_dat_coc', booking_id=booking.id)


@login_required(login_url='login')
def chi_tiet_dat_coc(request, booking_id):
    booking = get_object_or_404(
        DatSan.objects.select_related('san', 'san__maChiNhanh'),
        id=booking_id,
        nguoi_dat=request.user,
    )
    if not booking.yeu_cau_thanh_toan or not booking.ngay_khach_mo_thanh_toan:
        messages.error(request, "Vui lòng mở yêu cầu đặt cọc từ Lịch sử đặt sân.")
        return redirect('lich_su_dat_san')

    target = booking_target_queryset(booking)
    total_price = target.aggregate(total=Sum('tongGiaTien'))['total'] or Decimal('0')
    total_deposit = target.aggregate(total=Sum('so_tien_coc'))['total'] or Decimal('0')
    context = {
        'booking': booking,
        'is_group': booking.loaiDatSan == 1 and bool(booking.nhom_dat_san),
        'so_buoi': target.count(),
        'tong_tien': total_price,
        'so_tien_coc': total_deposit,
        'so_tien_con_lai': max(total_price - total_deposit, Decimal('0')),
        'han_thanh_toan': booking.han_thanh_toan,
        'het_han': booking.yeu_cau_thanh_toan_het_han,
        'co_the_xac_nhan': booking.trangThai == 'pending' and not booking.khach_xac_nhan_chuyen_khoan and not booking.yeu_cau_thanh_toan_het_han,
    }
    return render(request, 'chi_tiet_dat_coc.html', context)


@login_required(login_url='login')
@require_POST
def huy_yeu_cau_dat_san(request, booking_id):
    booking = get_object_or_404(DatSan, id=booking_id, nguoi_dat=request.user)
    if booking.trangThai != 'pending':
        messages.error(request, "Chỉ có thể hủy đơn đang chờ duyệt.")
        return redirect('lich_su_dat_san')
    booking_target_queryset(booking).update(
        trangThai='cancelled',
        yeu_cau_thanh_toan=False,
        ngay_khach_mo_thanh_toan=None,
        khach_xac_nhan_chuyen_khoan=False,
    )
    messages.success(request, "Đã gửi yêu cầu hủy đơn đặt sân.")
    return redirect('lich_su_dat_san')


@login_required(login_url='login')
@require_POST
def xoa_yeu_cau_dat_san(request, booking_id):
    booking = get_object_or_404(DatSan, id=booking_id, nguoi_dat=request.user)
    if booking.trangThai not in {'pending', 'cancelled'}:
        messages.error(request, "Chỉ có thể xóa đơn chưa hoàn tất hoặc đã hủy.")
        return redirect('lich_su_dat_san')
    booking_target_queryset(booking).delete()
    messages.success(request, "Đã xóa yêu cầu đặt sân khỏi danh sách.")
    return redirect('lich_su_dat_san')


@login_required(login_url='login')
@require_POST
def xac_nhan_da_chuyen_khoan(request, booking_id):
    booking = get_object_or_404(DatSan, id=booking_id, nguoi_dat=request.user)
    if booking.trangThai != 'pending' or not booking.yeu_cau_thanh_toan or not booking.ngay_khach_mo_thanh_toan:
        messages.error(request, "Đơn này chưa sẵn sàng để xác nhận chuyển khoản.")
        return redirect('lich_su_dat_san')
    if booking.yeu_cau_thanh_toan_het_han:
        messages.error(request, "Yêu cầu đặt cọc đã hết hạn. Vui lòng chờ quản lý gửi lại yêu cầu mới.")
        return redirect('lich_su_dat_san')
    target = booking_target_queryset(booking)
    target.update(
        khach_xac_nhan_chuyen_khoan=True,
        ngay_khach_xac_nhan_ck=timezone.now(),
    )
    manager = NguoiDung.objects.filter(
        chi_nhanh_quan_ly_id=booking.san.maChiNhanh_id,
        role__in=['manager', 'staff'],
    ).order_by('-is_staff', 'id').first()
    if manager:
        ThongBao.objects.create(
            nguoi_nhan=manager,
            tieu_de="Khách đã xác nhận chuyển khoản",
            noi_dung=f"{booking.tenNguoiDat} đã bấm xác nhận chuyển khoản cho sân {booking.san.tenSan} ngày {booking.ngayBatDau:%d/%m/%Y}.",
        )
    messages.success(request, "Đã gửi xác nhận chuyển khoản đến quản lý. Đơn sẽ được duyệt sau khi đối soát.")
    return redirect('lich_su_dat_san')


def co_quyen_xem_hoa_don(request, don):
    if don.nguoi_dat == request.user and don.trangThai in {'confirmed', 'completed'}:
        return True
    if request.user.is_superuser or request.user.is_staff:
        return True
    if request.user.role in {'staff', 'manager'} and request.user.chi_nhanh_quan_ly_id == don.san.maChiNhanh_id:
        return True
    return False


def tao_tom_tat_hoa_don(don, chi_tiet, tong_tien):
    items = list(chi_tiet)
    first_item = items[0] if items else don
    last_item = items[-1] if items else don
    is_group = don.loaiDatSan == 1 and don.nhom_dat_san
    statuses = {item.get_trangThai_display() for item in items}
    status_label = statuses.pop() if len(statuses) == 1 else don.get_trangThai_display()

    return {
        'is_group': is_group,
        'items': items,
        'title': "Lịch cố định" if is_group else "Đặt sân vãng lai",
        'so_buoi': len(items) or 1,
        'ngay_bat_dau': first_item.ngayBatDau,
        'ngay_ket_thuc': last_item.ngayBatDau,
        'gio_bat_dau': first_item.gioBatDau,
        'gio_ket_thuc': first_item.gioKetThuc,
        'lich_tap': first_item.get_lich_tap_display() if is_group and first_item.lich_tap else "-",
        'san': first_item.san,
        'trang_thai': status_label,
        'don_gia': first_item.tongGiaTien,
        'tong_tien': tong_tien,
    }


def lay_du_lieu_hoa_don(request, booking_id):
    don = get_object_or_404(
        DatSan.objects.select_related('nguoi_dat', 'san', 'san__maChiNhanh', 'nguoi_duyet'),
        id=booking_id,
    )
    if not co_quyen_xem_hoa_don(request, don):
        raise Http404("Hóa đơn không tồn tại.")

    if don.loaiDatSan == 1 and don.nhom_dat_san:
        chi_tiet = DatSan.objects.filter(nhom_dat_san=don.nhom_dat_san).select_related(
            'san', 'san__maChiNhanh', 'nguoi_duyet'
        ).order_by('ngayBatDau', 'gioBatDau')
    else:
        chi_tiet = DatSan.objects.filter(id=don.id).select_related('san', 'san__maChiNhanh', 'nguoi_duyet')

    tong_tien = chi_tiet.aggregate(Sum('tongGiaTien'))['tongGiaTien__sum'] or 0
    nguoi_duyet = chi_tiet.filter(nguoi_duyet__isnull=False).select_related('nguoi_duyet').first()
    chi_tiet = list(chi_tiet)

    return {
        'don': don,
        'chi_tiet': chi_tiet,
        'tong_tien': tong_tien,
        'nguoi_duyet': nguoi_duyet.nguoi_duyet if nguoi_duyet else None,
        'tom_tat_hoa_don': tao_tom_tat_hoa_don(don, chi_tiet, tong_tien),
    }


@login_required(login_url='login')
def xuat_hoa_don(request, booking_id):
    return render(request, 'hoa_don.html', lay_du_lieu_hoa_don(request, booking_id))


@login_required(login_url='login')
def tai_hoa_don_anh(request, booking_id):
    data = lay_du_lieu_hoa_don(request, booking_id)
    try:
        png_bytes = render_invoice_png(
            data['don'],
            data['chi_tiet'],
            data['tong_tien'],
            data['nguoi_duyet'],
            data['tom_tat_hoa_don'],
        )
    except RuntimeError as exc:
        return HttpResponse(str(exc), status=503, content_type='text/plain; charset=utf-8')
    response = HttpResponse(png_bytes, content_type='image/png')
    response['Content-Disposition'] = f'attachment; filename="hoa-don-{booking_id}.png"'
    return response

# ==========================================
# CỘNG ĐỒNG & DIỄN ĐÀN
# ==========================================
@login_required(login_url='login')
def lich_cong_dong(request):
    ngay_str = request.GET.get('ngay')
    if ngay_str:
        try:
            ngay_xem = datetime.strptime(ngay_str, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "Ngày xem lịch không hợp lệ.")
            return redirect('lich_cong_dong')
    else:
        ngay_xem = timezone.now().date()
    ds_san = SanCauLong.objects.select_related('maChiNhanh').order_by('maChiNhanh__tenChiNhanh', 'tenSan')
    ds_dat_cho = DatSan.objects.filter(ngayBatDau=ngay_xem, trangThai__in=['confirmed', 'pending', 'completed']).select_related('san', 'san__maChiNhanh', 'nguoi_dat').order_by('san__maChiNhanh__tenChiNhanh', 'san__tenSan', 'gioBatDau')
    san_id = request.GET.get('san'); 
    if san_id:
        if not san_id.isdigit():
            messages.error(request, "Sân lọc không hợp lệ.")
            return redirect('lich_cong_dong')
        ds_dat_cho = ds_dat_cho.filter(san_id=int(san_id))
    return render(request, 'lich_cong_dong.html', {'ds_dat_cho': ds_dat_cho, 'ds_san': ds_san, 'ngay_hien_tai': ngay_xem, 'san_dang_chon': int(san_id) if san_id else None})

@login_required(login_url='login')
def update_recruitment(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body); booking = get_object_or_404(DatSan, id=data.get('id'), nguoi_dat=request.user)
            count = int(data.get('count', 0))
            if count < 0 or count > 10:
                return JsonResponse({'status': 'error', 'message': 'Số lượng cần tuyển phải từ 0 đến 10.'}, status=400)
            booking.soLuongTuyen = count; booking.tuyenThanhVien = data.get('enable', False) and count > 0
            if booking.tuyenThanhVien:
                booking.trinh_do_can = data.get('trinh_do', 'tb')
                raw_note = data.get('ghi_chu', '')
                booking.ghi_chu_tuyen = normalize_plain_text(raw_note, max_length=255, field_label="Ghi chú tuyển") if raw_note else ''
            booking.save(); return JsonResponse({'status': 'success'})
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            if hasattr(exc, "messages"):
                return JsonResponse({'status': 'error', 'message': exc.messages[0]}, status=400)
            return JsonResponse({'status': 'error', 'message': 'Dữ liệu cập nhật không hợp lệ.'}, status=400)
    return JsonResponse({'status': 'error'}, status=405)

@login_required(login_url='login')
def dien_dan_view(request):
    query = request.GET.get('q', ''); ds_bai = BaiDang.objects.filter(duyet_bai=True)
    if query: ds_bai = ds_bai.filter(Q(tieu_de__icontains=query) | Q(noi_dung__icontains=query))
    return render(request, 'dien_dan.html', {'ds_bai': ds_bai.order_by('-ngay_dang')})

@login_required(login_url='login')
def chi_tiet_bai_viet(request, bai_id):
    bai = get_object_or_404(BaiDang, id=bai_id)
    if not bai.duyet_bai and bai.nguoi_dang != request.user and not request.user.is_staff:
        raise Http404("Bài viết không tồn tại.")
    da_xem = request.session.get('viewed_posts', [])
    if bai_id not in da_xem:
        bai.luot_xem += 1; bai.save(); da_xem.append(bai_id); request.session['viewed_posts'] = da_xem; request.session.modified = True
    if request.method == 'POST':
        form = BinhLuanForm(request.POST)
        if form.is_valid():
            bl = form.save(commit=False); bl.bai_dang = bai; bl.nguoi_binh_luan = request.user
            parent_id = request.POST.get('parent_id')
            if parent_id:
                try: bl.parent = BinhLuan.objects.get(id=parent_id, bai_dang=bai)
                except BinhLuan.DoesNotExist: pass
            bl.save(); return redirect('chi_tiet_bai_viet', bai_id=bai.id)
    return render(request, 'chi_tiet_bai_viet.html', {'bai': bai, 'ds_binh_luan': bai.binh_luan_set.filter(parent=None).order_by('-ngay_tao'), 'form': BinhLuanForm()})

@login_required(login_url='login')
@require_POST
def xoa_binh_luan(request, bl_id):
    bl = get_object_or_404(BinhLuan, id=bl_id)
    if bl.nguoi_binh_luan == request.user or request.user.is_staff:
        bai_id = bl.bai_dang.id
        bl.delete()
        messages.success(request, "Đã xóa bình luận thành công.")
        return redirect('chi_tiet_bai_viet', bai_id=bai_id)
    messages.error(request, "Bạn không có quyền xóa bình luận này.")
    return redirect('chi_tiet_bai_viet', bai_id=bl.bai_dang.id)

@login_required(login_url='login')
def tao_bai_viet(request):
    form = BaiDangForm()
    if request.method == 'POST':
        form = BaiDangForm(request.POST, request.FILES)
        if form.is_valid():
            bai = form.save(commit=False); bai.nguoi_dang = request.user; bai.save()
            notify_admins(
                title=f"{request.user.ten} đã gửi một bài viết",
                message=f"Bài viết “{bai.tieu_de}” đang chờ được kiểm duyệt.",
                category="post",
                link=f"{reverse('admin_posts')}?status=pending",
                global_only=True,
            )
            messages.success(request, "Đã gửi bài viết (Chờ duyệt)."); return redirect('dien_dan')
    return render(request, 'tao_bai_viet.html', {'form': form})

@login_required(login_url='login')
def support_view(request):
    if request.method == 'GET':
        messages.info(request, "Tính năng hỗ trợ đã chuyển sang icon tin nhắn ở góc trái dưới.")
        return redirect('home')
    hoi_thoai = HoiThoaiKhachHang.objects.filter(nguoi_dung=request.user, da_dong=False).order_by('-ngay_tao').first()
    if not hoi_thoai:
        hoi_thoai = HoiThoaiKhachHang.objects.create(nguoi_dung=request.user, tieu_de=f"Hỗ trợ {request.user.ten}")
    if request.method == 'POST':
        form = HoTroForm(request.POST)
        if form.is_valid():
            cau_hoi = form.cleaned_data['cau_hoi']
            branch_id = request.POST.get('branch_id')
            force_admin = request.POST.get('force_admin') == '1'
            create_customer_message(request.user, cau_hoi, branch_id=branch_id, force_admin=force_admin)
            return redirect('support')
    return render(request, 'support.html', {'form': HoTroForm(), 'lich_su_chat': hoi_thoai.hotro_set.all().order_by('ngay_gui')})


@login_required(login_url='login')
def support_widget_state(request):
    return JsonResponse(serialize_customer_state(request.user))


@login_required(login_url='login')
@require_POST
def support_widget_send(request):
    try:
        payload = json.loads(request.body.decode('utf-8')) if request.body else request.POST
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Dữ liệu gửi không hợp lệ.'}, status=400)

    try:
        message = normalize_plain_text(payload.get('message'), max_length=1000, field_label='Tin nhắn hỗ trợ')
    except Exception as exc:
        return JsonResponse({'error': exc.messages[0] if hasattr(exc, 'messages') else 'Vui lòng nhập tin nhắn.'}, status=400)

    branch_id = payload.get('branch_id') or None
    force_admin = str(payload.get('force_admin', '')).lower() in {'1', 'true', 'yes', 'on'}
    conversation, _ = create_customer_message(request.user, message, branch_id=branch_id, force_admin=force_admin)
    return JsonResponse({
        'ok': True,
        'conversation_id': conversation.id,
        'state': serialize_customer_state(request.user),
    })
