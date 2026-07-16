# Mismo patrón que el Dockerfile del demo-app: slim, cache de capas, no-root.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Crear el usuario no-root ANTES de copiar, para poder asignarle propiedad.
RUN useradd --create-home --uid 1000 appuser

# Cache de capas: dependencias antes que el código.
# --chown=appuser: los archivos quedan propiedad del usuario no-root, para que
# pueda LEERLOS cuando la app corre como appuser (evita PermissionError).
COPY --chown=appuser:appuser requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser main.py .

# Cambiar al usuario no-root (seguridad) DESPUÉS de tener todo en su sitio.
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
