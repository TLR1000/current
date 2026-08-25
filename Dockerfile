FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CURRENT_DB=/data/current.sqlite3 \
    CURRENT_DIAMONDS_FILE=/app/data/diamonds.txt

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY scripts ./scripts

RUN mkdir -p /data && useradd --system --uid 10001 --create-home current \
    && chown -R current:current /data

USER current

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
