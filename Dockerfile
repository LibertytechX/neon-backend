FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# collect static + apply migrations at start, then serve with gunicorn
ENV DJANGO_DEBUG=false
EXPOSE 8000
CMD sh -c "python manage.py migrate --noinput && \
           gunicorn neonslot_api.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-3}"
