# VESTING DAY - runs the agent on 0.0.0.0:8000. No runtime installs: everything is
# resolved at build time from uv.lock. Works with no .env (SAMPLE_MODE fallback).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1 PORT=8000
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
RUN uv sync --frozen --no-dev --no-group prep

COPY run.py metadata.json .env.example ./
COPY data ./data
COPY input_examples ./input_examples
COPY output_examples ./output_examples
COPY logs ./logs
COPY third_party ./third_party

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "python", "run.py"]
