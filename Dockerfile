FROM python:3.12-slim

LABEL org.opencontainers.image.title="SiteFlow" \
      org.opencontainers.image.description="Docker 化的个人作品画廊：上传 HTML / ZIP / 外链，CSP sandbox 隔离" \
      org.opencontainers.image.source="https://github.com/mcocdaa/SiteFlow" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /srv/siteflow

RUN useradd --create-home --uid 1000 app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY DESIGN.md README.md ./

RUN mkdir -p /data && chown -R app:app /data /srv/siteflow
USER app

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
