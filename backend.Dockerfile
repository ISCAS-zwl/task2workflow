FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY server/ ./server/
COPY node/ ./node/
COPY tools/ ./tools/
COPY prompt/ ./prompt/

ENV PYTHONPATH=/app

EXPOSE 8182

CMD ["uvicorn", "server.websocket_server:app", "--host", "0.0.0.0", "--port", "8182"]
