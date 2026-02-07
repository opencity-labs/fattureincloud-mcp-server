# FattureInCloud MCP Server
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY server.py .
COPY src/ ./src/

# Default command
CMD ["python", "server.py"]
