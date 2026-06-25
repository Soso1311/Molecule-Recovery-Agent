FROM python:3.11-slim

# Creates a non-root user. Running as root inside a container violates the
# principle of least privilege and widens the blast radius of any escape.
RUN groupadd --gid 1001 appuser && \
    useradd --uid 1001 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies before copying application code so Docker can cache
# this layer and skip reinstalling on code only changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copies the application code (respects .dockerignore).
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
