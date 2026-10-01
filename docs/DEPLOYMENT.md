# Deployment

V1 runs fine on a single small server (or a PaaS such as Render, Railway or Fly.io) with PostgreSQL.

## Checklist

1. **Environment** (see `.env.example`):
   ```
   DJANGO_DEBUG=false
   DJANGO_SECRET_KEY=<long random value>
   DJANGO_ALLOWED_HOSTS=api.yourdomain.com
   DJANGO_CSRF_TRUSTED_ORIGINS=https://api.yourdomain.com
   CORS_ALLOWED_ORIGINS=https://app.yourdomain.com
   FRONTEND_URL=https://app.yourdomain.com
   BACKEND_URL=https://api.yourdomain.com
   PAYSTACK_SECRET_KEY=sk_live_...       # only when going live
   PAYSTACK_PUBLIC_KEY=pk_live_...
   PAYSTACK_CALLBACK_URL=https://app.yourdomain.com/payments/complete
   EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
   EMAIL_HOST=... EMAIL_HOST_USER=... EMAIL_HOST_PASSWORD=...
   DEFAULT_FROM_EMAIL=no-reply@yourdomain.com
   ```
   With `DJANGO_DEBUG=false` the app refuses to start without a secret key, forces HTTPS
   redirects, sets secure cookies and HSTS, and ignores `PAYSTACK_SIMULATE`.

2. **PostgreSQL:**
   ```
   pip install "psycopg[binary]>=3.2"
   DB_ENGINE=postgres DB_NAME=... DB_USER=... DB_PASSWORD=... DB_HOST=... DB_PORT=5432
   ```

3. **Build and run:**
   ```bash
   pip install -r requirements.txt gunicorn
   python manage.py migrate
   python manage.py collectstatic --noinput
   gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
   ```
   Put Nginx or the platform's proxy in front for HTTPS. It must send `X-Forwarded-Proto`.

4. **Media files** (school logos, student photos, uploaded import files) are stored in
   `MEDIA_ROOT`. Back this up with the database, or switch to object storage (for example
   `django-storages` with S3-compatible storage) when you scale.

5. **Create the first school:**
   ```bash
   python manage.py createsuperuser        # platform operator (Django admin)
   python manage.py create_school --name "Bright Future College" \
       --principal-email principal@brightfuture.ng --principal-password '<temporary>'
   ```
   The principal logs in and the admin account is created from the staff screen.

6. **Paystack:** set the webhook URL to `https://api.yourdomain.com/api/v1/payments/paystack/webhook/`.

7. **Health check:** `GET /health/` returns `{"status": "ok"}`.

## Security and data protection

You are holding children's personal data and financial records. Before a real pilot:

- [ ] HTTPS only (automatic when `DJANGO_DEBUG=false` behind a proxy that sets `X-Forwarded-Proto`).
- [ ] Strong `DJANGO_SECRET_KEY`, never committed. Rotating it invalidates all pay, receipt and report-card links and password-reset links.
- [ ] Daily database backups, kept off the server, with a tested restore.
- [ ] Restrict Django admin to platform operators; consider IP allow-listing `/admin/`.
- [ ] Review who has the principal and admin roles at each school.
- [ ] A privacy notice for schools and parents, a data-processing agreement with each school, and a retention and deletion policy. **Get advice on Nigeria's Data Protection Act (NDPA) obligations.**
- [ ] Monitor the audit log for unusual activity (bulk exports, many failed logins).
- [ ] Keep dependencies updated (Django 5.2 is an LTS release).

## Scaling notes

* PDFs and imports run in the web request. That is fine for one class or a few hundred rows. For whole-school runs, add Celery + Redis and move `render_report_cards` and `commit_import` into tasks.
* Add a cache (Redis) so rate limiting is shared across workers.
* The dashboards use aggregate queries; add indexes or caching if a school grows past a few thousand students.
