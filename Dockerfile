FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend

# Mount point for the Railway/Fly volume: holds runs.db + decoded Mongo TLS cert
RUN mkdir -p /data
ENV EVAL_DB_PATH=/data/runs.db \
    MONGO_TLS_CA_PATH=/data/cred.pem \
    PORT=8010 \
    PYTHONUNBUFFERED=1

EXPOSE 8010

# Railway / Fly inject $PORT at runtime
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
