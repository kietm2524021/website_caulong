# Website Caulong

Django app for badminton court booking, forum posts, and customer support.

## Local development

```powershell
.\venv\Scripts\Activate.ps1
python manage.py migrate
python manage.py runserver
```

Local commands use:

```text
my_badminton.settings_local
```

## Production

Deploy commands should use:

```text
my_badminton.settings
```

Required environment variables are listed in `.env.example`.

Typical start command:

```bash
gunicorn my_badminton.wsgi:application
```
