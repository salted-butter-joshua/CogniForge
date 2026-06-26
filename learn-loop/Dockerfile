FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libxml2-dev libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ ./config/
COPY src/ ./src/
COPY docker/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV OUTPUT_DIR=/app/outputs
ENV LOOP_URLS=https://docs.python.org/3/tutorial/index.html
ENV LOOP_GOAL="Master core Python tutorial concepts"
ENV LOOP_TASK_ID=cogniforge-default

RUN mkdir -p /app/outputs

ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]
