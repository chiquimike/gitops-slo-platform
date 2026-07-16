"""
incident-enricher — servicio de enriquecimiento de incidentes.

FASE 5A (esta versión): webhook receiver MÍNIMO.
Su único trabajo por ahora es recibir el POST de Alertmanager cuando una alerta
dispara, y registrar en el log lo que llega. Nada de consultar Prometheus/Argo,
nada de LLM todavía. Primero validamos el TRANSPORTE; la lógica viene en 5B/5C.

Es un servicio SEPARADO del demo-app: el demo-app es la aplicación OBSERVADA;
este es parte de la plataforma que OBSERVA. Responsabilidades distintas.
"""

import json
import logging

from fastapi import FastAPI, Request

# Logging a stdout para que Kubernetes capture los logs (kubectl logs).
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("incident-enricher")

app = FastAPI(title="incident-enricher", version="0.1.0")


@app.get("/healthz")
def healthz():
    """Liveness probe."""
    return {"status": "healthy"}


@app.post("/alert")
async def receive_alert(request: Request):
    """
    Recibe el webhook de Alertmanager. El payload es JSON con una estructura
    definida por Alertmanager (grupo de alertas + labels + annotations).
    Por ahora solo lo registramos para VER que el transporte funciona.
    """
    payload = await request.json()

    # Alertmanager envía un objeto con 'alerts': lista de alertas del grupo.
    alerts = payload.get("alerts", [])
    logger.info("=== Webhook recibido de Alertmanager: %d alerta(s) ===", len(alerts))

    for alert in alerts:
        status = alert.get("status", "unknown")
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alertname = labels.get("alertname", "?")
        severity = labels.get("severity", "?")
        summary = annotations.get("summary", "")

        logger.info(
            "  [%s] %s (severity=%s) — %s",
            status.upper(), alertname, severity, summary,
        )

    # Log del payload completo para inspección durante el desarrollo de 5A.
    logger.info("Payload completo:\n%s", json.dumps(payload, indent=2))

    # Alertmanager espera un 200 para considerar la entrega exitosa.
    return {"received": len(alerts)}
