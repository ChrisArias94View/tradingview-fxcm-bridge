FROM python:3.7-slim-buster

WORKDIR /app

RUN apt-get update && \
    apt-get install -y \
    libstdc++6 \
    libgcc1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD gunicorn --bind 0.0.0.0:${PORT:-10000} app:app
