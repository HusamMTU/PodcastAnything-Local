FROM python:3.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --upgrade pip && \
    python -m pip install build && \
    python -m build


FROM python:3.13-slim AS runtime

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    DATA_DIR=/app/data \
    DATABASE_PATH=/app/data/app.db \
    JOBS_DIR=/app/data/jobs

WORKDIR /app

RUN useradd --create-home --home-dir /app --shell /usr/sbin/nologin app && \
    mkdir -p /app/data && \
    chown -R app:app /app

COPY --from=builder /build/dist /tmp/dist

RUN python -m pip install --upgrade pip && \
    python -m pip install /tmp/dist/*.whl && \
    rm -rf /tmp/dist

USER app

EXPOSE 8000

CMD ["uvicorn", "podcast_anything_local.main:app", "--host", "0.0.0.0", "--port", "8000"]
