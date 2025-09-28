# Use Python 3.12 slim image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies including build tools for cardano-python-signing-module
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    build-essential \
    swig \
    && rm -rf /var/lib/apt/lists/*

# Install Rust (required for cardano-python-signing-module)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install uv (Python package manager)
RUN pip install uv

# Copy dependency files
COPY pyproject.toml ./

# Create virtual environment and install dependencies
RUN uv venv .venv
RUN uv pip install -e . --group dev

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Expose port (Cloud Run will set PORT environment variable)
EXPOSE 8080

# Health check endpoint (test HTTP server for Cloud Run)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Use Cloud Run optimized entry point that starts health server immediately
CMD ["uv", "run", "python", "cloud_run_main.py"]
