FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_LINK_MODE=copy
ENV PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml uv.lock README.md /app/
RUN uv sync --frozen --no-dev

COPY streamlit_app/ /app/streamlit_app/
COPY eval/ /app/eval/
COPY data/ /app/data/
COPY results/ /app/results/
COPY docs/ /app/docs/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app
ENV PORT=8080

EXPOSE 8080

CMD ["streamlit", "run", "/app/streamlit_app/app.py", \
     "--server.port=8080", \
     "--server.address=0.0.0.0", \
     "--server.enableXsrfProtection=true"]
