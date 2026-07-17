"""
incident-enricher — servicio de enriquecimiento de incidentes.

FASE 5B (esta versión): RECOLECCIÓN DETERMINISTA DE CONTEXTO + PLANTILLA.
Cuando llega una alerta, el enricher:
  1. Extrae los datos estructurados del webhook (alertname, severity, tiempos).
  2. Calcula la duración del incidente de forma determinista (aritmética de fechas).
  3. Consulta la API de Prometheus por el SLI actual (lectura programática).
  4. Arma un resumen con una PLANTILLA DETERMINISTA. CERO LLM.

Este resumen es el BASELINE. En 5C, un LLM tomará este mismo contexto ya
recolectado y lo narrará; EXP-005 comparará ambos. Por eso el baseline debe ser
genuinamente bueno: la comparación solo es honesta si el determinista es fuerte.

El enricher es un servicio SEPARADO del demo-app (plataforma que observa, no app
observada).
"""

import json
import logging
import os
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("incident-enricher")

app = FastAPI(title="incident-enricher", version="0.2.0")

# URL de la API de Prometheus. Configurable por variable de entorno (buena
# práctica: no hardcodear), con default al DNS interno de Kubernetes.
PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL",
    "http://prometheus.monitoring.svc.cluster.local:9090",
)

# La recording rule del SLI que ya definimos en Fase 4.
SLI_QUERY = "sli:availability:ratio_5m"


@app.get("/healthz")
def healthz():
    return {"status": "healthy"}


async def query_prometheus_sli() -> float | None:
    """
    Consulta la API de Prometheus por el valor actual del SLI.
    Devuelve el SLI como float (0.0-1.0), o None si no se pudo obtener.

    DEGRADACIÓN CON GRACIA: si Prometheus no responde, el enricher NO se cae —
    devuelve None y el resumen indicará "SLI no disponible". El enriquecimiento
    es best-effort: una fuente de contexto caída no debe tumbar el enricher.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": SLI_QUERY},
            )
            resp.raise_for_status()
            data = resp.json()

        # Estructura de respuesta de Prometheus para una query instantánea:
        # data.data.result[0].value = [timestamp, "valor_como_string"]
        if data.get("status") != "success":
            logger.warning("Prometheus respondió status != success")
            return None

        result = data.get("data", {}).get("result", [])
        if not result:
            logger.warning("Prometheus devolvió resultado vacío para el SLI")
            return None

        # El valor viene como string en la segunda posición del par.
        value_str = result[0]["value"][1]
        return float(value_str)

    except (httpx.HTTPError, KeyError, ValueError, IndexError) as e:
        logger.warning("No se pudo obtener el SLI de Prometheus: %s", e)
        return None


def compute_duration(starts_at: str, ends_at: str) -> str:
    """
    Calcula la duración del incidente de forma DETERMINISTA (aritmética de fechas).
    Alertmanager envía tiempos ISO 8601. Si la alerta sigue activa (firing), el
    endsAt suele ser una fecha "cero" (0001-01-01), así que en ese caso medimos
    hasta ahora.
    """
    try:
        start = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        # Alertmanager usa año 0001 como "sin fin" para alertas activas.
        if ends_at and not ends_at.startswith("0001"):
            end = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
        else:
            end = datetime.now(timezone.utc)

        delta = end - start
        total_min = int(delta.total_seconds() // 60)
        h, m = divmod(total_min, 60)
        return f"{h}h {m}m" if h else f"{m}m"
    except (ValueError, AttributeError):
        return "desconocida"


def build_deterministic_summary(alert: dict, sli_value: float | None) -> str:
    """
    Arma el resumen del incidente con una PLANTILLA DETERMINISTA.
    Yuxtapone datos estructurados — NO narra ni correlaciona en lenguaje natural.
    Esa síntesis narrativa es justo lo que el LLM añadirá en 5C; aquí es el baseline.
    """
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    status = alert.get("status", "unknown")

    alertname = labels.get("alertname", "?")
    severity = labels.get("severity", "?")
    summary = annotations.get("summary", "")
    description = annotations.get("description", "")
    duration = compute_duration(alert.get("startsAt", ""), alert.get("endsAt", ""))

    sli_line = (
        f"{sli_value * 100:.1f}%" if sli_value is not None else "no disponible"
    )

    # La plantilla: estructurada, clara, funcional. Es lo mejor que un template
    # determinista puede dar — el baseline honesto contra el que medir el LLM.
    return (
        f"────────── RESUMEN DE INCIDENTE (baseline determinista) ──────────\n"
        f"Alerta:        {alertname}  [{severity.upper()}]\n"
        f"Estado:        {status.upper()}\n"
        f"Duración:      {duration}\n"
        f"SLI actual:    disponibilidad (5m) = {sli_line}\n"
        f"Resumen:       {summary}\n"
        f"Detalle:       {description}\n"
        f"──────────────────────────────────────────────────────────────────"
    )


@app.post("/alert")
async def receive_alert(request: Request):
    """
    Recibe el webhook de Alertmanager, recolecta contexto determinista, y arma
    el resumen baseline para cada alerta del grupo.
    """
    payload = await request.json()
    alerts = payload.get("alerts", [])
    logger.info("=== Webhook recibido: %d alerta(s) ===", len(alerts))

    # Consultamos el SLI una vez (es el estado global del servicio, no por-alerta).
    sli_value = await query_prometheus_sli()

    summaries = []
    for alert in alerts:
        summary_text = build_deterministic_summary(alert, sli_value)
        summaries.append(summary_text)
        logger.info("\n%s", summary_text)

    return {"received": len(alerts), "enriched": len(summaries)}
