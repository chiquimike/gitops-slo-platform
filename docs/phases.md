# Bitácora de progreso por fase

Registro cronológico de la construcción del proyecto. Documenta qué se hizo en
cada fase, qué se aprendió y qué muros se cruzaron. El valor está tanto en los
logros como en los errores resueltos: en entrevista, el que sepa explicar un fallo que
depuré vale más que un flujo que salió a la primera.

---

## Fase 1 — Sustrato GitOps _(completada)_

**Objetivo:** que un `git push` modifique el clúster sin tocar `kubectl`.
**Estado:** funcionalmente completa; cierre formal pendiente de documentación.

### Qué se construyó
- Clúster local k3d `slo-platform`.
- Argo CD instalado y accesible por la UI.
- `Application` CR apuntando al repo, con `prune` y `selfHeal` activos.
- Workload de demo desplegado 100% vía Argo CD (sin `kubectl apply` manual del
  workload).

### Muros cruzados (lo que se aprendió por las malas)
1. **Application en estado `Unknown`.** No era `OutOfSync`: era que Argo no podía
   leer/interpretar el repo. Diagnóstico con `kubectl describe application` →
   `ComparisonError: app path does not exist`.
2. **Causa raíz:** los manifiestos estaban en GitHub pero no en la ruta que el
   Application declaraba (`apps/demo-app`). Faltaba la estructura anidada de
   carpetas. Verificado con `git ls-files`.
3. **Lección de método:** síntoma → condición → causa raíz → verificación contra
   el source of truth. El fix fue en Git, nunca en el clúster.
4. **`commit` ≠ `push`.** Recordatorio grabado: Argo lee del remoto, no del
   working directory. Lo que no se empuja, no existe para Argo.
5. **Namespace `demo` creado por Argo, no a mano** (`CreateNamespace=true`).
   Confirmación visual de lo declarativo: apareció solo con edad distinta al
   resto de namespaces.

### Experimento asociado
- **EXP-001** (ver [`experiments.md`](../experiments.md)): self-heal de drift de
  réplicas. Tiempo medido y explicado en función del ciclo de reconciliación de
  Argo CD.

### Decisiones registradas
- ADR-001 (k3d vs kind), ADR-002 (bootstrap paradox), ADR-003 (prune+selfHeal),
  ADR-004 (semilla app-of-apps). Ver [`decisions.md`](decisions.md).

### Pendientes para cerrar la fase
- [X] Rellenar EXP-001 con el número medido y su interpretación.
- [X] Versionar capturas en `evidence/`.
- [X] `git add` / `commit` / `push`.
- [X] (Opcional) Correr self-heal 2-3 veces y reportar rango.

---

## Fase 2 — FastAPI instrumentada  _(completada)_

**Objetivo:** app real con endpoint `/metrics` (formato Prometheus) y un
endpoint de falla inyectable para chaos posterior.
**Estado:** en construcción (2A y 2B completos; 2C en curso).

### 2A — App instrumentada corriendo local
- FastAPI con instrumentación MANUAL vía prometheus-client (decisión deliberada
  sobre usar un instrumentator automático, para entender de qué métrica sale
  cada SLI). Tres tipos de métrica: Counter (disponibilidad), Histogram
  (latencia), Gauge (requests en vuelo).
- Endpoint `/chaos` para inyectar fallas (fail_rate) y latencia (latency_ms) en
  runtime, sin redeploy. Limitación conocida: estado en memoria por proceso, no
  se propaga entre réplicas.
- Validado local con uvicorn: `/metrics` poblándose con tráfico real.
- Experimento asociado: EXP-002 (degradación de SLI vía chaos, SLI observado 75%).

### 2B — Dockerización
- Dockerfile de nivel productivo con tres decisiones defendibles:
  - Imagen base `python:3.12-slim` (balance tamaño/compatibilidad; se descartó
    Alpine por incompatibilidad de musl con wheels precompiladas).
  - Orden de capas para cache: copiar requirements e instalar ANTES de copiar
    el código, para que un cambio de código no reinstale dependencias.
  - Usuario no-root (`appuser`) por seguridad; verificado con
    `docker exec ... whoami` -> appuser.
- Imagen resultante: ~231 MB en disco. Línea base para futuras optimizaciones
  (p. ej. multi-stage build).
- Añadido `.dockerignore` para excluir venv y basura del contexto de build.
- Validado: `/metrics` responde igual desde el contenedor que desde local.

### 2C — Despliegue en k3d vía Argo CD 
- Manifiestos actualizados: imagen `demo-app:0.1.0`, puerto 8000,
  `imagePullPolicy: IfNotPresent`.
- Aprendizaje central: la frontera GitOps vs CI/CD. GitOps despliega lo
  declarado en Git; construir y publicar la imagen es responsabilidad de CI/CD.
  Localmente se simula con `k3d image import` (reemplaza el push a un registry).

---

## Fase 3 — Observabilidad  _(no iniciada)_

**Objetivo:** Prometheus + Grafana desplegados vía Argo CD; un dashboard con el
SLI real.

> **Definición de "done" de esta fase (recordatorio):** NO es que Grafana
> muestre gráficas. Es que exista un SLI real medido y visible. El bloque
> central no está terminado hasta que una alerta de burn-rate dispara sola con
> una falla inyectada (Fase 4).

_Se completará al arrancar la fase._

---

## Fase 4 — SLO + burn-rate alerting  _(no iniciada)_

**Objetivo:** SLO formal definido, alertas basadas en consumo de error budget.
El corazón del proyecto.

_Se completará al arrancar la fase._

---

## Fase 5 — Experimentos y evidencia  _(no iniciada)_

**Objetivo:** correr carga (k6/vegeta) + chaos, medir antes/después, capturar
evidencia para los números del CV.

_Se completará al arrancar la fase._

---

## Fase 6 — Terraform + GCS  _(opcional, no iniciada)_

**Objetivo:** provisionar bucket GCS con Terraform, backend remoto de state,
backup de snapshots.

_Se completará al arrancar la fase._

---

## Fase 7 — Capa de IA / enriquecimiento de incidentes  _(opcional, no iniciada)_

**Objetivo:** servicio que genera borradores de narrativa de incidente a partir
de telemetría estructurada + historial de deploys. Solo tras validar que la
correlación de alertas se resuelve de forma determinista.

_Se completará al arrancar la fase._
