FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for OpenCV and image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy repository
COPY . .

# Expose FastAPI service port
EXPOSE 8000

ENV PORT=8000
ENV HOST=0.0.0.0

CMD ["uvicorn", "tarang.service.app:app", "--host", "0.0.0.0", "--port", "8000"]
