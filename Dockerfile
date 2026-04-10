FROM python:3.12-slim

WORKDIR /app

# Systeemafhankelijkheden
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App-code
COPY app/ ./app/
COPY static/ ./static/

# Data-map voor SQLite
RUN mkdir -p /app/data

# Non-root gebruiker
RUN useradd -m -u 1000 kmvuser && chown -R kmvuser:kmvuser /app
USER kmvuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
