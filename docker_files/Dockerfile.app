# ============================================================================
# Stage 1: Python Builder
# ============================================================================
# NOTE: Frontend is pre-built (frontend/dist/) and committed to the repo.
# To rebuild: cd frontend && npm install && npm run build
# This avoids Node.js build issues on restricted environments (RHEL/SELinux).
FROM docker.io/python:3.11-slim AS builder

WORKDIR /app

# Build arg: LLM_PROFILE controls which dependencies are installed
# Options: LITE (default), MED, MAX
ARG LLM_PROFILE=LITE
# Build arg: USE_LOCK=true to use pinned versions from requirements.lock
ARG USE_LOCK=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Base system dependencies (always needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libpq-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy all requirements files (lock file is optional)
COPY containers/app/requirements.base.txt ./requirements.base.txt
COPY containers/app/requirements.med.txt ./requirements.med.txt
COPY containers/app/requirements.max.txt ./requirements.max.txt
# Install Python dependencies based on profile
# When USE_LOCK=true and requirements.lock exists, use pinned versions for
# reproducible builds. Otherwise fall back to requirements.base.txt ranges.
RUN if [ "$USE_LOCK" = "true" ] && [ -f requirements.lock ]; then \
      echo "Installing from requirements.lock (pinned versions)" && \
      pip install --no-cache-dir -r requirements.lock; \
    else \
      echo "Installing from requirements.base.txt (version ranges)" && \
      pip install --no-cache-dir -r requirements.base.txt && \
      if [ "$LLM_PROFILE" = "MED" ] || [ "$LLM_PROFILE" = "MAX" ]; then \
        pip install --no-cache-dir -r requirements.med.txt; \
      fi && \
      if [ "$LLM_PROFILE" = "MAX" ]; then \
        pip install --no-cache-dir -r requirements.max.txt && \
        playwright install --with-deps chromium; \
      fi; \
    fi

# ============================================================================
# Stage 2: Final Image
# ============================================================================
FROM docker.io/python:3.11-slim

WORKDIR /app

ARG LLM_PROFILE=LITE

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    LISTEN_PORT=8000 \
    PATH="/opt/venv/bin:$PATH" \
    DEBIAN_FRONTEND=noninteractive

# Create a non-root user and group
RUN groupadd --gid 1001 chainlit_group && \
    useradd --uid 1001 --gid 1001 -ms /bin/bash chainlit_user

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    openssl \
    libpq5 \
    && if [ "$LLM_PROFILE" = "MAX" ]; then \
      apt-get install -y --no-install-recommends \
        libglib2.0-0 libnspr4 libnss3 libdbus-1-3 \
        libatk1.0-0 libatk-bridge2.0-0 libcups2 libxcb1 \
        libxkbcommon0 libatspi2.0-0 libx11-6 libxcomposite1 \
        libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 \
        libcairo2 libpango-1.0-0 libasound2; \
    fi \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI for container management from admin UI
# Using static binary (smaller than docker.io package, includes only the CLI)
RUN curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz \
    | tar xz --strip-components=1 -C /usr/local/bin docker/docker \
    && chmod +x /usr/local/bin/docker \
    && groupadd -f docker \
    && usermod -aG docker chainlit_user
# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy application code + config
COPY chat_app /app/chat_app
COPY public /app/public
COPY shared /app/shared
COPY skills /app/skills
COPY config.yaml /app/config.yaml
COPY config /app/config
COPY VERSION /app/VERSION
COPY CHANGELOG.md /app/CHANGELOG.md
COPY postgres /app/postgres
COPY metadata /app/metadata
COPY frontend/dist /app/admin-ui

# Copy and set up the entrypoint script
COPY docker_files/entrypoint.app.sh /app/entrypoint.sh

# Set ownership, permissions, and pre-create mount-point directories
RUN chmod +x /app/entrypoint.sh && \
    mkdir -p /app/.chainlit/blobs \
             /app/shared/public/documents/specs \
             /app/shared/public/documents/commands \
             /app/shared/public/documents/repo \
             /app/shared/public/documents/pdfs \
             /app/shared/public/documents/cribl \
             /app/shared/public/documents/feedback \
             /app/data \
             /app/certs && \
    chown -R chainlit_user:chainlit_group /app

# Switch to the non-root user
USER chainlit_user

EXPOSE 8000

# Health check: verify the Chainlit HTTP server is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8090/ || exit 1

ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
