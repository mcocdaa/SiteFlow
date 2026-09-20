FROM python:3.13-slim

LABEL org.opencontainers.image.title="SiteFlow" \
      org.opencontainers.image.description="Docker 化的个人作品画廊与静态制品沙箱展示平台" \
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
COPY DESIGN.md README.md pyproject.toml ./

RUN mkdir -p /data && chown -R app:app /data /srv/siteflow
USER app

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
