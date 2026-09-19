# API image. The same image runs the notification worker (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY migrate.py manage.py seed.py ./

# Run as an unprivileged user; uploaded files go to a volume owned by that user.
RUN useradd --create-home --uid 10001 hcrm && mkdir -p /data/storage && chown hcrm /data/storage
USER hcrm
ENV STORAGE_DIR=/data/storage

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
