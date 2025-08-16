# Minimal Python sandbox for untrusted code execution
FROM python:3.11-slim

# Install only essential packages
RUN pip install --no-cache-dir \
    numpy==1.24.3 \
    pandas==2.0.3

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash sandbox

# Set up working directory
WORKDIR /workspace

# Switch to non-root user
USER sandbox

# Set Python to unbuffered mode
ENV PYTHONUNBUFFERED=1

CMD ["python"]
