# We use a multi-stage build: one stage to sync dependencies with uv, and the runtime stage to run the app.

# --- Stage 1: Build & Sync ---
FROM ghcr.io/astral-sh/uv:0.6.3-python3.14-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first (for layer caching)
COPY uv.lock pyproject.toml ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy project source and install the project itself
COPY . .
RUN uv sync --frozen --no-dev


# --- Stage 2: Runtime ---
FROM cgr.dev/chainguard/python:latest

WORKDIR /app

# Copy the environment and app code from the build stage
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/ /app/

# Place the virtual environment's bin folder at the front of the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Set non-interactive matplotlib backend explicitly
ENV MPLBACKEND="Agg"

# Note: cgr.dev/chainguard/python has python available at /usr/bin/python
# We run the discord bot entrypoint
ENTRYPOINT ["python", "main.py"]
