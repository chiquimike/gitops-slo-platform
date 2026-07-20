# Experiments Log — GitOps SLO Platform

Bitácora de experimentos de fiabilidad. Cada entrada documenta una prueba
controlada: hipótesis, método, medición y limitaciones. Objetivo: que cada
número afirmado en el CV o en entrevista sea rastreable hasta su experimento.
No se afirma ningún número que no salga de aquí.

---

## EXP-001 — Self-heal de drift de réplicas (Argo CD)

- **Fecha:** 2026-07-03
- **Fase:** 1 (sustrato GitOps)
- **Entorno:** k3d local `slo-platform`, Argo CD stable, configuración de
  reconciliación por defecto. Laptop ThinkPad X280, un solo nodo lógico.

### Hipótesis
Con `selfHeal: true` en el `Application`, un cambio manual (imperativo) al número
de réplicas del deployment será detectado y revertido automáticamente por Argo
CD al estado declarado en Git, sin intervención humana.

### Método
1. Estado deseado en Git: `replicas: 3`.
2. Inyección de drift (chaos manual):
   `kubectl scale deployment demo-app -n demo --replicas=8`
3. Observación con:
   `kubectl get events -n demo --sort-by='.lastTimestamp' --watch`
4. Medición: diferencia entre el timestamp **absoluto** del evento `Scaled up`
   (provocado manualmente) y el del evento `Scaled down` (provocado por Argo).

### Resultado
- Réplicas declaradas: 3
- Réplicas inyectadas: 8
- Pods excedentes creados y luego terminados por Argo: 5
- Timestamp del ataque (`Scaled up`):   2026-07-03T17:34:53Z
- Timestamp de la corrección (`Scaled down`): 2026-07-03T17:39:27Z
- **Tiempo de self-heal medido: ~274 s (≈4 min 34 s)**

  <!-- VERIFICADO: recalculamos 17:39:27 − 17:34:53 = 4:34 = 274 s. Si repites la
       prueba, actualiza con tu nuevo dato o reporta un rango. -->

### Interpretación (el "por qué" del número)
El grueso del tiempo es **latencia de detección**, no de ejecución. Argo CD
reconcilia por polling a Git en un ciclo (~3 min por defecto), de modo que el
drift no se detecta en tiempo real continuo sino en el siguiente ciclo. Una vez
detectado, la corrección (matar los pods excedentes) es de segundos. Por eso un
`AGE` de pod de "2s" NO es el tiempo de self-heal: mide solo el último eslabón.

### Palanca de optimización (no aplicada, y por qué)
Para acelerar la detección se podría:
- Reducir `timeout.reconciliation` en la configuración de Argo CD, o
- Configurar un webhook de GitHub (detección casi instantánea de cambios en
  *Git*; nota: acelera cambios en el repo, no necesariamente drift dentro del
  clúster).

Ambas opciones aumentan la carga sobre Git y el API server. No se optimizó
porque, para este caso de uso, la latencia por defecto es aceptable. Saber
cuándo NO optimizar es parte de la decisión.

### Limitaciones / honestidad
- Clúster local de un solo nodo lógico, sin carga concurrente.
- El número no es extrapolable a un clúster de producción multi-nodo con webhook.
- Es una **demostración del mecanismo**, no un benchmark de producción.
- El valor exacto depende de en qué punto del ciclo de polling cayó el ataque;
  por eso conviene reportar un rango tras varias corridas.

### Evidencia
- `evidence/exp-001-selfheal-pods.png` — 5 pods en `Error` (edad ~2s) junto a
  3 `Running` (edad ~35m): Argo terminando el exceso.
- `evidence/exp-001-events-timestamps.png` — eventos `Scaled up` / `Scaled down`
  con timestamps absolutos usados para la medición.

### Talking point derivado
Mi self-heal por defecto tardó ~4.5 min porque Argo CD reconcilia por polling
cada ~3 min. No es lentitud, es un tradeoff entre latencia de reconciliación y
carga sobre Git/API server. Si necesitara más reactividad, bajaría el intervalo
o añadiría webhooks, a costa de más carga. El número no es fijo: es una decisión
de diseño.

---

## EXP-002 — Inyección de caos y degradación del SLI de disponibilidad

- **Fecha:** 2026-07-05
- **Fase:** 2 (FastAPI instrumentada) — validación local, sin Kubernetes.
- **Entorno:** app corriendo con uvicorn en localhost:8000, un solo proceso.
  Instrumentación manual con prometheus-client.

### Hipótesis
El endpoint de caos inyectable (`/chaos`) permite degradar de forma controlada
el SLI de disponibilidad, y la instrumentación manual (Counter
`http_requests_total` con label `status_code`) lo refleja fielmente en tiempo
real, distinguiendo respuestas exitosas (200) de fallidas (500).

