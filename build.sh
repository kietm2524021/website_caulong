#!/usr/bin/env bash
set -o errexit
export DJANGO_SETTINGS_MODULE=my_badminton.settings

# Cài đặt/Cập nhật thư viện
pip install --upgrade pip
pip install -r requirements.txt

# Gom file tĩnh
python manage.py collectstatic --noinput

# Cập nhật Database
python manage.py migrate

# Tạo dữ liệu mặc định an toàn, không nhân đôi khi deploy lại
python manage.py seed_defaults
