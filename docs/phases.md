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

## Fase 5 — AIOps / Incident Enrichment

> **Nota de roadmap:** El plan original contemplaba 7 fases. Tras completar el
> núcleo (Fases 1-4), se reevaluó el roadmap: los objetivos de la antigua Fase 5
> (validación bajo estrés) ya se cumplieron de forma distribuida en EXP-002 y
> EXP-004. Se priorizó la capa de AIOps sobre la de Terraform/GCS (ahora Fase 6,
> planificada) por su mayor valor diferenciador. Un roadmap es una hipótesis que
> se ajusta con evidencia, no un contrato inmutable.

**Objetivo:** enriquecer incidentes de forma responsable — un baseline
determinista primero, y un LLM que narra sobre datos ya verificados después,
midiendo si el LLM se justifica sobre el baseline.
**Estado:** en construcción (5A completo).

### Decisión de diseño: por qué un LLM aquí (y dónde NO)
- El enriquecimiento se resuelve ~70% con una plantilla determinista. El LLM se
  incluye por el 30% restante: sintetizar la correlación de señales en narrativa
  accionable. Distinción clave: el CÓDIGO correlaciona de forma determinista
  (aritmética de timestamps); el LLM solo COMUNICA esa correlación en lenguaje
  natural. Si se quita el LLM, el sistema sigue sabiendo qué deploy coincide con
  la caída — solo pierde la narrativa legible.
- El LLM nunca decide, diagnostica de logs crudos, ni afirma causalidad absoluta.
  Parte de hechos pre-verificados por el clúster y sugiere el sospechoso probable.

### 5A — Infraestructura de trigger (Alertmanager + webhook receiver)
- Desplegado **Alertmanager** (la pieza que se dejó pendiente conscientemente en
  Fase 4) vía Argo CD, con un receptor tipo webhook.
- Construido el **incident-enricher**: servicio FastAPI SEPARADO del demo-app
  (el demo-app es la app observada; el enricher es parte de la plataforma que
  observa — responsabilidades distintas). Por ahora solo recibe y loguea.
- Conectado Prometheus -> Alertmanager (bloque `alerting:` en la config) y
  Alertmanager -> enricher (webhook vía DNS interno de Kubernetes).
- Gotcha resuelto: el Dockerfile copiaba archivos como root y luego cambiaba a
  usuario no-root, causando PermissionError al leer main.py. Fix: `COPY --chown`
  para asignar propiedad al usuario no-root sin sacrificar la práctica de seguridad.
- **Hito validado:** una alerta de burn-rate (SLOBurnRateSlow) recorrió la cadena
  completa Prometheus -> Alertmanager -> enricher, con el payload estructurado
  (labels, annotations, startsAt/endsAt) aterrizando en los logs del servicio.
  Verificado también el ciclo `resolved` (send_resolved: true).
  Evidencia: evidence/5a-webhook-firing.png, evidence/5a-webhook-resolved.png

### 5B — Recolección determinista de contexto + plantilla baseline  _(completa)_

**Objetivo:** que el enricher RECOLECTE contexto de múltiples fuentes y arme un
resumen de incidente con plantilla determinista (cero LLM). Es el BASELINE contra
el que se medirá el LLM en 5C — construido genuinamente bueno para que la
comparación de EXP-005 sea honesta.

**1er incremento — Prometheus:**
- Consulta la API HTTP de Prometheus (`/api/v1/query`) por el SLI actual —
  lectura programática de métricas, no vía UI.
- Cálculo determinista de la duración del incidente (aritmética de startsAt/endsAt;
  maneja el caso "firing" donde Alertmanager usa año 0001 como "sin fin").

**2do incremento — Argo CD:**
- Consulta la API de Argo (`/api/v1/applications`) por el deploy más reciente
  (app, revisión/commit, timestamp de sync). Habilita la correlación temporal
  deploy <-> caída del SLI que el LLM narrará en 5C.
- Autenticación: cuenta de servicio `enricher` de SOLO LECTURA, creada vía los
  ConfigMaps de Argo (argocd-cm para la cuenta apiKey; argocd-rbac-cm con
  policy.csv `get applications` — least privilege). Token generado por la API de
  Argo y guardado en un Secret (creado imperativamente, fuera de Git); el
  deployment lo inyecta como variable de entorno. El token nunca toca el repo.

**Decisiones de diseño:**
- **httpx (async)** sobre requests: no bloquea el event loop de FastAPI.
- **Degradación con gracia:** cada fuente (Prometheus, Argo) falla de forma
  independiente sin tumbar el enricher — marca ese dato como "no disponible" y
  entrega el resto. Un servicio que se activa durante incidentes no puede
  depender de que todas sus fuentes estén sanas.
