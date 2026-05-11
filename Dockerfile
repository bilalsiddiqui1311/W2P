FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    W2P_DB_PATH=/data/w2p.sqlite3

RUN addgroup --system w2p && adduser --system --ingroup w2p w2p

WORKDIR /app

COPY pyproject.toml README.md ./
COPY w2p ./w2p
COPY frontend ./frontend

RUN pip install --no-cache-dir .
RUN mkdir -p /data && chown -R w2p:w2p /data

USER w2p
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"

CMD ["uvicorn", "w2p.api:app", "--host", "0.0.0.0", "--port", "8080"]
