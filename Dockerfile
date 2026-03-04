FROM python:3.12-slim

# Set UTC timezone for consistent candle timestamps
ENV TZ=UTC

# Install tzdata for timezone support
RUN apt-get update && apt-get install -y --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install production dependencies only
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

# Create non-root user for security and own the app directory
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser \
    && mkdir -p /app/data && chown -R appuser:appgroup /app

USER appuser

EXPOSE 5000

CMD ["python", "main.py"]
