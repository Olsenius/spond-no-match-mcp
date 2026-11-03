FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /build
COPY requirements.txt .
RUN uv pip install --system --no-cache --prefix=/install -r requirements.txt

FROM python:3.12-slim
COPY --from=builder /install /usr/local
RUN python -m compileall -q /usr/local/lib/python3.12
WORKDIR /app
COPY main.py server.py settings.py telemetry.py ./
RUN python -m compileall -q /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DATA_DIR=/data
# Settings saved on the gateway's settings page live here; mount a volume.
RUN mkdir /data && chown 1001:1001 /data && chmod 700 /data
VOLUME /data
USER 1001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8080'), timeout=4)"]
CMD ["python", "main.py"]
