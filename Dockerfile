FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt .

# Keep dependency and browser installation in a cached layer so normal code
# changes do not force Railway to redownload Chromium on every deploy.
RUN pip install -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

CMD ["python", "main.py"]