### Método
1. Reinicio de la app para partir de contadores en cero (línea base limpia).
2. Línea base SIN caos: 20 requests a `/api/work`.
   `for i in {1..20}; do curl -s localhost:8000/api/work > /dev/null; done`
3. Captura de `/metrics` -> foto "exp-002-baseline-metrics.png".
4. Activación de caos al 50%: `curl -X POST "localhost:8000/chaos?fail_rate=0.5"`.
5. 20 requests más a `/api/work` con caos activo.
6. Captura de `/metrics` -> foto "exp-002-chaos-metrics.png".
7. Apagado de caos: `curl -X POST "localhost:8000/chaos?fail_rate=0"`.

### Resultado
- Requests exitosos (status_code=200) a /api/work: 30
- Requests fallidos  (status_code=500) a /api/work: 10
- Total: [[40]]
- SLI de disponibilidad observado: 30 / 40 = 75%

  <!-- Ejemplo del acomodo de los datos: exitosos / total = [X]%. Podemos hacer
       distintas corridas para que nos den más porcentajes. -->

### Interpretación
El fail_rate es una PROBABILIDAD, no una cuota exacta: con fail_rate=0.5 sobre
20 requests, el número de fallos ronda ~10 pero varía por aleatoriedad (obtener
11 o 9 es normal). La instrumentación captura fielmente cada resultado por
status_code. El histograma http_request_duration_seconds captura en paralelo la
latencia (SLI de latencia), disponible para el SLO de Fase 4.

### Limitaciones / honestidad
- Prueba local de un solo proceso, sin Kubernetes ni concurrencia real.
- El estado de caos vive en memoria por proceso: con varias réplicas no se
  propaga (limitación conocida, a manejar en la fase de experimentos).
- Demostración del mecanismo de instrumentación + caos, no un benchmark.

### Evidencia
- evidence/exp-002-baseline-metrics.png  (Counter solo con status_code=200)
- evidence/exp-002-chaos-metrics.png      (Counter con 200 y 500)

### Talking point derivado
Mi instrumentacion manual distingue exito de fallo por status_code en un
Counter, del que sale directamente el SLI de disponibilidad. Validé el mecanismo
inyectando caos controlado y observando el SLI degradarse en tiempo real, con
evidencia antes/después.

---

## EXP-003 — Reproducibilidad de la configuración de Grafana ante destrucción del pod

- **Fecha:** 2026-07-08
- **Fase:** 3 (Observabilidad) — sub-fase 3B (Grafana).
- **Entorno:** k3d local, namespace `monitoring`. Grafana desplegada vía Argo CD
  con data source y dashboard provisionados declarativamente desde ConfigMaps.

### Hipótesis
La configuración de Grafana (data source de Prometheus y dashboard "demo-app SLI")
es reproducible desde Git y sobrevive a la destrucción del pod, porque vive en
ConfigMaps versionados y no en el almacenamiento efímero (emptyDir) del contenedor.
Predicción: al eliminar el pod de Grafana, el nuevo pod se levanta con el data
source y el dashboard intactos, sin intervención manual.

### Método (chaos aplicado a la configuración)
1. Estado inicial: Grafana corriendo, dashboard "demo-app SLI" visible, data
   source Prometheus provisionado y pasando "Save & test".
2. Inyección de falla (destrucción deliberada del pod):
   `kubectl delete pod -l app=grafana -n monitoring`
3. Observación: esperar a que el Deployment recree el pod
   (`kubectl get pods -n monitoring -w`).
4. Verificación: acceder de nuevo a Grafana (port-forward) y comprobar que el
   dashboard y el data source siguen presentes, sin reconfiguración manual.

### Resultado
- Pod de Grafana eliminado y recreado por el Deployment: sí.
- Dashboard "demo-app SLI" presente tras la recreación: SÍ (sobrevivió).
- Data source Prometheus presente y funcional tras la recreación: SÍ.
- Intervención manual requerida para restaurar la config: NINGUNA, GRACIAS A DIOS.

  Resultado binario: la hipótesis se CONFIRMA. La configuración es reproducible
  y resiliente a la pérdida del pod.

### Interpretación (el "por qué")
La configuración sobrevive porque su fuente de verdad son ConfigMaps versionados
en Git, montados como archivos al arrancar el pod (provisioning declarativo), no
el estado interno del contenedor. El emptyDir solo guarda datos operativos
internos de Grafana, no la configuración. Es el mismo principio que la config de
Prometheus vía ConfigMap: fuente externa al pod = persiste; estado local al pod =
efímero.

