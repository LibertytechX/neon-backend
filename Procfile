release: python manage.py migrate --noinput
web: gunicorn neonslot_api.wsgi:application --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-3}