- **Manejo del SLI NaN:** Prometheus devuelve NaN cuando el SLI se calcula sobre
  una ventana sin tráfico (0/0). No es fallo de la fuente sino ausencia de datos;
  se detecta (NaN != NaN, IEEE 754) y se marca "no disponible" en vez de mostrar
  un confuso "nan%". Caso límite encontrado comparando dos ejecuciones y corregido.
- **verify=False** en la llamada a Argo (cert autofirmado en local): atajo
  consciente de desarrollo; en producción se montaría el CA cert y se verificaría.
- **Tags de imagen versionados** (0.2.0 -> 0.3.0 -> 0.3.1): un tag nuevo por
  cambio fuerza redespliegue limpio y evita servir versiones cacheadas.

**Hito validado (evidencia honesta, incluyendo el bug encontrado y corregido):**
- Tres fuentes fusionadas: alerta (Alertmanager) + SLI (Prometheus) + último
  deploy (Argo) en un mismo resumen. Evidencia: evidence/5b-argo-integration.png
- Bug del SLI NaN: SLI sobre ventana sin tráfico salía como "nan%" (encontrado
  comparando dos ejecuciones). Evidencia: evidence/5b-nan-bug.png
- Bug corregido: mismo caso ahora muestra "no disponible" con warning explicativo
  (NaN != NaN, IEEE 754). Evidencia: evidence/5b-nan-fix.png

**El baseline determinista está completo:** contexto de 3 fuentes (alerta de
Alertmanager + SLI de Prometheus + deploy de Argo), ensamblado en un resumen
legible, resiliente a fallos de fuente y a datos vacíos. Cero LLM. Este es el
punto de partida de la comparación de 5C.

### 5C — Capa LLM sobre el baseline determinista  _(completa)_

**Objetivo:** añadir una narrativa en lenguaje natural ENCIMA del baseline
determinista (los dos conviven — Opción B), y medir en EXP-005 si el LLM aporta
valor real sobre el baseline. El LLM narra la correlación ya calculada por el
código; no decide ni diagnostica.

**Implementación:**
- El enricher recolecta el contexto UNA vez y genera dos salidas del mismo dict:
  el baseline determinista (hechos) y la narrativa LLM (síntesis). Garantiza que
  la comparación de EXP-005 sea sobre el mismo input.
- **Prompt restringido** que codifica la frontera: no inventar causas, no afirmar
  causalidad absoluta ("sospechoso probable", no "causa confirmada"), reportar
  faltantes como faltantes, no diagnosticar de logs. Temperatura 0.3 (consistencia
  sobre creatividad).
- **Convivencia (Opción B):** el reporte final tiene el baseline (siempre) + la
  narrativa (si el LLM responde). Si el LLM falla, el ingeniero recibe igual todos
  los hechos.

**Proveedor LLM — decisión y cambio (documentado, ADR-008):**
- Se optó por API en vez de local (no saturar la ThinkPad).
- Gemini se descartó: su free tier no estaba disponible para la cuenta
  (quota limit: 0, probable restricción regional). El diseño degradó con gracia
  ante el 429 (el baseline salió igual — evidencia útil de resiliencia).
- Se cambió a **Groq** (llama-3.3-70b-versatile). El cambio afectó UNA sola
  función (generate_llm_narrative); el resto del sistema no se enteró — bajo
  acoplamiento comprobado.

**EXP-005 — comparación baseline vs LLM (evaluación cualitativa honesta):**
- Con datos completos: el LLM explicitó la correlación temporal deploy<->caída
  como "sospechoso probable a investigar", respetando la frontera (lenguaje de
  hipótesis, no causalidad absoluta).
- Con dato faltante (SLI no disponible): el LLM lo reportó como faltante, NO lo
  inventó — validando la restricción anti-alucinación.
- Conclusión honesta: el LLM aporta valor real (correlación explícita +
  priorización accionable), pero contextual al lector — mayor para reducir carga
  cognitiva/juniors, potencialmente redundante para un senior. El baseline sigue
  siendo la base confiable.
- Evidencia: evidence/exp-005-llm-narrative-firing.png,
  evidence/exp-005-llm-narrative-nodata.png,
  evidence/5c-graceful-degradation-429.png 

**Fase 5 completa:** enriquecimiento de incidentes de punta a punta — alerta ->
Alertmanager -> enricher -> contexto de 3 fuentes -> baseline determinista +
narrativa LLM restringida, con degradación con gracia y proveedor desacoplado.


---

## Fase 6 — Terraform + GCS  _(opcional, no iniciada)_

**Objetivo:** provisionar bucket GCS con Terraform, backend remoto de state,
backup de snapshots.

_Se completará al arrancar la fase._

---