### Contraste (lo que habría pasado con click-ops)
Si el dashboard se hubiera creado manualmente por la UI, habría vivido solo en el
emptyDir y se habría PERDIDO al destruir el pod. Este experimento es la evidencia
empírica de por qué el provisioning declarativo supera al click-ops: no es una
preferencia estética, es una propiedad de resiliencia demostrable.

### Limitaciones / honestidad
- Prueba en entorno local de un nodo. La resiliencia demostrada es de la
  CONFIGURACIÓN, no de los datos de métricas (que viven en Prometheus, con su
  propia limitación de emptyDir documentada aparte).
- No prueba alta disponibilidad de Grafana (sigue siendo 1 réplica); prueba
  reproducibilidad de configuración, que es una propiedad distinta.

### Evidencia
- evidence/exp-003-dashboard-after-pod-delete.png  (dashboard visible tras
  recrear el pod, con su título correcto y datos)

### Talking point derivado
Validé la reproducibilidad de mi observabilidad con chaos: destruí el pod de
Grafana y el dashboard se reconstruyó solo desde ConfigMaps versionados. La
diferencia entre provisioning declarativo y click-ops no es teórica; la probé
matando el pod. Con click-ops, el dashboard se habría perdido.

---

## EXP-004 — Burn-rate alerting: detección de violación de SLO vía chaos

- **Fecha:** 2026-07-09
- **Fase:** 4 (SLO + burn-rate alerting).
- **Entorno:** k3d local. Prometheus con recording rules (SLI multi-ventana) y
  alert rules de burn-rate. SLO de disponibilidad = 99%, error budget = 1%.

### Hipótesis
Un fallo sostenido que consuma error budget a más de 14.4x el ritmo permitido
disparará la alerta Page (SLOBurnRateHigh) cuando la tasa de fallo supere el
umbral en AMBAS ventanas (5m y 1h) durante el periodo `for: 2m`, siguiendo la
metodología burn-rate multi-ventana del SRE Workbook de Google.

### Método (chaos + observación de la transición de estados)
1. Estado inicial: alertas en `Inactive`, servicio sano.
2. Inyección de fallo masivo: `curl -X POST ".../chaos?fail_rate=0.5"` (50%).
3. Tráfico sostenido ~6-7 min para llenar las ventanas de scrape con fallos.
4. Observación de la pestaña Alerts: transición Inactive -> Pending -> Firing.
5. Apagado del caos (fail_rate=0) y observación del retorno a Inactive.

### Resultado
- Tasa de fallo medida (Value de la alerta): 0.486 (48.6% de fallos).
- Umbral de disparo: (1 - SLI) > 14.4 * 0.01 = 0.144. Superado ampliamente.
- SLOBurnRateHigh (severity=page): alcanzó estado FIRING.
  Active since: 2026-07-09T18:46:21Z.
- SLOBurnRateSlow (severity=ticket): también activa (50% > umbral de 3x).
- Al apagar el caos, las alertas retornaron a Inactive conforme las ventanas
  se limpiaron de fallos.

### Interpretación (el "por qué")
El 48.6% de fallos superó por mucho el umbral de burn-rate de la Page (14.4x el
budget), disparando en las ventanas cortas (5m y 1h). Ambas alertas (Page y
Ticket) se activaron porque un fallo del 50% excede tanto el umbral de 14.4x
como el de 3x. El `for: 2m` retuvo la alerta en Pending hasta confirmar que la
condición era sostenida, evitando disparos por parpadeo. La cadena completa
funcionó: chaos -> SLI degradado -> error budget quemándose -> alerta Firing.

### Limitaciones / honestidad
- Prometheus con historia corta (pod recién recreado): la ventana de 1h tenía
  poca profundidad; con más historia, el comportamiento de la ventana larga
  sería más representativo.
- Las alertas DISPARAN en Prometheus pero NO se enrutan a ningún destino: eso es
  trabajo de Alertmanager, no desplegado (decisión de alcance). Ver estado
  Firing en la UI es suficiente para demostrar el mecanismo de burn-rate.
- Entorno local de un nodo, sin carga concurrente real.

### Evidencia
- evidence/exp-004-slo-burnrate-firing.png  (SLOBurnRateHigh en FIRING, Value 0.486)
- evidence/exp-004-both-alerts-active.png    (Page y Ticket ambas activas)

### Talking point derivado
Implementé burn-rate alerting multi-ventana sobre un SLO del 99%. Lo validé con
chaos: inyecté 50% de fallos y observé la alerta pasar de Inactive a Pending a
Firing cuando el burn rate superó 14.4x el error budget en las ventanas 5m y 1h.
No alerto sobre umbrales de infraestructura sino sobre consumo de error budget,
la metodología del SRE Workbook de Google, que elimina el ruido de los umbrales
estáticos. El enrutamiento a un canal real sería trabajo de Alertmanager.

