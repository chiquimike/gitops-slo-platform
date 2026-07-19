"""
incident-enricher — servicio de enriquecimiento de incidentes.

FASE 5C: añade la capa LLM (Gemini) sobre el baseline determinista.
El resumen final tiene DOS partes (Opción B — conviven):
  1. BASELINE determinista: hechos estructurados (siempre confiable).
  2. NARRATIVA LLM: síntesis legible de la correlación, ENCIMA de los hechos.

Frontera de responsabilidad (crítica): el CÓDIGO ya correlacionó de forma
determinista (tiene SLI, deploy, timestamps). El LLM SOLO narra esa correlación
ya calculada — el prompt lo restringe a no inventar causas, no afirmar causalidad
absoluta, y hablar de "sospechoso probable", no "causa confirmada".
Si Gemini falla, el ingeniero recibe igual el baseline determinista (degradación).
"""

import json
import logging
import os
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("incident-enricher")

app = FastAPI(title="incident-enricher", version="0.4.0")

# --- Configuración -----------------------------------------------------------
PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL", "http://prometheus.monitoring.svc.cluster.local:9090"
)
ARGOCD_URL = os.getenv("ARGOCD_URL", "https://argocd-server.argocd.svc.cluster.local")
ARGOCD_TOKEN = os.getenv("ARGOCD_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

SLI_QUERY = "sli:availability:ratio_5m"


@app.get("/healthz")
def healthz():
    return {"status": "healthy"}


async def query_prometheus_sli() -> float | None:
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
        if value != value:  # NaN
            logger.warning("SLI es NaN (sin tráfico en la ventana); no disponible")
            return None
        return value
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as e:
        logger.warning("No se pudo obtener el SLI de Prometheus: %s", e)
        return None


async def query_argocd_last_deploy() -> dict | None:
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


def build_context(alert: dict, sli_value: float | None, deploy: dict | None) -> dict:
    """Recolecta el contexto estructurado UNA vez. Ambas salidas (baseline y LLM)
    parten de este mismo dict — garantiza que EXP-005 compare sobre igual input."""
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    return {
        "alertname": labels.get("alertname", "?"),
        "severity": labels.get("severity", "?"),
        "status": alert.get("status", "unknown"),
        "summary": annotations.get("summary", ""),
        "description": annotations.get("description", ""),
        "duration": compute_duration(alert.get("startsAt", ""), alert.get("endsAt", "")),
        "sli": (f"{sli_value * 100:.1f}%" if sli_value is not None else "no disponible"),
        "deploy": (
            f"{deploy['app']} @ {deploy['revision']} (sync: {deploy['deployed_at']})"
            if deploy else "no disponible"
        ),
    }


def build_deterministic_summary(ctx: dict) -> str:
    """PARTE 1 — baseline determinista. Yuxtapone hechos. Siempre confiable."""
    return (
        f"────────── RESUMEN DE INCIDENTE (baseline determinista) ──────────\n"
        f"Alerta:        {ctx['alertname']}  [{ctx['severity'].upper()}]\n"
        f"Estado:        {ctx['status'].upper()}\n"
        f"Duración:      {ctx['duration']}\n"
        f"SLI actual:    disponibilidad (5m) = {ctx['sli']}\n"
        f"Último deploy: {ctx['deploy']}\n"
        f"Resumen:       {ctx['summary']}\n"
        f"Detalle:       {ctx['description']}\n"
        f"──────────────────────────────────────────────────────────────────"
    )


# El prompt restringido: codifica la FRONTERA de responsabilidad del LLM.
LLM_SYSTEM_INSTRUCTION = (
    "Eres un asistente de SRE que redacta un resumen breve de incidente para un "
    "ingeniero de guardia. Recibes DATOS YA VERIFICADOS por el sistema de "
    "monitoreo. Tu trabajo es SOLO comunicarlos en 2-3 frases claras y "
    "accionables en español. REGLAS ESTRICTAS: (1) No inventes causas ni datos "
    "que no estén en el contexto. (2) No afirmes causalidad absoluta; si el "
    "deploy coincide temporalmente con la degradación, di 'sospechoso probable a "
    "investigar', nunca 'causa confirmada'. (3) Si un dato es 'no disponible', "
    "dilo, no lo inventes. (4) No diagnostiques desde logs; no tienes logs. "
    "Solo narras la correlación de los datos estructurados dados."
)


async def generate_llm_narrative(ctx: dict) -> str | None:
    """PARTE 2 — narrativa del LLM (Gemini). None si falla (degradación con gracia:
    el ingeniero recibe igual el baseline determinista)."""
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY no configurada; se omite narrativa LLM")
        return None

    user_context = (
        f"Contexto del incidente (datos verificados):\n"
        f"- Alerta: {ctx['alertname']} (severidad {ctx['severity']}, estado {ctx['status']})\n"
        f"- Duración: {ctx['duration']}\n"
        f"- SLI de disponibilidad (5m): {ctx['sli']}\n"
        f"- Último deploy: {ctx['deploy']}\n"
        f"- Resumen de la alerta: {ctx['summary']}\n"
        f"Redacta el resumen para el ingeniero de guardia."
    )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    body = {
        "system_instruction": {"parts": [{"text": LLM_SYSTEM_INSTRUCTION}]},
        "contents": [{"parts": [{"text": user_context}]}],
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        # Extrae el texto de la respuesta de Gemini.
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("No se pudo generar la narrativa LLM: %s", e)
        return None


def build_combined_report(baseline: str, narrative: str | None) -> str:
    """Ensambla el reporte final: baseline (hechos) + narrativa LLM (encima)."""
    if narrative:
        llm_block = (
            f"\n╔══════════ NARRATIVA (LLM — Gemini) ══════════╗\n"
            f"{narrative}\n"
            f"╚══════════════════════════════════════════════╝"
        )
    else:
        llm_block = (
            "\n[Narrativa LLM no disponible — el baseline determinista de arriba "
            "contiene todos los hechos verificados.]"
        )
    return baseline + llm_block


@app.post("/alert")
async def receive_alert(request: Request):
    payload = await request.json()
    alerts = payload.get("alerts", [])
    logger.info("=== Webhook recibido: %d alerta(s) ===", len(alerts))

    sli_value = await query_prometheus_sli()
    deploy = await query_argocd_last_deploy()

    for alert in alerts:
        ctx = build_context(alert, sli_value, deploy)          # contexto único
        baseline = build_deterministic_summary(ctx)            # parte 1
        narrative = await generate_llm_narrative(ctx)          # parte 2
        report = build_combined_report(baseline, narrative)
        logger.info("\n%s", report)

    return {"received": len(alerts)}
