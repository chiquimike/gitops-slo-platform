"""
demo-app — FastAPI instrumentada para la GitOps SLO Platform.

Objetivo de esta app:
  1. Exponer métricas en formato Prometheus en /metrics.
  2. Generar SLIs reales (tasa de éxito y latencia) desde tráfico real.
  3. Permitir inyectar fallas controladas (chaos) para los experimentos.

La instrumentación es MANUAL (prometheus-client) a propósito: para entender
exactamente qué se mide y de qué métrica sale cada SLI.
"""

import time
import random

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

app = FastAPI(title="demo-app", version="0.1.0")


# ─────────────────────────────────────────────────────────────────────────────
# MÉTRICAS — los tres tipos base. Entender cuál usar para qué ES la lección.
# ─────────────────────────────────────────────────────────────────────────────

# COUNTER: valor que SOLO sube (nunca baja). Para "cuántas veces pasó X".
# De aquí sale el SLI DE DISPONIBILIDAD: éxito = (total - errores) / total.
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total de requests HTTP procesados",
    ["method", "endpoint", "status_code"],
)

# HISTOGRAM: distribución de valores en buckets. Para medir "cuánto tardó X".
# De aquí sale el SLI DE LATENCIA: percentiles como p99 se calculan del histograma.
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Duración de los requests HTTP, en segundos",
    ["method", "endpoint"],
)

# GAUGE: valor instantáneo que SUBE y BAJA. Para "cuántos X hay AHORA MISMO".
REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Requests actualmente en vuelo",
    ["method", "endpoint"],
)


# ─────────────────────────────────────────────────────────────────────────────
# ESTADO DE CAOS INYECTABLE — se controla en runtime vía /chaos, sin redeploy.
# NOTA (limitación conocida): este estado vive EN MEMORIA, por proceso. Con
# varias réplicas, un POST /chaos solo afecta al pod que lo recibió. Se aborda
# en la fase de experimentos (p. ej. escalar a 1 réplica durante el chaos).
# ─────────────────────────────────────────────────────────────────────────────
chaos_state = {"fail_rate": 0.0, "latency_ms": 0}


# ─────────────────────────────────────────────────────────────────────────────
# MIDDLEWARE — instrumenta TODOS los requests automáticamente, en un solo lugar.
# Alternativa a decorar cada endpoint a mano: el middleware envuelve todo.
# ─────────────────────────────────────────────────────────────────────────────
@app.middleware("http")
async def instrument_requests(request: Request, call_next):
    method = request.method
    endpoint = request.url.path

    REQUESTS_IN_PROGRESS.labels(method, endpoint).inc()
    start = time.perf_counter()
    status_code = 500  # por defecto; se sobreescribe si el request completa
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(method, endpoint).observe(elapsed)
        REQUEST_COUNT.labels(method, endpoint, str(status_code)).inc()
        REQUESTS_IN_PROGRESS.labels(method, endpoint).dec()


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS DE NEGOCIO — su éxito y latencia SON el SLI que mediremos.
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"service": "demo-app", "status": "ok"}


@app.get("/api/work")
def do_work():
    """
    Endpoint 'de negocio'. Aplica el caos configurado:
      - latency_ms: añade retraso artificial (degrada el SLI de latencia).
      - fail_rate:  probabilidad de devolver 500 (degrada el SLI de éxito).
    """
    if chaos_state["latency_ms"] > 0:
        time.sleep(chaos_state["latency_ms"] / 1000.0)

    if random.random() < chaos_state["fail_rate"]:
        return Response(
            content='{"error": "chaos-induced failure"}',
            status_code=500,
            media_type="application/json",
        )

    return {"result": "work done"}


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS OPERATIVOS
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    """Liveness probe. Responde 200 si el proceso está vivo."""
    return {"status": "healthy"}


@app.get("/metrics")
def metrics():
    """Expone las métricas en el formato que Prometheus scrapea."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/chaos")
def set_chaos(fail_rate: float = 0.0, latency_ms: int = 0):
    """
    Configura el caos en runtime. Ejemplos:
      POST /chaos?fail_rate=0.3          -> 30% de /api/work devuelve 500
      POST /chaos?latency_ms=500         -> +500ms de latencia
      POST /chaos?fail_rate=0&latency_ms=0 -> apaga el caos
    """
    chaos_state["fail_rate"] = max(0.0, min(1.0, fail_rate))
    chaos_state["latency_ms"] = max(0, latency_ms)
    return {"chaos": chaos_state}


@app.get("/chaos")
def get_chaos():
    """Consulta el estado actual del caos."""
    return {"chaos": chaos_state}
