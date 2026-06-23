from django.urls import path
from . import views
from . import admin_views
from . import support_views

# Tên gợi nhớ để gọi trong template (ví dụ: {% url 'home' %})
urlpatterns = [
    # --- Trang chủ ---
    path('', views.home, name='home'),

    # --- Xác thực (Auth) ---
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # --- Đặt sân ---
    path('dat-san/', views.dat_san_view, name='dat_san'),
    path('lich-su-dat-san/', views.lich_su_dat_san, name='lich_su_dat_san'),
    path('lich-su-dat-san/<int:booking_id>/mo-dat-coc/', views.mo_yeu_cau_dat_coc, name='mo_yeu_cau_dat_coc'),
    path('lich-su-dat-san/<int:booking_id>/chi-tiet-dat-coc/', views.chi_tiet_dat_coc, name='chi_tiet_dat_coc'),
    path('lich-su-dat-san/<int:booking_id>/huy/', views.huy_yeu_cau_dat_san, name='huy_yeu_cau_dat_san'),
    path('lich-su-dat-san/<int:booking_id>/xoa/', views.xoa_yeu_cau_dat_san, name='xoa_yeu_cau_dat_san'),
    path('lich-su-dat-san/<int:booking_id>/da-chuyen-khoan/', views.xac_nhan_da_chuyen_khoan, name='xac_nhan_da_chuyen_khoan'),
    path('hoa-don/<int:booking_id>/', views.xuat_hoa_don, name='xuat_hoa_don'),
    path('hoa-don/<int:booking_id>/anh/', views.tai_hoa_don_anh, name='tai_hoa_don_anh'),

    # --- Diễn đàn ---
    path('dien-dan/', views.dien_dan_view, name='dien_dan'),
    path('dien-dan/tao-bai/', views.tao_bai_viet, name='tao_bai_viet'),

    # --- Hỗ trợ ---
    path('ho-tro/', views.support_view, name='support'),
    path('api/ho-tro/widget/', views.support_widget_state, name='support_widget_state'),
    path('api/ho-tro/widget/gui/', views.support_widget_send, name='support_widget_send'),
    path('api/ho-tro/widget/xoa/', support_views.support_widget_delete, name='support_widget_delete'),
    path('api/live/', views.customer_live_state, name='customer_live_state'),
    path('lich-cong-dong/', views.lich_cong_dong, name='lich_cong_dong'),
    path('dien-dan/bai-viet/<int:bai_id>/', views.chi_tiet_bai_viet, name='chi_tiet_bai_viet'),
    path('xoa-binh-luan/<int:bl_id>/', views.xoa_binh_luan, name='xoa_binh_luan'),
    path('api/update-recruitment/', views.update_recruitment, name='update_recruitment'),

    # --- Console quản trị mới ---
    path('quan-tri/', admin_views.admin_dashboard, name='admin_dashboard'),
    path('quan-tri/api/live/', admin_views.admin_live_state, name='admin_live_state'),
    path('quan-tri/don-dat-san/', admin_views.admin_bookings, name='admin_bookings'),
    path('quan-tri/don-dat-san/bulk-action/', admin_views.admin_booking_bulk_action, name='admin_booking_bulk_action'),
    path('quan-tri/don-dat-san/<int:booking_id>/action/', admin_views.admin_booking_action, name='admin_booking_action'),
    path('quan-tri/thong-bao/<int:notification_id>/mo/', admin_views.admin_notification_open, name='admin_notification_open'),
    path('quan-tri/thong-bao/doc-tat-ca/', admin_views.admin_notifications_read_all, name='admin_notifications_read_all'),
    path('quan-tri/san-chi-nhanh/', admin_views.admin_courts, name='admin_courts'),
    path('quan-tri/bai-viet/', admin_views.admin_posts, name='admin_posts'),
    path('quan-tri/bai-viet/<int:post_id>/action/', admin_views.admin_post_action, name='admin_post_action'),
    path('quan-tri/ho-tro/', admin_views.admin_support, name='admin_support'),
    path('quan-tri/ho-tro/<int:conversation_id>/', admin_views.admin_support, name='admin_support_detail'),
    path('quan-tri/api/ho-tro/widget/', admin_views.admin_support_widget_state, name='admin_support_widget_state'),
    path('quan-tri/api/ho-tro/widget/tra-loi/', admin_views.admin_support_widget_reply, name='admin_support_widget_reply'),
    path('quan-tri/api/ho-tro/widget/roi/', admin_views.admin_support_widget_leave, name='admin_support_widget_leave'),
    path('quan-tri/api/ho-tro/widget/xoa/', admin_views.admin_support_widget_delete, name='admin_support_widget_delete'),
    path('quan-tri/nguoi-dung/', admin_views.admin_users, name='admin_users'),
    path('quan-tri/nguoi-dung/<int:user_id>/update/', admin_views.admin_user_update, name='admin_user_update'),
]
