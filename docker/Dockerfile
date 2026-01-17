# sandbox/docker/Dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and schemas into container under /app/sandbox
# so imports like `from sandbox.app...` continue to work
COPY app/ ./sandbox/app/
COPY schemas/ ./sandbox/schemas/

# Create data directories
RUN mkdir -p sandbox/data/uploads sandbox/data/repos sandbox/data/projects

# Set Python path
ENV PYTHONPATH=/app

# Default environment variables
ENV SANDBOX_ENVIRONMENT=production
ENV SANDBOX_LOG_LEVEL=INFO
ENV SANDBOX_LOG_JSON=true
ENV SANDBOX_POSTGRES_DSN=postgresql+psycopg://sandbox:sandbox@postgres:5432/sandbox

# Expose port (if adding API later)
EXPOSE 8080

# Run as non-root user
RUN useradd -m -u 1000 sandbox && chown -R sandbox:sandbox /app
USER sandbox

# Default command (can be overridden)
CMD ["python", "-c", "from sandbox.app.main import startup; startup(); print('Sandbox tool ready')"]
