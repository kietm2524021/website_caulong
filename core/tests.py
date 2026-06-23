import os
import uuid
from io import StringIO
from decimal import Decimal
from datetime import time, timedelta
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.core.management import call_command
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from .models import BaiDang, BinhLuan, ChiNhanh, DatSan, HoiThoaiKhachHang, HoTro, NguoiDung, SanCauLong, ThongBao
from . import invoice_image
from .support_ai import tao_phan_hoi_ho_tro
from .security import BotProtectionMiddleware, RequestRateLimitMiddleware, SecurityResponseHeadersMiddleware
from .views import tinh_tien_chi_tiet


class BookingSupportInvoiceTests(TestCase):
    def setUp(self):
        self.user = NguoiDung.objects.create_user(
            username="0900000001",
            sodienthoai="0900000001",
            ten="Khach Test",
            password="Test@12345",
        )
        self.admin = NguoiDung.objects.create_user(
            username="0900000002",
            sodienthoai="0900000002",
            ten="Admin Test",
            password="Admin@12345",
            is_staff=True,
        )
        self.branch = ChiNhanh.objects.create(
            tenChiNhanh="Chi nhanh Test",
            diaChi="123 Test",
            sdt="0900000000",
            tenQuanLy="Quan ly Test",
            ten_ngan_hang="VCB",
            so_tai_khoan="123456789",
            chu_tai_khoan="Badminton Test",
        )
        self.branch_2 = ChiNhanh.objects.create(
            tenChiNhanh="Chi nhanh 2",
            diaChi="456 Test",
            sdt="0900000003",
            tenQuanLy="Quan ly 2",
        )
        self.court_1 = SanCauLong.objects.create(maChiNhanh=self.branch, tenSan="San 1")
        self.court_2 = SanCauLong.objects.create(maChiNhanh=self.branch, tenSan="San 2")
        self.client.force_login(self.user)

    def post_booking(self, court, booking_date, start="17:00", end="18:00", **extra):
        data = {
            "san": str(court.id),
            "loaiDatSan": "0",
            "ngayBatDau": booking_date.isoformat(),
            "ngayKetThuc": "",
            "gioBatDau": start,
            "gioKetThuc": end,
            "lich_tap": "",
            "phuong_thuc_thanh_toan": "cash",
            "soLuongTuyen": "0",
            "trinh_do_can": "tb",
            "ghi_chu_tuyen": "",
        }
        data.update(extra)
        return self.client.post(f"{reverse('dat_san')}?san_id={court.id}", data)

    @patch.dict(
        os.environ,
        {
            "CREATE_SUPERUSER": "True",
            "DEFAULT_ADMIN_NAME": "Admin Mặc Định",
            "DEFAULT_ADMIN_PHONE": "0988888888",
            "DJANGO_SUPERUSER_PASSWORD": "StrongSeedPass@123",
            "DJANGO_SUPERUSER_EMAIL": "seed-admin@example.com",
        },
        clear=False,
    )
    def test_seed_defaults_is_idempotent(self):
        call_command("seed_defaults", stdout=StringIO())

        seeded_admin = NguoiDung.objects.get(sodienthoai="0988888888")
        self.assertTrue(seeded_admin.is_superuser)
        self.assertTrue(seeded_admin.is_staff)
        self.assertEqual(seeded_admin.ten, "Admin Mặc Định")

        seeded_branches = ChiNhanh.objects.filter(tenChiNhanh__in=["Lê Giang 1", "Lê Giang 2"])
        self.assertEqual(seeded_branches.count(), 2)
        self.assertEqual(SanCauLong.objects.filter(maChiNhanh__in=seeded_branches).count(), 14)
        court = SanCauLong.objects.get(maChiNhanh__tenChiNhanh="Lê Giang 1", tenSan="Sân 1")
        court.gia_co_dinh = Decimal("123000")
        court.save(update_fields=["gia_co_dinh"])

        call_command("seed_defaults", stdout=StringIO())

        self.assertEqual(NguoiDung.objects.filter(sodienthoai="0988888888").count(), 1)
        self.assertEqual(ChiNhanh.objects.filter(tenChiNhanh__in=["Lê Giang 1", "Lê Giang 2"]).count(), 2)
        self.assertEqual(SanCauLong.objects.filter(maChiNhanh__in=seeded_branches).count(), 14)
        court.refresh_from_db()
        self.assertEqual(court.gia_co_dinh, Decimal("123000"))

    def test_booking_conflict_is_scoped_to_the_same_court(self):
        booking_date = timezone.now().date() + timedelta(days=2)
        DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=booking_date,
            gioBatDau=time(17, 0),
            gioKetThuc=time(18, 0),
            tongGiaTien=50000,
            trangThai="confirmed",
        )

        self.post_booking(self.court_1, booking_date, start="17:30", end="18:30")
        self.assertEqual(DatSan.objects.filter(san=self.court_1).count(), 1)

        self.post_booking(self.court_2, booking_date, start="17:30", end="18:30")
        self.assertEqual(DatSan.objects.filter(san=self.court_2).count(), 1)

    def test_booking_prices_use_requested_rates(self):
        self.assertEqual(self.court_1.gia_vang, Decimal("50000"))
        self.assertEqual(self.court_1.gia_thuong, Decimal("80000"))
        self.assertEqual(self.court_1.gia_co_dinh, Decimal("40000"))
        self.assertEqual(tinh_tien_chi_tiet(self.court_1, 0, time(9, 0), time(10, 0)), Decimal("50000"))
        self.assertEqual(tinh_tien_chi_tiet(self.court_1, 0, time(18, 0), time(19, 0)), Decimal("80000"))
        self.assertEqual(tinh_tien_chi_tiet(self.court_1, 0, time(16, 30), time(17, 30)), Decimal("65000.0"))
        self.assertEqual(tinh_tien_chi_tiet(self.court_1, 1, time(18, 0), time(19, 0)), Decimal("40000"))
        self.assertEqual(tinh_tien_chi_tiet(self.court_1, 1, time(18, 0), time(20, 0)), Decimal("80000"))

    def test_booking_generates_deposit_transfer_content(self):
        booking_date = timezone.now().date() + timedelta(days=3)
        self.branch.tenChiNhanh = "Lê Giang 1"
        self.branch.save(update_fields=["tenChiNhanh"])
        self.post_booking(
            self.court_2,
            booking_date,
            start="19:00",
            end="20:00",
        )

        booking = DatSan.objects.get(san=self.court_2)
        self.assertEqual(booking.phuong_thuc_thanh_toan, "bank")
        self.assertEqual(
            booking.noi_dung_chuyen_khoan,
            f"KHACHTEST_LG1_SAN2_1900_{booking_date.strftime('%d%m%y')}",
        )
        self.assertTrue(booking.noi_dung_chuyen_khoan.isascii())

    def test_booking_form_has_recruitment_defaults_and_no_payment_method_box(self):
        response = self.client.get(f"{reverse('dat_san')}?san_id={self.court_1.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-price-fixed="40000"')
        self.assertContains(response, "total += duration * priceFixed;")
        self.assertContains(response, 'name="soLuongTuyen" value="1"')
        self.assertContains(response, '<option value="yeu" selected>')
        self.assertContains(response, 'value="Giao lưu vui vẻ, chia đều tiền sân."')
        self.assertNotContains(response, "Phương thức thanh toán")

    def test_home_uses_badminton_court_photo_instead_of_table_tennis_icon(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "photo-1617696618050-b0fef0c666af")
        self.assertContains(response, 'alt="Sân cầu lông trong nhà San 1"')
        self.assertNotContains(response, "fa-table-tennis-paddle-ball")

    def test_fixed_booking_conflict_blocks_all_matching_days(self):
        monday = timezone.now().date()
        while monday.weekday() != 0:
            monday += timedelta(days=1)

        DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=monday,
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            tongGiaTien=60000,
            trangThai="confirmed",
        )

        self.post_booking(
            self.court_1,
            monday,
            start="18:30",
            end="19:30",
            loaiDatSan="1",
            lich_tap="246",
            ngayKetThuc=monday.isoformat(),
        )

        self.assertEqual(DatSan.objects.filter(san=self.court_1).count(), 1)

    def test_admin_bookings_groups_fixed_booking_into_one_row(self):
        start_date = timezone.now().date() + timedelta(days=2)
        end_date = start_date + timedelta(days=14)
        self.post_booking(
            self.court_1,
            start_date,
            start="18:00",
            end="19:00",
            loaiDatSan="1",
            lich_tap="full",
            ngayKetThuc=end_date.isoformat(),
        )
        self.assertEqual(DatSan.objects.filter(san=self.court_1, loaiDatSan=1).count(), 15)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_bookings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "15 buổi")
        content = response.content.decode("utf-8")
        self.assertIn("600.000đ", content)
        fixed_bookings = DatSan.objects.filter(san=self.court_1, loaiDatSan=1)
        self.assertEqual(fixed_bookings.count(), 15)
        self.assertFalse(fixed_bookings.exclude(tongGiaTien=Decimal("40000")).exists())
        self.assertEqual(content.count('class="form-check-input booking-select"'), 1)
        self.assertContains(response, 'id="selectAllBookings"')

        first_booking = fixed_bookings.order_by("ngayBatDau").first()
        invoice = self.client.get(reverse("xuat_hoa_don", args=[first_booking.id]))
        self.assertContains(invoice, "40.000đ")
        self.assertContains(invoice, "600.000đ")

    def test_admin_bookings_flags_overlapping_requests_on_the_same_court(self):
        booking_date = timezone.localdate() + timedelta(days=2)
        first = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=booking_date,
            gioBatDau=time(18, 0),
            gioKetThuc=time(20, 0),
            tongGiaTien=160000,
            trangThai="pending",
        )
        second = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=booking_date,
            gioBatDau=time(19, 0),
            gioKetThuc=time(21, 0),
            tongGiaTien=160000,
            trangThai="confirmed",
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_bookings"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["booking_summary"]["conflicts"], 2)
        rows = {row.id: row for row in response.context["bookings"]}
        self.assertTrue(rows[first.id].admin_has_conflict)
        self.assertTrue(rows[second.id].admin_has_conflict)
        self.assertContains(response, "Chồng lịch với 1 đơn khác")

    def test_admin_bookings_prioritizes_deposit_confirmation_then_new_requests(self):
        booking_date = timezone.localdate() + timedelta(days=3)
        waiting = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=booking_date,
            gioBatDau=time(20, 0),
            gioKetThuc=time(21, 0),
            tongGiaTien=80000,
            trangThai="pending",
            yeu_cau_thanh_toan=True,
        )
        new_request = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_2,
            ngayBatDau=booking_date,
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            tongGiaTien=80000,
            trangThai="pending",
        )
        deposited = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_2,
            ngayBatDau=booking_date,
            gioBatDau=time(21, 0),
            gioKetThuc=time(22, 0),
            tongGiaTien=80000,
            trangThai="pending",
            yeu_cau_thanh_toan=True,
            khach_xac_nhan_chuyen_khoan=True,
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_bookings"))

        self.assertEqual(response.status_code, 200)
        row_ids = [row.id for row in response.context["bookings"]]
        self.assertEqual(row_ids, [deposited.id, new_request.id, waiting.id])
        self.assertContains(response, "Cần đối soát cọc ngay")
        self.assertContains(response, "Yêu cầu mới cần xử lý")

    @patch.dict(os.environ, {"AI_SUPPORT_ENABLED": "False"}, clear=False)
    def test_support_auto_reply_and_admin_handoff(self):
        self.client.post(reverse("support"), {"cau_hoi": "Thanh toan QR nhu the nao?"})
        auto_reply = HoTro.objects.latest("id")
        self.assertEqual(auto_reply.nguon_tra_loi, "ai")
        self.assertTrue(auto_reply.tra_loi)
        self.assertTrue(auto_reply.da_xem)

        self.client.post(reverse("support"), {"cau_hoi": "Toi muon admin tra loi giup toi"})
        handoff = HoTro.objects.latest("id")
        self.assertEqual(handoff.nguon_tra_loi, "admin")
        self.assertTrue(handoff.yeu_cau_admin)
        self.assertFalse(handoff.tra_loi)
        self.assertFalse(handoff.da_xem)

    @patch.dict(os.environ, {"AI_SUPPORT_ENABLED": "False"}, clear=False)
    def test_support_generic_system_question_still_gets_reply(self):
        reply, source, needs_admin = tao_phan_hoi_ho_tro("Toi can huong dan dung he thong dat san")
        self.assertEqual(source, "ai")
        self.assertFalse(needs_admin)
        self.assertTrue(reply)

    @patch.dict(os.environ, {"AI_SUPPORT_ENABLED": "False"}, clear=False)
    def test_support_out_of_scope_question_gets_guidance_reply(self):
        reply, source, needs_admin = tao_phan_hoi_ho_tro("Alo ban oi")
        self.assertEqual(source, "ai")
        self.assertFalse(needs_admin)
        self.assertIn("Bạn có thể hỏi", reply)

    @patch.dict(os.environ, {"AI_SUPPORT_ENABLED": "False"}, clear=False)
    def test_support_out_of_scope_non_greeting_gets_guidance_reply(self):
        reply, source, needs_admin = tao_phan_hoi_ho_tro("Ke cho toi mot cau chuyen vui")
        self.assertEqual(source, "ai")
        self.assertFalse(needs_admin)
        self.assertIn("hệ thống đặt sân", reply)

    @patch.dict(os.environ, {"AI_SUPPORT_ENABLED": "False"}, clear=False)
    def test_support_widget_answers_availability_with_abbreviation(self):
        response = self.client.post(
            reverse("support_widget_send"),
            data='{"message":"hom nay co san trong k","branch_id":%d,"force_admin":false}' % self.branch.id,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        messages = response.json()["state"]["messages"]
        self.assertIn("Còn sân trống", messages[-1]["reply"])
        self.assertIn("Khung giờ", messages[-1]["reply"])

    @patch.dict(os.environ, {"AI_SUPPORT_ENABLED": "False"}, clear=False)
    def test_support_widget_understands_casual_play_question(self):
        response = self.client.post(
            reverse("support_widget_send"),
            data='{"message":"hom nay co san nao danh k","branch_id":%d,"force_admin":false}' % self.branch.id,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        reply = response.json()["state"]["messages"][-1]["reply"]
        self.assertIn("Còn sân trống", reply)

    @patch.dict(os.environ, {"AI_SUPPORT_ENABLED": "False"}, clear=False)
    def test_support_widget_answers_recruitment_question_before_availability(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=tomorrow,
            gioBatDau=time(18, 0),
            gioKetThuc=time(20, 0),
            tongGiaTien=160000,
            trangThai="confirmed",
            tuyenThanhVien=True,
            soLuongTuyen=2,
            trinh_do_can="tb",
            ghi_chu_tuyen="vui vẻ",
        )

        response = self.client.post(
            reverse("support_widget_send"),
            data='{"message":"ngay mai co san nao tuyen thanh vien khong","branch_id":%d,"force_admin":false}' % self.branch.id,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        reply = response.json()["state"]["messages"][-1]["reply"]
        self.assertIn("tuyển thành viên", reply)
        self.assertIn("San 1", reply)
        self.assertIn("18:00-20:00", reply)
        self.assertIn("2 người", reply)
        self.assertNotIn("Còn sân trống", reply)

    @patch.dict(os.environ, {"AI_SUPPORT_ENABLED": "False"}, clear=False)
    def test_support_widget_answers_common_system_question_groups(self):
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)
        saturday = today + timedelta(days=(5 - today.weekday()) % 7)
        court_3 = SanCauLong.objects.create(maChiNhanh=self.branch, tenSan="San 3")
        BaiDang.objects.create(
            nguoi_dang=self.user,
            tieu_de="Hướng dẫn tìm đồng đội chơi cầu lông",
            noi_dung="Kinh nghiệm đăng bài tìm đồng đội và kèo giao lưu.",
            duyet_bai=True,
        )
        DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=today,
            gioBatDau=time(18, 0),
            gioKetThuc=time(20, 0),
            tongGiaTien=160000,
            trangThai="confirmed",
            tuyenThanhVien=True,
            soLuongTuyen=2,
            trinh_do_can="tb",
            ghi_chu_tuyen="vui vẻ",
        )
        DatSan.objects.create(
            nguoi_dat=self.user,
            san=court_3,
            ngayBatDau=tomorrow,
            gioBatDau=time(19, 0),
            gioKetThuc=time(21, 0),
            tongGiaTien=160000,
            trangThai="confirmed",
            tuyenThanhVien=True,
            soLuongTuyen=3,
            trinh_do_can="kha",
            ghi_chu_tuyen="ưu tiên đôi nam",
        )
        DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_2,
            ngayBatDau=saturday,
            gioBatDau=time(18, 0),
            gioKetThuc=time(20, 0),
            tongGiaTien=160000,
            trangThai="confirmed",
            tuyenThanhVien=True,
            soLuongTuyen=1,
        )

        questions = [
            ("Hôm nay có sân nào còn trống không?", "Còn sân trống"),
            ("Ngày mai có sân nào đang hoạt động không?", "đang hoạt động"),
            ("Cuối tuần này có những sân nào mở cửa?", "Giờ mở cửa"),
            ("Tối nay có sân nào đánh từ 18h đến 20h không?", "18:00-20:00"),
            ("Có sân nào đang chơi vào lúc 19h không?", "Chi tiết lịch sân"),
            ("Hôm nay có sân nào đang tuyển thành viên không?", "tuyển thành viên"),
            ("Ngày mai có sân nào tuyển thêm người đánh không?", "San 3"),
            ("Có sân nào đang thiếu người chơi không?", "tuyển thành viên"),
            ("Cuối tuần này có sân nào cần thêm thành viên không?", "tuyển thành viên"),
            ("Cho tôi xem các lịch sân đang tuyển người.", "tuyển thành viên"),
            ("Ai đang tham gia sân lúc 18h hôm nay?", "do Khach Test đặt"),
            ("Cho tôi xem chi tiết lịch sân tối nay.", "Chi tiết lịch sân"),
            ("Sân số 3 ngày mai có bao nhiêu người đăng ký?", "San 3"),
            ("Lịch sân ngày mai có ghi chú gì không?", "ưu tiên đôi nam"),
            ("Sân nào có đông người tham gia nhất hôm nay?", "chưa lưu danh sách người tham gia"),
            ("Tôi muốn đặt sân vào tối mai thì còn sân nào trống?", "Còn sân trống"),
            ("Có thể đặt sân từ 19h đến 21h hôm nay không?", "Còn sân trống"),
            ("Cho tôi xem các khung giờ còn trống để đặt sân.", "Khung giờ gợi ý"),
            ("Trên diễn đàn đang có bài viết nào mới không?", "Diễn đàn"),
            ("Có bài viết nào hướng dẫn tìm đồng đội chơi cầu lông không?", "Hướng dẫn tìm đồng đội"),
            ("mai còn sân nào ko", "Còn sân trống"),
            ("tối nay có ai tuyển người đánh không", "tuyển thành viên"),
            ("kiếm sân đánh ngày mai", "Còn sân trống"),
            ("sân nào đang thiếu người", "tuyển thành viên"),
            ("có kèo nào tối nay không", "tuyển thành viên"),
            ("cho mình tham gia sân đang tuyển thành viên", "tuyển thành viên"),
            ("xem lịch đánh cầu ngày mai", "Còn sân trống"),
        ]

        for question, expected in questions:
            response = self.client.post(
                reverse("support_widget_send"),
                data='{"message":"%s","branch_id":%d,"force_admin":false}' % (question, self.branch.id),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200, question)
            reply = response.json()["state"]["messages"][-1]["reply"]
            self.assertIn(expected, reply, question)

    @patch("core.support_ai.requests.post")
    @patch.dict(
        os.environ,
        {
            "AI_SUPPORT_ENABLED": "True",
            "AI_SUPPORT_API_KEY": "test-key",
            "AI_SUPPORT_MODEL": "gpt-5.5",
        },
        clear=False,
    )
    def test_support_uses_configured_model_when_calling_api(self, mock_post):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"output_text": "Day la phan hoi AI"}
        mock_post.return_value = mock_response

        reply, source, needs_admin = tao_phan_hoi_ho_tro("Chi nhanh co dich vu gi dac biet?")

        self.assertEqual(reply, "Day la phan hoi AI")
        self.assertEqual(source, "ai")
        self.assertFalse(needs_admin)
        self.assertEqual(mock_post.call_args.kwargs["json"]["model"], "gpt-5.5")

    def test_invoice_contains_required_booking_fields(self):
        booking_date = timezone.now().date() + timedelta(days=4)
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=booking_date,
            gioBatDau=time(17, 0),
            gioKetThuc=time(18, 0),
            tongGiaTien=1000000,
            so_tien_coc=300000,
            daThanhToan=True,
            trangThai="confirmed",
            nguoi_duyet=self.admin,
        )

        response = self.client.get(reverse("xuat_hoa_don", args=[booking.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Khach Test")
        self.assertContains(response, "Chi nhanh Test")
        self.assertContains(response, "San 1")
        self.assertContains(response, "17:00 - 18:00")
        self.assertContains(response, "Admin Test")
        self.assertContains(response, "Tổng tiền")
        self.assertContains(response, "1.000.000đ")
        self.assertContains(response, "Đã cọc")
        self.assertContains(response, "300.000đ")
        self.assertContains(response, "Còn phải thanh toán")
        self.assertContains(response, "700.000đ")

    def test_fixed_booking_invoice_is_compact_summary(self):
        group_id = uuid.uuid4()
        start_date = timezone.now().date() + timedelta(days=5)
        for offset in range(15):
            DatSan.objects.create(
                nguoi_dat=self.user,
                san=self.court_1,
                ngayBatDau=start_date + timedelta(days=offset),
                ngayKetThuc=start_date + timedelta(days=14),
                gioBatDau=time(17, 0),
                gioKetThuc=time(19, 0),
                lich_tap="full",
                tongGiaTien=40000,
                trangThai="confirmed",
                loaiDatSan=1,
                nhom_dat_san=group_id,
                nguoi_duyet=self.admin,
            )
        first_booking = DatSan.objects.filter(nhom_dat_san=group_id).order_by("ngayBatDau").first()

        response = self.client.get(reverse("xuat_hoa_don", args=[first_booking.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lịch cố định")
        self.assertContains(response, "15 buổi")
        self.assertContains(response, "40.000đ")
        self.assertContains(response, "600.000đ")
        self.assertContains(response, "Gộp toàn bộ đơn trong cùng lịch cố định.")
        self.assertContains(response, start_date.strftime("%d/%m/%Y"))
        self.assertContains(response, (start_date + timedelta(days=14)).strftime("%d/%m/%Y"))
        self.assertEqual(response.content.decode("utf-8").count("<tr>"), 2)

    def test_invoice_image_download_returns_png(self):
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.now().date() + timedelta(days=4),
            gioBatDau=time(17, 0),
            gioKetThuc=time(18, 0),
            tongGiaTien=50000,
            trangThai="confirmed",
            nguoi_duyet=self.admin,
        )

        response = self.client.get(reverse("tai_hoa_don_anh", args=[booking.id]))
        if invoice_image.Image is None:
            self.assertEqual(response.status_code, 503)
            return
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_admin_console_blocks_regular_customers(self):
        response = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_admin_console_pages_render_for_staff(self):
        self.client.force_login(self.admin)
        BaiDang.objects.create(nguoi_dang=self.user, tieu_de="Bai test", noi_dung="Noi dung test")
        thread = HoiThoaiKhachHang.objects.create(nguoi_dung=self.user)
        HoTro.objects.create(hoi_thoai=thread, nguoi_dung=self.user, cau_hoi="Can ho tro")

        for name in ["admin_dashboard", "admin_bookings", "admin_courts", "admin_posts", "admin_support", "admin_users"]:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_booking_request_notifies_global_and_branch_admins(self):
        branch_manager = NguoiDung.objects.create_user(
            username="manager",
            sodienthoai="0900000099",
            ten="Quản lý chi nhánh",
            password="Manager@123",
            role="manager",
            chi_nhanh_quan_ly=self.branch,
        )
        booking_date = timezone.now().date() + timedelta(days=3)
        self.post_booking(self.court_1, booking_date)

        for recipient in [self.admin, branch_manager]:
            notification = ThongBao.objects.get(nguoi_nhan=recipient, loai="booking")
            self.assertIn("Khach Test đã gửi yêu cầu đặt sân", notification.tieu_de)
            self.assertIn(reverse("admin_bookings"), notification.duong_dan)

    def test_post_notification_only_goes_to_global_admin(self):
        branch_manager = NguoiDung.objects.create_user(
            username="manager-post",
            sodienthoai="0900000098",
            ten="Quản lý chi nhánh",
            password="Manager@123",
            role="manager",
            chi_nhanh_quan_ly=self.branch,
        )
        response = self.client.post(
            reverse("tao_bai_viet"),
            {"tieu_de": "Bài viết chờ duyệt", "noi_dung": "Nội dung bài viết hợp lệ."},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ThongBao.objects.filter(nguoi_nhan=self.admin, loai="post").exists())
        self.assertFalse(ThongBao.objects.filter(nguoi_nhan=branch_manager, loai="post").exists())

    def test_forum_lists_only_approved_posts_and_preserves_search_query(self):
        approved = BaiDang.objects.create(
            nguoi_dang=self.user,
            tieu_de="Kỹ thuật đập cầu",
            noi_dung="Nội dung đã được duyệt.",
            duyet_bai=True,
        )
        pending = BaiDang.objects.create(
            nguoi_dang=self.user,
            tieu_de="Kỹ thuật chưa duyệt",
            noi_dung="Nội dung đang chờ.",
            duyet_bai=False,
        )

        response = self.client.get(reverse("dien_dan"), {"q": "Kỹ thuật"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["query"], "Kỹ thuật")
        self.assertContains(response, approved.tieu_de)
        self.assertNotContains(response, pending.tieu_de)

    def test_post_view_count_increases_once_per_session(self):
        post = BaiDang.objects.create(
            nguoi_dang=self.user,
            tieu_de="Bài kiểm tra lượt xem",
            noi_dung="Nội dung bài viết.",
            duyet_bai=True,
        )

        self.client.get(reverse("chi_tiet_bai_viet", args=[post.id]))
        self.client.get(reverse("chi_tiet_bai_viet", args=[post.id]))
        post.refresh_from_db()

        self.assertEqual(post.luot_xem, 1)

    def test_comment_validation_and_xss_escaping(self):
        post = BaiDang.objects.create(
            nguoi_dang=self.user,
            tieu_de="Bài kiểm tra bình luận",
            noi_dung="Nội dung bài viết.",
            duyet_bai=True,
        )
        detail_url = reverse("chi_tiet_bai_viet", args=[post.id])

        invalid = self.client.post(detail_url, {"noi_dung": "   "})
        self.assertEqual(invalid.status_code, 200)
        self.assertTrue(invalid.context["form"].errors)
        self.assertEqual(BinhLuan.objects.count(), 0)

        self.client.post(detail_url, {"noi_dung": "<script>alert(1)</script>"})
        rendered = self.client.get(detail_url)
        self.assertContains(rendered, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(rendered, "<script>alert(1)</script>")

    def test_only_comment_owner_or_staff_can_delete_comment(self):
        other_user = NguoiDung.objects.create_user(
            username="0900000088",
            sodienthoai="0900000088",
            ten="Người bình luận",
            password="Other@12345",
        )
        post = BaiDang.objects.create(
            nguoi_dang=self.user,
            tieu_de="Bài kiểm tra quyền xóa",
            noi_dung="Nội dung bài viết.",
            duyet_bai=True,
        )
        comment = BinhLuan.objects.create(bai_dang=post, nguoi_binh_luan=other_user, noi_dung="Bình luận")

        self.client.post(reverse("xoa_binh_luan", args=[comment.id]))
        self.assertTrue(BinhLuan.objects.filter(id=comment.id).exists())

        self.client.force_login(self.admin)
        self.client.post(reverse("xoa_binh_luan", args=[comment.id]))
        self.assertFalse(BinhLuan.objects.filter(id=comment.id).exists())

    def test_admin_can_approve_hide_and_delete_post_without_external_redirect(self):
        post = BaiDang.objects.create(
            nguoi_dang=self.user,
            tieu_de="Bài chờ duyệt",
            noi_dung="Nội dung bài viết.",
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin_post_action", args=[post.id]),
            {"action": "approve", "next": "https://evil.example/phishing"},
        )

        self.assertRedirects(response, reverse("admin_posts"))
        post.refresh_from_db()
        self.assertTrue(post.duyet_bai)

        self.client.post(reverse("admin_post_action", args=[post.id]), {"action": "hide"})
        post.refresh_from_db()
        self.assertFalse(post.duyet_bai)

        self.client.post(reverse("admin_post_action", args=[post.id]), {"action": "delete"})
        self.assertFalse(BaiDang.objects.filter(id=post.id).exists())

    def test_opening_support_widget_does_not_create_empty_conversation(self):
        HoiThoaiKhachHang.objects.filter(nguoi_dung=self.user).delete()

        response = self.client.get(reverse("support_widget_state"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["conversation"])
        self.assertEqual(response.json()["messages"], [])
        self.assertFalse(HoiThoaiKhachHang.objects.filter(nguoi_dung=self.user).exists())

    def test_closed_support_conversation_is_hidden_from_admin_queue(self):
        conversation = HoiThoaiKhachHang.objects.create(
            nguoi_dung=self.user,
            chi_nhanh=self.branch,
            can_admin=True,
            da_dong=True,
        )
        HoTro.objects.create(hoi_thoai=conversation, nguoi_dung=self.user, cau_hoi="Hội thoại đã đóng")
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_support_widget_state"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conversations"], [])

    def test_support_request_notifies_branch_manager_and_links_to_chat(self):
        branch_manager = NguoiDung.objects.create_user(
            username="manager-support",
            sodienthoai="0900000097",
            ten="Quản lý chi nhánh",
            password="Manager@123",
            role="manager",
            chi_nhanh_quan_ly=self.branch,
        )
        response = self.client.post(
            reverse("support_widget_send"),
            data='{"message":"Tôi muốn trao đổi với quản lý","branch_id":%d,"force_admin":true}' % self.branch.id,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        conversation_id = response.json()["conversation_id"]
        notification = ThongBao.objects.get(nguoi_nhan=branch_manager, loai="support")
        self.assertEqual(notification.duong_dan, f"/quan-tri/ho-tro/{conversation_id}/")

    def test_admin_notification_bell_and_open_action(self):
        notification = ThongBao.objects.create(
            nguoi_nhan=self.admin,
            tieu_de="Khách hàng gửi yêu cầu",
            noi_dung="Có một yêu cầu mới cần xử lý.",
            loai="booking",
            duong_dan=reverse("admin_bookings"),
        )
        self.client.force_login(self.admin)
        page = self.client.get(reverse("admin_dashboard"))
        self.assertContains(page, "Khách hàng gửi yêu cầu")
        self.assertContains(page, "1 thông báo chưa đọc")

        response = self.client.post(reverse("admin_notification_open", args=[notification.id]))
        self.assertRedirects(response, reverse("admin_bookings"))
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_admin_live_state_returns_notifications_support_and_booking_signature(self):
        ThongBao.objects.create(
            nguoi_nhan=self.admin,
            tieu_de="Can xu ly don moi",
            noi_dung="Co mot don dat san can kiem tra.",
            loai="booking",
            duong_dan=reverse("admin_bookings"),
        )
        conversation = HoiThoaiKhachHang.objects.create(
            nguoi_dung=self.user,
            chi_nhanh=self.branch,
            can_admin=True,
        )
        HoTro.objects.create(
            hoi_thoai=conversation,
            nguoi_dung=self.user,
            nguoi_gui="customer",
            cau_hoi="Can gap quan ly",
        )
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.localdate() + timedelta(days=1),
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            trangThai="pending",
            tongGiaTien=50000,
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_live_state"), {"bookings": "1", "q": booking.sdt})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["notifications"]["unread_count"], 1)
        self.assertEqual(payload["notifications"]["items"][0]["title"], "Can xu ly don moi")
        self.assertEqual(payload["support_unread"], 1)
        self.assertIn("signature", payload["bookings"])
        self.assertEqual(payload["bookings"]["counts"]["pending"], 1)

    def test_customer_live_state_changes_when_manager_updates_booking_flow(self):
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.localdate() + timedelta(days=1),
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            trangThai="pending",
            tongGiaTien=50000,
        )

        before = self.client.get(reverse("customer_live_state")).json()["bookings"]["signature"]
        history = self.client.get(reverse("lich_su_dat_san"))
        self.assertContains(history, "customerBookingLiveReload")

        self.client.force_login(self.admin)
        self.client.post(reverse("admin_booking_action", args=[booking.id]), {"action": "request_payment"})

        self.client.force_login(self.user)
        after_payment_request = self.client.get(reverse("customer_live_state")).json()
        self.assertNotEqual(before, after_payment_request["bookings"]["signature"])
        self.assertEqual(after_payment_request["bookings"]["counts"]["payment_requested"], 1)
        self.assertEqual(after_payment_request["notifications"]["items"][0]["url"], reverse("lich_su_dat_san"))

        booking.refresh_from_db()
        booking.khach_xac_nhan_chuyen_khoan = True
        booking.ngay_khach_xac_nhan_ck = timezone.now()
        booking.save(update_fields=["khach_xac_nhan_chuyen_khoan", "ngay_khach_xac_nhan_ck"])
        mid_signature = after_payment_request["bookings"]["signature"]

        self.client.force_login(self.admin)
        self.client.post(reverse("admin_booking_action", args=[booking.id]), {"action": "mark_transfer_received"})

        self.client.force_login(self.user)
        after_approval = self.client.get(reverse("customer_live_state")).json()["bookings"]
        self.assertNotEqual(mid_signature, after_approval["signature"])
        self.assertEqual(after_approval["counts"]["confirmed"], 1)
        self.assertEqual(after_approval["counts"]["paid"], 1)

    def test_booking_deposit_is_ten_thousand_per_hour(self):
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.now().date() + timedelta(days=5),
            gioBatDau=time(18, 0),
            gioKetThuc=time(20, 0),
            tongGiaTien=160000,
        )
        self.assertEqual(booking.so_tien_coc, Decimal("20000"))

    def test_admin_sends_deposit_request_before_approval(self):
        self.client.force_login(self.admin)
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.now().date() + timedelta(days=5),
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            tongGiaTien=50000,
            trangThai="pending",
        )

        self.client.post(reverse("admin_booking_action", args=[booking.id]), {"action": "request_payment"})
        booking.refresh_from_db()
        self.assertEqual(booking.trangThai, "pending")
        self.assertTrue(booking.yeu_cau_thanh_toan)
        self.assertIsNotNone(booking.ngay_gui_yeu_cau_thanh_toan)
        self.assertIsNone(booking.ngay_khach_mo_thanh_toan)
        self.assertEqual(booking.nguoi_duyet, self.admin)

    def test_customer_click_starts_deposit_countdown_and_reopens_without_reset(self):
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.now().date() + timedelta(days=5),
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            tongGiaTien=50000,
            yeu_cau_thanh_toan=True,
            ngay_gui_yeu_cau_thanh_toan=timezone.now() - timedelta(hours=1),
        )

        history = self.client.get(reverse("lich_su_dat_san"))
        self.assertContains(history, "Cần thanh toán tiền cọc - Nhấp để xem")
        self.assertNotContains(history, "Thông tin đặt cọc")

        response = self.client.post(reverse("mo_yeu_cau_dat_coc", args=[booking.id]))
        self.assertRedirects(
            response,
            reverse("chi_tiet_dat_coc", args=[booking.id]),
        )
        booking.refresh_from_db()
        opened_at = booking.ngay_khach_mo_thanh_toan
        self.assertIsNotNone(opened_at)
        self.assertAlmostEqual((booking.han_thanh_toan - opened_at).total_seconds(), 900)

        detail = self.client.get(reverse("chi_tiet_dat_coc", args=[booking.id]))
        self.assertContains(detail, "Chi tiết thanh toán tiền cọc")
        self.assertContains(detail, 'class="payment-countdown"')
        self.assertContains(detail, f'data-copy="{booking.noi_dung_chuyen_khoan}"')
        self.assertContains(detail, f"<code>{booking.noi_dung_chuyen_khoan}</code>", html=True)
        self.assertRegex(
            booking.noi_dung_chuyen_khoan,
            r"^[A-Z0-9]+_[A-Z0-9]+_[A-Z0-9]+_\d{4}_\d{6}$",
        )
        self.assertContains(detail, "Đã chuyển khoản")
        self.assertContains(detail, "Hủy đặt sân")
        self.assertContains(detail, "Nhấp để sao chép")

        history_after_open = self.client.get(reverse("lich_su_dat_san"))
        self.assertNotContains(history_after_open, "Chi tiết thanh toán tiền cọc")
        self.assertNotContains(history_after_open, "Chủ tài khoản")

        self.client.post(reverse("mo_yeu_cau_dat_coc", args=[booking.id]))
        booking.refresh_from_db()
        self.assertEqual(booking.ngay_khach_mo_thanh_toan, opened_at)

    def test_customer_deposit_confirmation_notifies_admin(self):
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.now().date() + timedelta(days=5),
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            tongGiaTien=50000,
            yeu_cau_thanh_toan=True,
            ngay_gui_yeu_cau_thanh_toan=timezone.now(),
            ngay_khach_mo_thanh_toan=timezone.now(),
        )
        self.client.post(reverse("xac_nhan_da_chuyen_khoan", args=[booking.id]))
        notification = ThongBao.objects.get(nguoi_nhan=self.admin, loai="payment")
        self.assertIn("đã xác nhận đặt cọc", notification.tieu_de)
        self.assertIn(reverse("admin_bookings"), notification.duong_dan)

    def test_customer_cancellation_requires_reason_and_stays_in_history(self):
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.now().date() + timedelta(days=5),
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            tongGiaTien=50000,
        )
        self.client.post(reverse("huy_yeu_cau_dat_san", args=[booking.id]), {"ly_do_huy": "Thay đổi lịch cá nhân"})
        booking.refresh_from_db()
        self.assertEqual(booking.trangThai, "cancelled")
        self.assertEqual(booking.ly_do_huy, "Thay đổi lịch cá nhân")
        history = self.client.get(reverse("lich_su_dat_san"))
        self.assertContains(history, "Thay đổi lịch cá nhân")
        self.assertContains(history, "card-cancelled")
        self.client.post(reverse("xoa_yeu_cau_dat_san", args=[booking.id]))
        self.assertTrue(DatSan.objects.filter(id=booking.id).exists())

    def test_manager_cancellation_reason_is_returned_to_customer(self):
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.now().date() + timedelta(days=5),
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            tongGiaTien=50000,
        )
        self.client.force_login(self.admin)
        self.client.post(
            reverse("admin_booking_action", args=[booking.id]),
            {"action": "cancel", "ly_do_huy": "Sân bảo trì đột xuất"},
        )
        booking.refresh_from_db()
        self.assertEqual(booking.ly_do_huy, "Sân bảo trì đột xuất")
        customer_notice = ThongBao.objects.get(nguoi_nhan=self.user, tieu_de="Đơn đặt sân đã bị hủy")
        self.assertIn("Sân bảo trì đột xuất", customer_notice.noi_dung)

    def test_fixed_booking_deposit_is_ten_thousand_per_booked_day(self):
        group_id = uuid.uuid4()
        start_date = timezone.now().date() + timedelta(days=5)
        for offset in range(30):
            DatSan.objects.create(
                nguoi_dat=self.user,
                san=self.court_1,
                ngayBatDau=start_date + timedelta(days=offset),
                gioBatDau=time(18, 0),
                gioKetThuc=time(19, 0),
                tongGiaTien=40000,
                loaiDatSan=1,
                nhom_dat_san=group_id,
            )
        self.assertEqual(
            DatSan.objects.filter(nhom_dat_san=group_id).aggregate(Sum("so_tien_coc"))["so_tien_coc__sum"],
            Decimal("300000"),
        )
        first_booking = DatSan.objects.filter(nhom_dat_san=group_id).order_by("ngayBatDau").first()
        last_booking = DatSan.objects.filter(nhom_dat_san=group_id).order_by("ngayBatDau").last()
        self.client.force_login(self.admin)
        self.client.post(
            reverse("admin_booking_action", args=[last_booking.id]),
            {"action": "request_payment"},
        )
        expected_content = first_booking.tao_noi_dung_chuyen_khoan(tien_coc=Decimal("300000"))
        self.assertEqual(
            set(
                DatSan.objects.filter(nhom_dat_san=group_id).values_list(
                    "noi_dung_chuyen_khoan", flat=True
                )
            ),
            {expected_content},
        )

        self.client.force_login(self.user)
        self.client.post(reverse("mo_yeu_cau_dat_coc", args=[first_booking.id]))
        detail = self.client.get(reverse("chi_tiet_dat_coc", args=[first_booking.id]))
        self.assertContains(detail, "1.200.000đ")
        self.assertContains(detail, "300.000đ")
        self.assertContains(detail, "900.000đ")
        self.assertContains(detail, f'data-copy="{expected_content}"')
        self.assertContains(detail, f"<code>{expected_content}</code>", html=True)

    def test_admin_only_approves_after_customer_confirms_transfer(self):
        self.client.force_login(self.admin)
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.now().date() + timedelta(days=5),
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            tongGiaTien=50000,
            trangThai="pending",
        )
        self.client.post(reverse("admin_booking_action", args=[booking.id]), {"action": "mark_transfer_received"})
        booking.refresh_from_db()
        self.assertEqual(booking.trangThai, "pending")

        booking.khach_xac_nhan_chuyen_khoan = True
        booking.yeu_cau_thanh_toan = True
        booking.save(update_fields=["khach_xac_nhan_chuyen_khoan", "yeu_cau_thanh_toan"])
        self.client.post(reverse("admin_booking_action", args=[booking.id]), {"action": "mark_transfer_received"})
        booking.refresh_from_db()
        self.assertEqual(booking.trangThai, "confirmed")
        self.assertTrue(booking.daThanhToan)

    def test_expired_deposit_request_cannot_be_confirmed_by_customer(self):
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.now().date() + timedelta(days=5),
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            tongGiaTien=50000,
            yeu_cau_thanh_toan=True,
            ngay_gui_yeu_cau_thanh_toan=timezone.now() - timedelta(hours=1),
            ngay_khach_mo_thanh_toan=timezone.now() - timedelta(minutes=16),
        )
        self.client.post(reverse("xac_nhan_da_chuyen_khoan", args=[booking.id]))
        booking.refresh_from_db()
        self.assertFalse(booking.khach_xac_nhan_chuyen_khoan)

    def test_admin_console_bulk_requests_payment_for_selected_bookings(self):
        self.client.force_login(self.admin)
        booking_1 = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.now().date() + timedelta(days=5),
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            tongGiaTien=50000,
            trangThai="pending",
        )
        booking_2 = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_2,
            ngayBatDau=timezone.now().date() + timedelta(days=6),
            gioBatDau=time(19, 0),
            gioKetThuc=time(20, 0),
            tongGiaTien=60000,
            trangThai="pending",
        )

        response = self.client.post(
            reverse("admin_booking_bulk_action"),
            {"action": "request_payment", "booking_ids": [booking_1.id, booking_2.id]},
        )

        self.assertEqual(response.status_code, 302)
        booking_1.refresh_from_db()
        booking_2.refresh_from_db()
        self.assertTrue(booking_1.yeu_cau_thanh_toan)
        self.assertTrue(booking_2.yeu_cau_thanh_toan)

    def test_admin_console_bulk_delete_requires_confirmation_and_deletes_all_states(self):
        self.client.force_login(self.admin)
        bookings = [
            DatSan.objects.create(
                nguoi_dat=self.user,
                san=self.court_1,
                ngayBatDau=timezone.now().date() + timedelta(days=index + 5),
                gioBatDau=time(18, 0),
                gioKetThuc=time(19, 0),
                tongGiaTien=50000,
                trangThai=status,
            )
            for index, status in enumerate(("pending", "cancelled", "confirmed"))
        ]
        booking_ids = [booking.id for booking in bookings]

        response = self.client.post(
            reverse("admin_booking_bulk_action"),
            {"action": "delete", "booking_ids": booking_ids},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DatSan.objects.filter(id__in=booking_ids).count(), 3)

        response = self.client.post(
            reverse("admin_booking_bulk_action"),
            {
                "action": "delete",
                "booking_ids": booking_ids,
                "delete_confirmed": "yes",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DatSan.objects.filter(id__in=booking_ids).exists())

    @patch.dict(os.environ, {"AI_SUPPORT_ENABLED": "False"}, clear=False)
    def test_ten_customers_can_use_core_booking_payment_and_cancellation_flows(self):
        customers = [
            NguoiDung.objects.create_user(
                username=f"09100000{index:02d}",
                sodienthoai=f"09100000{index:02d}",
                ten=f"Khach Hang {index}",
                password="Test@12345",
            )
            for index in range(10)
        ]
        booking_date = timezone.now().date() + timedelta(days=20)
        active_booking_ids = []
        cancelled_booking_ids = []

        for index, customer in enumerate(customers):
            self.client.force_login(customer)
            for page in ("home", "dien_dan", "lich_cong_dong", "lich_su_dat_san"):
                self.assertEqual(self.client.get(reverse(page)).status_code, 200)
            support_response = self.client.post(
                reverse("support_widget_send"),
                {"message": f"Can ho tro tai khoan {index}", "force_admin": "1"},
            )
            self.assertEqual(support_response.status_code, 200)

            response = self.post_booking(
                self.court_1,
                booking_date + timedelta(days=index),
                start="18:00",
                end="19:00",
            )
            self.assertRedirects(response, reverse("lich_su_dat_san"))
            booking = DatSan.objects.get(nguoi_dat=customer)
            self.assertEqual(booking.trangThai, "pending")

            if index % 2 == 0:
                response = self.client.post(
                    reverse("huy_yeu_cau_dat_san", args=[booking.id]),
                    {"ly_do_huy": f"Khach {index} thay doi lich"},
                )
                self.assertRedirects(response, reverse("lich_su_dat_san"))
                booking.refresh_from_db()
                self.assertEqual(booking.trangThai, "cancelled")
                self.assertTrue(booking.ly_do_huy)
                cancelled_booking_ids.append(booking.id)
            else:
                active_booking_ids.append(booking.id)

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin_booking_bulk_action"),
            {"action": "request_payment", "booking_ids": active_booking_ids},
        )
        self.assertEqual(response.status_code, 302)

        for customer, booking_id in zip(customers[1::2], active_booking_ids):
            self.client.force_login(customer)
            response = self.client.post(reverse("mo_yeu_cau_dat_coc", args=[booking_id]))
            self.assertRedirects(response, reverse("chi_tiet_dat_coc", args=[booking_id]))
            self.assertEqual(self.client.get(reverse("chi_tiet_dat_coc", args=[booking_id])).status_code, 200)
            response = self.client.post(reverse("xac_nhan_da_chuyen_khoan", args=[booking_id]))
            self.assertRedirects(response, reverse("lich_su_dat_san"))

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin_booking_bulk_action"),
            {"action": "mark_transfer_received", "booking_ids": active_booking_ids},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            DatSan.objects.filter(id__in=active_booking_ids, trangThai="confirmed", daThanhToan=True).count(),
            5,
        )
        self.assertEqual(
            DatSan.objects.filter(id__in=cancelled_booking_ids, trangThai="cancelled").count(),
            5,
        )

    def test_select_all_controls_remain_available_after_filtering(self):
        self.client.force_login(self.admin)
        booking = DatSan.objects.create(
            nguoi_dat=self.user,
            san=self.court_1,
            ngayBatDau=timezone.now().date() + timedelta(days=5),
            gioBatDau=time(18, 0),
            gioKetThuc=time(19, 0),
            tongGiaTien=50000,
            trangThai="pending",
        )
        response = self.client.get(reverse("admin_bookings"), {"status": "pending", "q": booking.sdt})
        self.assertContains(response, 'id="selectAllBookings"')
        self.assertContains(response, f'value="{booking.id}" form="bulkBookingForm"')
        self.assertContains(response, "Gửi yêu cầu cọc")
        self.assertContains(response, "Xác nhận cọc & duyệt")
        self.assertContains(response, "Hủy đã chọn")
        self.assertContains(response, "Xóa đã chọn")
        self.assertContains(response, 'name="delete_confirmed"')
        self.assertContains(response, "Xác nhận lần 1")
        self.assertContains(response, "Xác nhận lần 2")

    def test_admin_console_support_reply_updates_message(self):
        self.client.force_login(self.admin)
        thread = HoiThoaiKhachHang.objects.create(nguoi_dung=self.user)
        message = HoTro.objects.create(hoi_thoai=thread, nguoi_dung=self.user, cau_hoi="Can admin")

        self.client.post(
            reverse("admin_support_detail", args=[thread.id]),
            {"message_id": message.id, "tra_loi": "Admin da phan hoi"},
        )
        message.refresh_from_db()
        self.assertEqual(message.tra_loi, "Admin da phan hoi")
        self.assertEqual(message.nguon_tra_loi, "admin")
        self.assertEqual(message.admin_tra_loi, self.admin)
        self.assertTrue(message.da_xem)

    def test_admin_second_reply_becomes_new_message_instead_of_overwriting(self):
        branch_admin = NguoiDung.objects.create_user(
            username="0900000010",
            sodienthoai="0900000010",
            ten="Admin Chat",
            password="Admin@12345",
            role="manager",
            chi_nhanh_quan_ly=self.branch,
        )
        self.client.post(
            reverse("support_widget_send"),
            data='{"message":"Toi can gap admin chi nhanh 1","branch_id":%d,"force_admin":true}' % self.branch.id,
            content_type="application/json",
        )
        conversation = HoiThoaiKhachHang.objects.get(nguoi_dung=self.user, chi_nhanh=self.branch)
        self.client.force_login(branch_admin)

        self.client.post(
            reverse("admin_support_widget_reply"),
            data='{"conversation_id":%d,"reply":"Phan hoi lan 1"}' % conversation.id,
            content_type="application/json",
        )
        self.client.post(
            reverse("admin_support_widget_reply"),
            data='{"conversation_id":%d,"reply":"Phan hoi lan 2"}' % conversation.id,
            content_type="application/json",
        )

        messages = list(conversation.hotro_set.order_by("ngay_gui", "id"))
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].tra_loi, "Phan hoi lan 1")
        self.assertEqual(messages[1].nguoi_gui, "admin")
        self.assertEqual(messages[1].cau_hoi, "Phan hoi lan 2")
        self.assertEqual(messages[1].admin_tra_loi, branch_admin)

    def test_support_widget_routes_admin_request_to_branch_admin(self):
        branch_admin = NguoiDung.objects.create_user(
            username="0900000004",
            sodienthoai="0900000004",
            ten="Admin Chi Nhanh 1",
            password="Admin@12345",
            role="manager",
            chi_nhanh_quan_ly=self.branch,
        )
        other_admin = NguoiDung.objects.create_user(
            username="0900000005",
            sodienthoai="0900000005",
            ten="Admin Chi Nhanh 2",
            password="Admin@12345",
            role="manager",
            chi_nhanh_quan_ly=self.branch_2,
        )

        response = self.client.post(
            reverse("support_widget_send"),
            data='{"message":"Yeu cau gap admin chi nhanh 1","branch_id":%d,"force_admin":true}' % self.branch.id,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        conversation = HoiThoaiKhachHang.objects.get(nguoi_dung=self.user, chi_nhanh=self.branch)
        self.assertTrue(conversation.can_admin)
        self.assertIsNone(conversation.admin_phu_trach)
        message = conversation.hotro_set.latest("id")
        self.assertTrue(message.yeu_cau_admin)
        self.assertFalse(message.tra_loi)

        self.client.force_login(branch_admin)
        response = self.client.get(reverse("admin_support_widget_state"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unread_count"], 1)
        self.assertEqual(response.json()["conversations"][0]["customer_name"], "Khach Test")

        self.client.force_login(other_admin)
        response = self.client.get(reverse("admin_support_widget_state"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unread_count"], 0)
        self.assertEqual(response.json()["conversations"], [])

    def test_branch_admin_can_reply_from_support_widget(self):
        branch_admin = NguoiDung.objects.create_user(
            username="0900000006",
            sodienthoai="0900000006",
            ten="Admin Tra Loi",
            password="Admin@12345",
            role="manager",
            chi_nhanh_quan_ly=self.branch,
        )
        self.client.post(
            reverse("support_widget_send"),
            data='{"message":"Yeu cau gap admin chi nhanh 1","branch_id":%d,"force_admin":true}' % self.branch.id,
            content_type="application/json",
        )
        conversation = HoiThoaiKhachHang.objects.get(nguoi_dung=self.user, chi_nhanh=self.branch)
        self.client.force_login(branch_admin)

        response = self.client.post(
            reverse("admin_support_widget_reply"),
            data='{"conversation_id":%d,"reply":"Admin chi nhanh da nhan yeu cau"}' % conversation.id,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        message = conversation.hotro_set.latest("id")
        self.assertEqual(message.tra_loi, "Admin chi nhanh da nhan yeu cau")
        self.assertEqual(message.admin_tra_loi, branch_admin)
        self.assertTrue(message.da_xem)

        self.client.force_login(self.user)
        response = self.client.get(reverse("support_widget_state"))
        replies = [item["reply"] for item in response.json()["messages"]]
        self.assertIn("Admin chi nhanh da nhan yeu cau", replies)

    def test_admin_can_leave_support_conversation(self):
        branch_admin = NguoiDung.objects.create_user(
            username="0900000011",
            sodienthoai="0900000011",
            ten="Admin Leave",
            password="Admin@12345",
            role="manager",
            chi_nhanh_quan_ly=self.branch,
        )
        self.client.post(
            reverse("support_widget_send"),
            data='{"message":"Toi can gap admin chi nhanh 1","branch_id":%d,"force_admin":true}' % self.branch.id,
            content_type="application/json",
        )
        conversation = HoiThoaiKhachHang.objects.get(nguoi_dung=self.user, chi_nhanh=self.branch)
        self.client.force_login(branch_admin)

        response = self.client.post(
            reverse("admin_support_widget_leave"),
            data='{"conversation_id":%d}' % conversation.id,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        conversation.refresh_from_db()
        self.assertTrue(conversation.can_admin)
        self.assertIsNone(conversation.admin_phu_trach)

    def test_customer_can_delete_chat_history(self):
        self.client.post(
            reverse("support_widget_send"),
            data='{"message":"Huong dan dat san","force_admin":false}',
            content_type="application/json",
        )
        conversation = HoiThoaiKhachHang.objects.filter(nguoi_dung=self.user, da_dong=False).order_by("-ngay_tao").first()
        response = self.client.post(
            reverse("support_widget_delete"),
            data='{"conversation_id":%d}' % conversation.id,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(HoiThoaiKhachHang.objects.filter(id=conversation.id).exists())

    def test_admin_can_delete_chat_history(self):
        branch_admin = NguoiDung.objects.create_user(
            username="0900000012",
            sodienthoai="0900000012",
            ten="Admin Delete",
            password="Admin@12345",
            role="manager",
            chi_nhanh_quan_ly=self.branch,
        )
        self.client.post(
            reverse("support_widget_send"),
            data='{"message":"Toi can gap admin chi nhanh 1","branch_id":%d,"force_admin":true}' % self.branch.id,
            content_type="application/json",
        )
        conversation = HoiThoaiKhachHang.objects.get(nguoi_dung=self.user, chi_nhanh=self.branch)
        self.client.force_login(branch_admin)

        response = self.client.post(
            reverse("admin_support_widget_delete"),
            data='{"conversation_id":%d}' % conversation.id,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(HoiThoaiKhachHang.objects.filter(id=conversation.id).exists())


class SecurityAndScheduleTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = NguoiDung.objects.create_user(
            username="0911111111",
            sodienthoai="0911111111",
            ten="Khách kiểm thử",
            password="Test@12345",
            is_staff=True,
        )
        self.branch = ChiNhanh.objects.create(
            tenChiNhanh="Chi nhánh kiểm thử",
            diaChi="Bạc Liêu",
            sdt="0911111112",
            tenQuanLy="Quản lý kiểm thử",
        )
        self.court = SanCauLong.objects.create(maChiNhanh=self.branch, tenSan="Sân 1")

    def test_system_and_admin_schedules_are_grouped_by_time_then_court(self):
        today = timezone.localdate()
        court_2 = SanCauLong.objects.create(maChiNhanh=self.branch, tenSan="Sân 2")
        court_5 = SanCauLong.objects.create(maChiNhanh=self.branch, tenSan="Sân 5")
        court_6 = SanCauLong.objects.create(maChiNhanh=self.branch, tenSan="Sân 6")
        schedule = [
            (self.court, time(15, 0), time(16, 0)),
            (court_2, time(15, 0), time(16, 0)),
            (court_5, time(17, 0), time(18, 0)),
            (court_6, time(17, 0), time(18, 0)),
        ]
        for court, start, end in reversed(schedule):
            DatSan.objects.create(
                nguoi_dat=self.user,
                san=court,
                ngayBatDau=today,
                gioBatDau=start,
                gioKetThuc=end,
                tongGiaTien=80000,
                trangThai="confirmed",
            )

        self.client.force_login(self.user)
        response = self.client.get(reverse("lich_cong_dong"))

        self.assertEqual(response.status_code, 200)
        expected = [(start, court.tenSan) for court, start, _ in schedule]
        system_schedule = [(item.gioBatDau, item.san.tenSan) for item in response.context["ds_dat_cho"]]
        self.assertEqual(system_schedule, expected)

        admin_response = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(admin_response.status_code, 200)
        admin_schedule = [(item.gioBatDau, item.san.tenSan) for item in admin_response.context["today_schedule"]]
        self.assertEqual(admin_schedule, expected)

    def test_source_guard_is_loaded_for_customer_and_admin_pages(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("home")), "js/source-guard.js")
        self.assertContains(self.client.get(reverse("admin_dashboard")), "js/source-guard.js")

    @override_settings(BOT_PROTECTION_ENABLED=True)
    def test_bot_scanners_and_sensitive_paths_are_blocked(self):
        middleware = BotProtectionMiddleware(lambda request: HttpResponse("ok"))

        sensitive_path = middleware(self.factory.get("/.env", HTTP_USER_AGENT="Mozilla/5.0"))
        scanner_agent = middleware(self.factory.get("/", HTTP_USER_AGENT="sqlmap/1.8"))

        self.assertEqual(sensitive_path.status_code, 404)
        self.assertEqual(scanner_agent.status_code, 404)
        self.assertEqual(sensitive_path["Cache-Control"], "no-store")

    @override_settings(
        RATE_LIMIT_RULES=[
            {"name": "test", "path_prefix": "/api/test/", "methods": {"GET"}, "limit": 1, "window": 60},
        ]
    )
    def test_rate_limit_returns_retry_after(self):
        cache.clear()
        middleware = RequestRateLimitMiddleware(lambda request: HttpResponse("ok"))
        first = middleware(self.factory.get("/api/test/", REMOTE_ADDR="198.51.100.10"))
        second = middleware(self.factory.get("/api/test/", REMOTE_ADDR="198.51.100.10"))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second["Retry-After"], "60")

    def test_security_response_headers_are_added(self):
        middleware = SecurityResponseHeadersMiddleware(lambda request: HttpResponse("ok"))
        response = middleware(self.factory.get("/"))

        self.assertEqual(response["X-Permitted-Cross-Domain-Policies"], "none")
        self.assertIn("camera=()", response["Permissions-Policy"])
