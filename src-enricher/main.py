"""
incident-enricher — servicio de enriquecimiento de incidentes.

FASE 5B (2do incremento + fix NaN): recolecta contexto determinista de DOS
fuentes (Prometheus SLI + Argo CD último deploy) y arma el resumen. CERO LLM.
Fix 0.3.1: maneja el caso NaN del SLI (ventana sin tráfico -> 0/0).
"""

import json
import logging
import os
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("incident-enricher")

app = FastAPI(title="incident-enricher", version="0.3.1")

# --- Configuración (variables de entorno, con defaults al DNS interno) --------
PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL", "http://prometheus.monitoring.svc.cluster.local:9090"
)
ARGOCD_URL = os.getenv("ARGOCD_URL", "https://argocd-server.argocd.svc.cluster.local")
ARGOCD_TOKEN = os.getenv("ARGOCD_TOKEN", "")

SLI_QUERY = "sli:availability:ratio_5m"


@app.get("/healthz")
def healthz():
    return {"status": "healthy"}


async def query_prometheus_sli() -> float | None:
    """Consulta el SLI actual a Prometheus. Devuelve None si falla o si es NaN."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query", params={"query": SLI_QUERY}
            )
            resp.raise_for_status()
            data = resp.json()
        if data.get("status") != "success":
            return None
        result = data.get("data", {}).get("result", [])
        if not result:
            logger.warning("Prometheus devolvió resultado vacío para el SLI")
            return None
        value = float(result[0]["value"][1])
        # Prometheus devuelve NaN cuando el SLI se calcula sobre una ventana sin
        # tráfico (0/0). No es un fallo de la fuente, es "sin datos suficientes".
        # NaN es el único valor != a sí mismo (IEEE 754); así lo detectamos.
        if value != value:
            logger.warning("SLI es NaN (sin tráfico en la ventana); se marca no disponible")
            return None
        return value
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as e:
        logger.warning("No se pudo obtener el SLI de Prometheus: %s", e)
        return None


async def query_argocd_last_deploy() -> dict | None:
    """Consulta Argo CD por el deploy más reciente. None si falla (degradación)."""
    if not ARGOCD_TOKEN:
        logger.warning("ARGOCD_TOKEN no configurado; se omite contexto de deploy")
        return None
    try:
        headers = {"Authorization": f"Bearer {ARGOCD_TOKEN}"}
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
            resp = await client.get(f"{ARGOCD_URL}/api/v1/applications", headers=headers)
            resp.raise_for_status()
            data = resp.json()
        apps = data.get("items", []) or []
        latest = None
        for app_item in apps:
            name = app_item.get("metadata", {}).get("name", "?")
            sync = app_item.get("status", {}).get("sync", {})
            history = app_item.get("status", {}).get("history", []) or []
            revision = sync.get("revision", "")[:7]
            deployed_at = history[-1].get("deployedAt", "") if history else ""
            if deployed_at and (latest is None or deployed_at > latest["deployed_at"]):
                latest = {"app": name, "revision": revision, "deployed_at": deployed_at}
        return latest
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as e:
        logger.warning("No se pudo obtener el deploy de Argo CD: %s", e)
        return None


def compute_duration(starts_at: str, ends_at: str) -> str:
    """Duración del incidente por aritmética de timestamps (determinista)."""
    try:
        start = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        if ends_at and not ends_at.startswith("0001"):
            end = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
        else:
            end = datetime.now(timezone.utc)
        total_min = int((end - start).total_seconds() // 60)
        h, m = divmod(total_min, 60)
        return f"{h}h {m}m" if h else f"{m}m"
    except (ValueError, AttributeError):
        return "desconocida"


def build_deterministic_summary(
    alert: dict, sli_value: float | None, deploy: dict | None
) -> str:
    """Plantilla determinista. Yuxtapone datos estructurados de las 3 fuentes."""
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    status = alert.get("status", "unknown")
    alertname = labels.get("alertname", "?")
    severity = labels.get("severity", "?")
    summary = annotations.get("summary", "")
    description = annotations.get("description", "")
    duration = compute_duration(alert.get("startsAt", ""), alert.get("endsAt", ""))

    sli_line = f"{sli_value * 100:.1f}%" if sli_value is not None else "no disponible"
    if deploy:
        deploy_line = f"{deploy['app']} @ {deploy['revision']} (sync: {deploy['deployed_at']})"
    else:
        deploy_line = "no disponible"

    return (
        f"────────── RESUMEN DE INCIDENTE (baseline determinista) ──────────\n"
        f"Alerta:        {alertname}  [{severity.upper()}]\n"
        f"Estado:        {status.upper()}\n"
        f"Duración:      {duration}\n"
        f"SLI actual:    disponibilidad (5m) = {sli_line}\n"
        f"Último deploy: {deploy_line}\n"
        f"Resumen:       {summary}\n"
        f"Detalle:       {description}\n"
        f"──────────────────────────────────────────────────────────────────"
    )


@app.post("/alert")
async def receive_alert(request: Request):
    payload = await request.json()
    alerts = payload.get("alerts", [])
    logger.info("=== Webhook recibido: %d alerta(s) ===", len(alerts))
    sli_value = await query_prometheus_sli()
    deploy = await query_argocd_last_deploy()
    for alert in alerts:
        logger.info("\n%s", build_deterministic_summary(alert, sli_value, deploy))
    return {"received": len(alerts)}
