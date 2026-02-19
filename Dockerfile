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
    gcc \
    curl \
 && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage caching
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# Copy application code
COPY . /app

EXPOSE 5000

# Use gunicorn with the factory `create_app()` function
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:create_app()", "--workers", "3"]
