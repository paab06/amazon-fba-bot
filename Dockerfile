# Dockerfile
FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar archivos del proyecto
COPY pyproject.toml pyproject.toml
COPY src/ src/
COPY start_dual_flow.py start_dual_flow.py

# Instalar dependencias Python
RUN pip install --no-cache-dir -e .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Comando por defecto
CMD ["python", "start_dual_flow.py"]
