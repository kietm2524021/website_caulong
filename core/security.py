import logging
import os
import re
import time
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone


logger = logging.getLogger("security")


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "unknown")[:45]


def normalize_plain_text(value, max_length=1000, field_label="Nội dung"):
    text = " ".join((value or "").split())
    if not text:
        raise ValidationError(f"{field_label} không được để trống.")
    if len(text) > max_length:
        raise ValidationError(f"{field_label} không được vượt quá {max_length} ký tự.")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise ValidationError(f"{field_label} chứa ký tự không hợp lệ.")
    return text


def validate_uploaded_file(
    uploaded_file,
    *,
    allowed_extensions,
    allowed_content_types,
    max_size,
    field_label="Tệp",
):
    if not uploaded_file:
        return uploaded_file

    extension = os.path.splitext(uploaded_file.name or "")[1].lower()
    if extension not in {item.lower() for item in allowed_extensions}:
        raise ValidationError(f"{field_label} phải có định dạng: {', '.join(sorted(allowed_extensions))}.")

    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    if content_type and content_type not in {item.lower() for item in allowed_content_types}:
        raise ValidationError(f"{field_label} có MIME type không được phép.")

    if uploaded_file.size > max_size:
        raise ValidationError(f"{field_label} vượt quá dung lượng cho phép {max_size // (1024 * 1024)}MB.")

    return uploaded_file


class PasswordComplexityValidator:
    def validate(self, password, user=None):
        errors = []
        if not re.search(r"[A-Z]", password or ""):
            errors.append("ít nhất 1 chữ hoa")
        if not re.search(r"[a-z]", password or ""):
            errors.append("ít nhất 1 chữ thường")
        if not re.search(r"\d", password or ""):
            errors.append("ít nhất 1 chữ số")
        if not re.search(r"[^A-Za-z0-9]", password or ""):
            errors.append("ít nhất 1 ký tự đặc biệt")
        if errors:
            raise ValidationError("Mật khẩu phải có " + ", ".join(errors) + ".")

    def get_help_text(self):
        return "Mật khẩu phải có chữ hoa, chữ thường, số và ký tự đặc biệt."


def is_user_locked(user):
    return bool(user.locked_until and user.locked_until > timezone.now())


def reset_login_failures(user):
    changed_fields = []
    if user.failed_login_attempts:
        user.failed_login_attempts = 0
        changed_fields.append("failed_login_attempts")
    if user.locked_until:
        user.locked_until = None
        changed_fields.append("locked_until")
    if changed_fields:
        user.save(update_fields=changed_fields)


def register_failed_login(user):
    now = timezone.now()
    if user.locked_until and user.locked_until <= now:
        user.failed_login_attempts = 0
        user.locked_until = None

    user.failed_login_attempts += 1
    if user.failed_login_attempts >= settings.LOGIN_FAILURE_LIMIT:
        user.locked_until = now + timedelta(seconds=settings.LOGIN_LOCKOUT_SECONDS)
    user.save(update_fields=["failed_login_attempts", "locked_until"])
    return is_user_locked(user)


def build_lockout_message(user):
    if not user.locked_until:
        return "Tài khoản đang tạm thời bị khóa."
    remaining = max(1, int((user.locked_until - timezone.now()).total_seconds() // 60) + 1)
    return f"Tài khoản đang tạm khóa. Vui lòng thử lại sau khoảng {remaining} phút."


class SessionIdleTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            timeout_seconds = int(getattr(settings, "SESSION_IDLE_TIMEOUT", 3600))
            now_ts = int(time.time())
            last_activity = request.session.get("last_activity_ts")
            if last_activity and now_ts - int(last_activity) > timeout_seconds:
                logger.info(
                    "Session expired due to inactivity user=%s ip=%s",
                    request.user.pk,
                    get_client_ip(request),
                )
                logout(request)
                request.session.flush()
                if request.path.startswith("/api/") or request.path.startswith("/quan-tri/api/"):
                    return JsonResponse({"error": "Phiên đăng nhập đã hết hạn."}, status=401)
                messages.warning(request, "Phiên đăng nhập đã hết hạn do không hoạt động.")
                return redirect(settings.LOGIN_URL)
            request.session["last_activity_ts"] = now_ts

        return self.get_response(request)


class RequestRateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.rules = getattr(settings, "RATE_LIMIT_RULES", [])

    def __call__(self, request):
        ip_address = get_client_ip(request)
        path = request.path or "/"
        method = request.method.upper()

        for rule in self.rules:
            if rule.get("methods") and method not in rule["methods"]:
                continue
            prefix = rule.get("path_prefix")
            if prefix and not path.startswith(prefix):
                continue
            window = int(rule.get("window", 60))
            limit = int(rule.get("limit", 60))
            key = f"ratelimit:{rule.get('name', prefix)}:{ip_address}"
            current = cache.get(key, 0)
            if current >= limit:
                logger.warning(
                    "Rate limit blocked name=%s ip=%s path=%s",
                    rule.get("name", prefix),
                    ip_address,
                    path,
                )
                if path.startswith("/api/") or path.startswith("/quan-tri/api/"):
                    return JsonResponse({"error": "Bạn thao tác quá nhanh. Vui lòng thử lại sau."}, status=429)
                return HttpResponse("Too many requests", status=429)
            if current == 0:
                cache.set(key, 1, timeout=window)
            else:
                try:
                    cache.incr(key)
                except ValueError:
                    cache.set(key, current + 1, timeout=window)

        return self.get_response(request)
