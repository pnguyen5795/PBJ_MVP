FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system pbj \
    && useradd --system --gid pbj --home-dir /app pbj

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY docker-entrypoint.sh /usr/local/bin/pbj-entrypoint
RUN chmod 0755 /usr/local/bin/pbj-entrypoint \
    && mkdir -p /var/data \
    && chown -R pbj:pbj /app /var/data

EXPOSE 10000

ENTRYPOINT ["pbj-entrypoint"]
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]
