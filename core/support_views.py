import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import HoiThoaiKhachHang
from .support_chat import serialize_customer_state


@login_required(login_url="login")
@require_POST
def support_widget_delete(request):
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else request.POST
    except json.JSONDecodeError:
        return JsonResponse({"error": "Dữ liệu gửi không hợp lệ."}, status=400)

    conversation_id = payload.get("conversation_id")
    qs = HoiThoaiKhachHang.objects.filter(nguoi_dung=request.user, da_dong=False)
    conversation = qs.filter(id=conversation_id).first() if conversation_id else qs.order_by("-ngay_tao").first()
    if not conversation:
        return JsonResponse({"error": "Không tìm thấy hội thoại cần xóa."}, status=404)

    conversation.delete()
    return JsonResponse({"ok": True, "state": serialize_customer_state(request.user)})
