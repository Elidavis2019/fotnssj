# ════════════════════════════════════════════════════════════════════════
# FOTNSSJ — Single image, MODE controls active routes
#
# Build:  docker build -t fotnssj .
# Run:    docker-compose up --build -d
# ════════════════════════════════════════════════════════════════════════
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -r fotnssj \
    && useradd -r -g fotnssj -d /app -s /sbin/nologin fotnssj

WORKDIR /app

# Dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY fotnssj.py .
COPY geometry/   geometry/
COPY branches/   branches/
COPY dispatch/   dispatch/
COPY sync/       sync/

# Data directories — volumes mount here at runtime
RUN mkdir -p \
    /data/checkpoints \
    /data/sessions \
    /data/auth \
    /data/state \
    /data/geometry \
    /data/stations \
    && chown -R fotnssj:fotnssj /data /app

USER fotnssj

HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=20s \
    --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

EXPOSE 5000

CMD ["python", "fotnssj.py"]