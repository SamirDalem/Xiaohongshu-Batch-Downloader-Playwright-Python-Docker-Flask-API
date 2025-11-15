# Use an official slim Python image
FROM python:3.12-slim

# Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /work

# Install minimal system libs required by Playwright
# Note: libgdk-pixbuf2.0-0 replaced with libgdk-pixbuf-xlib-2.0-0 for newer Debian variants
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    wget \
    gnupg \
    locales \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxss1 \
    libasound2 \
    libgbm1 \
    libgtk-3-0 \
    libx11-6 \
    libx11-xcb1 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    fonts-liberation \
    fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/*

# Copy your Flask/playwright app into the image (make sure file exists in build context)
COPY app_playwright_update.py /work/app_playwright_update.py

# Install Python deps (Flask + Playwright). If you have extra deps, add them here or use requirements.txt.
RUN pip install --upgrade pip setuptools wheel \
 && pip install flask requests playwright aiohttp tqdm

# Install Playwright browsers (Chromium/Firefox/WebKit). This downloads the browsers.
RUN python -m playwright install --with-deps

# Create folders for downloads/debug
RUN mkdir -p /work/downloads /work/debug

EXPOSE 6000

CMD ["python", "/work/app_playwright_update.py"]
