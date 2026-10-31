# KhetKavach backend for Hugging Face Spaces (Docker SDK, free CPU). Listens on port 7860.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Hugging Face runs Spaces as user 1000; give it a home for caches.
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

# rasterio wheels bundle GDAL, so no system GDAL packages are needed.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=user app ./app

USER user
ENV HOME=/home/user
EXPOSE 7860
# Render sets $PORT; Hugging Face uses 7860.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips '*'"]
