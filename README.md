# Website Caulong

Django app for badminton court booking, forum posts, and customer support.

## Local development

```powershell
.\venv\Scripts\Activate.ps1
python manage.py migrate
python manage.py seed_defaults
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

`build.sh` runs `seed_defaults` after migrations. The command safely creates one
admin (when `CREATE_SUPERUSER=True`), branches `Lê Giang 1` and `Lê Giang 2`,
and courts `Sân 1` through `Sân 7` for each branch. Re-running it does not create
duplicates or reset an existing admin password. Configure admin credentials and
optional branch contact details with the variables documented in `.env.example`.
