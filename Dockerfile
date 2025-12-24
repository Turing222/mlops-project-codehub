

# Base Image: Lightweight Python
FROM python:3.11-slim

# Working Directory
WORKDIR /app

# Install system dependencies (curl is often needed for healthchecks/debugging)
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install uv (The package manager you chose)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency definition
COPY pyproject.toml .

# Install dependencies
# --system flag installs into the system python, avoiding venv creation inside docker
RUN uv pip install --system -r pyproject.toml

# Copy the rest of the code
COPY . .

# Expose the port
EXPOSE 8000