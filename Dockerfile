# Multi-stage image (decision D4): python:3.12-slim, uid 10001, read-only root
# filesystem friendly (writable paths: /tmp as tmpfs and the /data volume).

FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN python -m venv /opt/venv
# Only the hashed runtime lock is installed: no development package can enter
# the image, and --require-hashes refuses anything not in the lock.
COPY requirements.txt ./
RUN /opt/venv/bin/pip install --require-hashes --no-deps -r requirements.txt

FROM python:3.12-slim
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ROLE=all \
    EVIDENCE_DIR=/data/evidence
RUN groupadd --system --gid 10001 revrook \
    && useradd --system --uid 10001 --gid 10001 --no-create-home \
        --shell /usr/sbin/nologin revrook \
    && mkdir -p /data/evidence \
    && chown -R 10001:10001 /data
COPY --from=builder /opt/venv /opt/venv
WORKDIR /srv/revrook
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status == 200 else 1)"]
# ROLE=all (default) starts web and worker as two processes. Use ROLE=web or
# ROLE=worker, or pass a subcommand, to run one role.
ENTRYPOINT ["python", "-m", "app.cli"]