---

## EXP-005 — Baseline determinista vs. narrativa LLM (enriquecimiento de incidentes)

- **Fecha:** 2026-07-19
- **Fase:** 5C (capa LLM sobre baseline determinista).
- **Entorno:** k3d local. Enricher con contexto de 3 fuentes (Alertmanager +
  Prometheus SLI + Argo CD deploy). LLM: Groq (llama-3.3-70b-versatile), temp 0.3.

### Hipótesis
Sobre el mismo incidente y el mismo contexto ya recolectado de forma determinista,
un LLM aporta valor al EXPLICITAR la correlación temporal (deploy <-> caída del
SLI) que el baseline solo yuxtapone, produciendo una narrativa accionable — SIN
inventar datos, sin afirmar causalidad absoluta, y reportando datos faltantes como
faltantes. El LLM narra; no decide ni diagnostica.

### Método (comparación cualitativa, mismo input)
El enricher recolecta el contexto UNA vez y genera DOS salidas del mismo dict:
(1) plantilla determinista (baseline), (2) narrativa LLM. Se comparan lado a lado
sobre dos incidentes: uno con SLI disponible (firing) y otro con SLI no disponible
(resolved). Criterios definidos de antemano: ¿explicita la correlación?
¿es accionable? ¿respeta las restricciones del prompt (no causalidad absoluta,
no inventar, reportar faltantes)?

### Resultado
**Caso 1 — incidente con datos completos (SLI 51%, deploy conocido):**
- Baseline: yuxtapuso los hechos (SLI 51%, deploy monitoring @ commit, hora).
- LLM: explicitó la correlación — señaló el deploy como "sospechoso probable a
  investigar en relación con la degradación", y añadió priorización accionable
  ("investigar para determinar la causa raíz"). Usó lenguaje de hipótesis
  ("podría ser"), NO de causalidad confirmada. Respetó la frontera.

**Caso 2 — incidente con dato faltante (SLI no disponible, resolved):**
- Baseline: mostró "SLI: no disponible".
- LLM: reportó honestamente "la disponibilidad del SLI no está disponible para
  este período" — NO inventó un valor. Respetó la regla anti-alucinación.

### Interpretación (juicio honesto)
- **Valor real aportado por el LLM:** convierte datos adyacentes en una hipótesis
  conectada (correlación temporal explícita) y orienta la acción. Este es el 30%
  que justifica el LLM sobre el baseline, tal como se predijo en el diseño.
- **Límite honesto del valor:** el aporte es mayor para un ingeniero junior o
  para reducir carga cognitiva bajo estrés; para un senior que lee el baseline al
  instante, la narrativa puede ser redundante. El LLM no aporta datos nuevos —
  solo comunica mejor los existentes.
- **Validación de la frontera:** en ambos casos el LLM respetó el prompt
  restringido — no afirmó causalidad absoluta, no inventó el dato faltante. La
  frontera código-correlaciona / LLM-narra se sostuvo empíricamente.

### Contraste con el diseño
Se confirma la decisión de diseño (ADR-008): el enriquecimiento se resuelve ~70%
con el baseline determinista; el LLM aporta el 30% de síntesis/correlación. La
convivencia (Opción B) probó su valor: cuando Gemini falló antes (429), el
baseline salió igual — el LLM es capa de valor añadido, no dependencia crítica.

### Limitaciones / honestidad
- Evaluación cualitativa sobre 2 incidentes, no un estudio estadístico.
- "Valor" del LLM juzgado por criterios definidos, no por métrica numérica
  (deliberado: la calidad narrativa no se reduce honestamente a un número).
- Groq como proveedor tras descartar Gemini por cuota (limit:0); el bajo
  acoplamiento permitió el cambio tocando una sola función.

### Evidencia
- evidence/exp-005-llm-narrative-firing.png   (caso con datos, correlación explícita)
- evidence/exp-005-llm-narrative-nodata.png   (caso sin SLI, reportado sin inventar)

### Talking point derivado
Medí el aporte del LLM sobre un baseline determinista fuerte, no contra un
strawman. El LLM explicitó la correlación temporal deploy-caída como 'sospechoso
probable', respetando el prompt restringido en ambos casos —con datos y sin
ellos, donde reportó el faltante sin inventarlo—. Concluí honestamente que el
valor es real pero contextual al lector: mayor para reducir carga cognitiva, y
el baseline determinista sigue siendo la base confiable si el LLM falla.

