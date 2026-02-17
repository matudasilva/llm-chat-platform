FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Minimal system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Install runtime dependencies first (cache-friendly)
COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Dev-only: optionally install test/dev dependencies (e.g., pytest)
ARG INSTALL_DEV_DEPS=0
COPY app/requirements-dev.txt /app/requirements-dev.txt
RUN if [ "$INSTALL_DEV_DEPS" = "1" ]; then \
      pip install --no-cache-dir -r /app/requirements-dev.txt ; \
    fi

# Copy application code (prod image remains self-contained)
COPY app /app/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
