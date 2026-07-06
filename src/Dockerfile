# ─────────────────────────────────────────────────────────────────────────────
# Imagen base: python-slim. Balance entre tamaño (~150MB) y compatibilidad.
# Se pinea la versión exacta (no ':latest') por reproducibilidad, mismo
# principio que aplicamos con la imagen de whoami en Fase 1.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Buenas prácticas de entorno para Python en contenedor:
#   PYTHONDONTWRITEBYTECODE: no genera .pyc (innecesarios en contenedor)
#   PYTHONUNBUFFERED: logs salen en tiempo real, no se quedan en buffer
#     (crítico para que Kubernetes capture los logs de inmediato)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ─────────────────────────────────────────────────────────────────────────────
# ORDEN DE CAPAS PARA CACHE (decisión deliberada):
# Copiamos SOLO requirements.txt primero e instalamos. Así, mientras no cambien
# las dependencias, Docker reutiliza esta capa cacheada aunque cambie el código.
# Si copiáramos todo el código antes, cada cambio de código reinstalaría todo.
# ─────────────────────────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ahora sí, el código. Cambios aquí NO invalidan la capa de pip install de arriba.
COPY main.py .

# ─────────────────────────────────────────────────────────────────────────────
# USUARIO NO-ROOT (seguridad):
# Por defecto un contenedor corre como root. Creamos un usuario sin privilegios
# y cambiamos a él. Si la app se compromete, el atacante no tiene root.
# ─────────────────────────────────────────────────────────────────────────────
RUN useradd --create-home --uid 1000 appuser
USER appuser

# Documenta el puerto que la app expone (informativo; no publica el puerto).
EXPOSE 8000

# Comando de arranque. Nota: SIN --reload (eso es solo para desarrollo local).
# host 0.0.0.0 para que sea accesible desde fuera del contenedor.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
