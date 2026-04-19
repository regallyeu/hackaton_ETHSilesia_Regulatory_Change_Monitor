FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY isap_crawler.py .
COPY isap_extract_changes.py .
COPY docker/crawler/entrypoint.sh /entrypoint.sh
# Windows checkouts often use CRLF; kernel then looks for "/bin/sh\r" → "no such file or directory"
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

VOLUME ["/isap_data"]

# Invoke via sh so CRLF in shebang cannot break kernel execve (still normalize line endings below).
ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]
