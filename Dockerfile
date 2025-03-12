FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    fonts-dejavu \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000
CMD ["gunicorn", "-b", "0.0.0.0:8000", "--timeout", "600", "app:app"]