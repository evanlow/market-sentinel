FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system sentinel && adduser --system --ingroup sentinel sentinel \
    && mkdir -p /data && chown -R sentinel:sentinel /data /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY wsgi.py ./

RUN pip install --upgrade pip && pip install .

USER sentinel

ENV DATABASE_URL=sqlite:////data/market_sentinel.db \
    PORT=8000

EXPOSE 8000
VOLUME ["/data"]

CMD ["sh", "-c", "gunicorn --workers 2 --threads 4 --timeout 60 --bind 0.0.0.0:${PORT} wsgi:app"]
