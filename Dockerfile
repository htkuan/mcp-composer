FROM ghcr.io/astral-sh/uv:python3.12-alpine

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apk add --no-cache \
    nodejs \
    npm \
    docker-cli

COPY pyproject.toml .
COPY uv.lock .

RUN uv venv && uv sync

EXPOSE 8000

CMD ["uv", "run", "src/main.py"]
