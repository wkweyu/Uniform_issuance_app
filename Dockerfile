FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# system deps (add more if build fails for binary packages like WeasyPrint)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    libjpeg-dev \
    zlib1g-dev \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libglib2.0-0 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    fonts-dejavu-core \
    gcc \
    curl \
 && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage caching
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# Copy application code
COPY . /app

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:5000/health || exit 1

# Use gunicorn with the factory `create_app()` function
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:create_app()", "--workers", "3"]
