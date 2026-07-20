# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12.13-slim-trixie@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

FROM --platform=linux/amd64 ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

RUN python -m venv "${VIRTUAL_ENV}"
WORKDIR /build
COPY requirements/production-linux-x86_64-python3.12.txt requirements/production.txt
RUN python -m pip install --require-hashes --no-deps --requirement requirements/production.txt

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip wheel --no-deps --wheel-dir /tmp/wheels . \
    && python -m pip install --no-deps /tmp/wheels/scalescore-*.whl \
    && python -m pip check

FROM --platform=linux/amd64 ${PYTHON_IMAGE} AS runtime

ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="Proofhouse Readiness" \
      org.opencontainers.image.description="Readiness API and optional async worker runtime" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="https://github.com/im-sham/scalescore"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8000

RUN rm -rf /usr/local/lib/python3.12/site-packages /usr/local/bin/pip* \
    && groupadd --gid 10001 scalescore \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app --shell /usr/sbin/nologin scalescore \
    && mkdir -p /app/.local/scalescore \
    && chown -R 10001:10001 /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 docker/entrypoint.sh /usr/local/bin/scalescore-container

WORKDIR /app
USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('SERVER_PORT', '8000') + '/api/v1/health', timeout=3)"]

ENTRYPOINT ["/usr/local/bin/scalescore-container"]
CMD ["api"]
