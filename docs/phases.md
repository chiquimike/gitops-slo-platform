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

## Fase 3 — Observabilidad _(completada)_

**Objetivo:** desplegar Prometheus y Grafana vía Argo CD, con Prometheus
scrapeando la app y un dashboard que muestre el SLI real.
**Estado:** completa (3A Prometheus + 3B Grafana).

### 3A — Prometheus con service discovery
- Prometheus desplegado a mano (Deployment + ConfigMap + RBAC + Service) en
  namespace propio `monitoring`, vía Argo CD. Se optó por manifiestos propios
  sobre Helm chart para entender cada pieza (observabilidad es brecha declarada).
- RBAC con least privilege: ClusterRole (necesita descubrir targets
  across-namespace) pero SOLO verbos de lectura (get, list, watch). Un sistema
  de observabilidad solo observa; su blast radius se limita a lectura.
- Modelo pull: Prometheus scrapea el /metrics de sus targets. Ventaja: la
  disponibilidad del target es intrínseca (scrape falla = servicio caído).
- Service discovery + relabeling: descubre todos los endpoints del clúster y los
  filtra en cascada (namespace -> service -> puerto) con action keep, hasta
  exactamente la FastAPI. Sin keep, se scrapearía todo el clúster (fallos
  masivos, desperdicio, contaminación de datos).
- Validado: target demo-app 3/3 UP, verificado en tres capas (UI targets,
  series en Graph, cruce contra kubectl get endpoints). emptyDir para storage:
  limitación consciente (métricas no persisten reinicio; en prod, PersistentVolume).

### Incidente resuelto durante 3A
- Detectado `argocd-applicationset-controller` en CrashLoopBackOff (139 reinicios)
  mientras se revisaba el clúster. Causa raíz (vía logs --previous): CRD de
  ApplicationSet ausente ("if kind is a CRD, it should be installed before
  calling Start") — gotcha de orden de instalación de CRDs.
- Decisión: desactivar el controller (replicas=0) por no usarse ApplicationSets,
  aplicando minimización de superficie operativa. Reversibilidad verificada en
  ambos sentidos. Documentado en ADR-006.
- Lección: sesgo de confirmación. Un componente sano junto a uno en CrashLoop
  sigue siendo un sistema degradado. Escanear TODO el estado, no solo lo buscado.

### 3B — Grafana con provisioning declarativo
- Grafana desplegada vía Argo CD. Data source (Prometheus) y dashboard
  provisionados declarativamente desde ConfigMaps, NO por la UI (click-ops).
- Contraseña de admin en un Secret creado imperativamente (fuera de Git); el
  Deployment solo lo referencia. Nota: Secrets de K8s son base64, no cifrado;
  en GitOps puro se usaría Sealed Secrets / SOPS / External Secrets.
- DNS interno de Kubernetes: Grafana alcanza Prometheus como http://prometheus:9090
  (mismo namespace). Los consumidores usan nombres estables, no IPs.
- fsGroup 472 para permisos de volumen (Grafana corre no-root; emptyDir nace
  root-owned). Cuidado con solapamiento de montajes (storage movido a subruta
  para no tapar la carpeta de dashboards).
- Primer panel PromQL construido a mano: rate(http_requests_total{endpoint="/api/work"}[5m]).
  Aprendizaje: nunca graficar un Counter crudo; rate() lo convierte en req/s. La
  ventana ([5m]) debe ser >= ~4x el scrape_interval (15s) para tener suficientes
  puntos; [10s] rompería el cálculo.
- Experimento asociado: EXP-003 (dashboard sobrevive a la destrucción del pod
  porque viene de ConfigMaps versionados — reproducibilidad probada con chaos).

---

## Fase 4 — SLO + Burn-rate Alerting _(completada)_

**Objetivo:** definir un SLO formal con error budget y alertar sobre el consumo
del presupuesto (burn-rate), no sobre umbrales de infraestructura.
**Estado:** completa. El corazón SRE del proyecto.

### Definición del SLI y el SLO
- SLI de disponibilidad definido como proporción de eventos buenos sobre totales:
  requests exitosos (200) a /api/work / requests totales a /api/work. Mide la
  EXPERIENCIA DEL USUARIO, no la salud de la infraestructura (un pod "healthy"
  puede devolver 500s; el SLI mide lo que el usuario siente).
- SLO elegido: 99% de disponibilidad sobre ventana de 30 días. Decisión razonada
  como objetivo iterativo (empezar conservador, ajustar con datos). El 99%
  permite ~7.2h de caída/mes, margen holgado para experimentar; cada nueve
  adicional reduce el margen 10x y multiplica el costo.
- Error budget = 1%. Concepto clave: el budget se consume con FALLOS, no con
  tráfico exitoso. El margen no usado es "licencia para arriesgar" (deploys,
  chaos); cuando se agota, se congela el cambio y se estabiliza.

### Recording rules (SLI precalculado)
- El SLI se encapsuló en recording rules (convención nivel:métrica:operación,
  ej. sli:availability:ratio_5m) en 4 ventanas (5m, 1h, 30m, 6h). Ventajas:
  legibilidad (nombre corto vs. query larga) y rendimiento (precálculo por
  intervalo). Las ventanas cortas alimentan la alerta Page; las largas, la Ticket.
- PromQL: uso de rate() en numerador y denominador para que las unidades se
  cancelen y quede una proporción 0-1; sum() para agregar los 3 pods en un SLI
  de servicio único. Nunca graficar un Counter crudo.

### Burn-rate alerting multi-ventana (SRE Workbook de Google)
- Dos alertas por severidad:
  - SLOBurnRateHigh (page): burn rate 14.4x, ventanas 5m Y 1h, for 2m. Agota el
    budget mensual en ~2 días. Detección rápida de quema violenta.
  - SLOBurnRateSlow (ticket): burn rate 3x, ventanas 30m Y 6h, for 15m. Agota el
    budget en ~10 días. Fuga lenta que solo emerge del ruido en ventanas largas.
- Diseño anti-ruido: cada alerta exige que AMBAS ventanas superen el umbral. Un
  pico efímero mueve la ventana corta pero no la larga -> no dispara. El campo
  `for` añade confirmación temporal (Pending -> Firing) contra parpadeos.

### Gotchas y aprendizajes de la fase
- Falso positivo del editor: el ConfigMap con reglas de Prometheus marca error de
  schema en VS Code (aplica schema de reglas puras a un ConfigMap). Estructura
  válida; Prometheus carga las reglas (verificado en Status > Rules).
- Prometheus NO recarga reglas automáticamente al cambiar el ConfigMap: las lee
  al arrancar. Fix elegido: recrear el pod (vs. /-/reload o config-reloader
  sidecar, que el kube-prometheus-stack abstrae). Elección razonada por alcance.
- Port-forward muere al recrear el pod: primer uso en vivo del runbook de
  diagnóstico en capas (docs/runbooks/).

### Experimento asociado
- EXP-004 (evidencia estrella): chaos al 50% -> SLI degradado -> burn rate 14.4x
  superado -> SLOBurnRateHigh en FIRING (Value 0.486). Ambas alertas (Page y
  Ticket) activas. Toda la cadena SRE validada de punta a punta.

### Limitación consciente
- Las alertas disparan en Prometheus pero NO se enrutan a un destino (Slack,
  email): eso es trabajo de Alertmanager, no desplegado (decisión de alcance).
  Ver el estado Firing en la UI demuestra el mecanismo de burn-rate.

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
