FROM ghcr.io/astral-sh/uv:0.12.13@sha256:b485bd65cc2cf1c9a93b3554012c9c3778cf7b1b5fd3d3096ce9e1226c97e1e6 AS uv
FROM python:3.12-slim-bookworm

COPY --from=uv /uv /uvx /bin/

WORKDIR /app
ENV UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock /app/
RUN uv sync --locked --no-dev --no-install-project

RUN groupadd --gid 10001 healtheval \
    && useradd --uid 10001 --gid 10001 --create-home --no-log-init healtheval \
    && mkdir /app/var \
    && chown healtheval:healtheval /app/var

COPY streamlit_app/ /app/streamlit_app/
COPY eval/ /app/eval/
COPY data/ /app/data/
COPY results/ /app/results/
COPY docs/ /app/docs/
COPY scripts/container_entrypoint.py scripts/container_healthcheck.py /app/scripts/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PORT=8080 \
    HEALTHEVAL_STATE_DIR=/app/var \
    XDG_CACHE_HOME=/tmp/cache \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true

USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "/app/scripts/container_healthcheck.py"]
ENTRYPOINT ["python", "/app/scripts/container_entrypoint.py"]
