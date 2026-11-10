FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

EXPOSE 8085
HEALTHCHECK --interval=30s --timeout=6s --retries=3 \
  CMD python -c "import os,urllib.request; b='/'+os.environ.get('BASE_PATH','').strip('/'); urllib.request.urlopen('http://127.0.0.1:8085'+b.rstrip('/')+'/api/status', timeout=5)"

# Nur EIN Worker: Warteschlange liegt im Speicher
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8085", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
