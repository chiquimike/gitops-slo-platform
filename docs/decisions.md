# Decisiones de diseño (ADRs)

Registro de decisiones de arquitectura con su contexto y tradeoffs. Cada una
está pensada para ser defendida en entrevista: no basta con el "qué", importa
el "por qué" y qué se sacrificó.

---

## ADR-001 — k3d en lugar de kind o minikube

**Contexto:** se necesita Kubernetes local para el plano de cómputo.

**Decisión:** usar k3d (envuelve k3s).

**Por qué:**
- Continuidad con experiencia previa administrando un clúster k3s real → menor
  carga cognitiva.
- Recreación de clústeres en segundos, útil porque se destruye y recrea mucho
  al probar reconciliación.

**Tradeoff:** `kind` es el default más común en pipelines de CI/CD de la
industria. Elegir k3d optimiza para velocidad de iteración local a costa de no
usar la herramienta que más se ve en CI.

**Talking point:** _"Elegí k3d por continuidad con mi experiencia en k3s y por
la velocidad de recreación; sé que kind es el estándar de facto en CI, y ese es
el tradeoff que acepté conscientemente."_

---

## ADR-002 — El bootstrap paradox de GitOps

**Contexto:** el principio del proyecto es "todo declarativo, nada imperativo".
Pero Argo CD (la herramienta de GitOps) se instala con `kubectl apply` a mano.

**Decisión:** aceptar un único paso imperativo para instalar Argo CD, y a partir
de ahí todo lo demás es declarativo.

**Por qué:** es el problema del huevo y la gallina. No puedes usar GitOps para
instalar la herramienta de GitOps antes de que exista. Se arranca imperativamente
una sola vez; después, incluso Argo CD puede gestionarse a sí mismo de forma
declarativa.

**Talking point:** _"El bootstrap de GitOps es inherentemente imperativo: instalo
Argo CD una vez a mano y a partir de ahí todo el estado se vuelve declarativo.
Reconocer esa excepción demuestra que entiendo el modelo, no que lo violo."_

---

## ADR-003 — `prune: true` y `selfHeal: true`

**Contexto:** política de sincronización del `Application`.

**Decisión:** activar ambas.

**Por qué:**
- `selfHeal: true` — si alguien modifica el clúster a mano, Argo lo revierte al
  estado de Git. Es lo que hace real el "Git es la única fuente de verdad".
- `prune: true` — si se borra un manifiesto de Git, Argo borra el recurso del
  clúster. Enforcement completo del estado declarado.

**Tradeoff (importante):** `prune` es poderosa y destructiva. Si borras un
manifiesto por error, Argo borra el recurso en producción. Es el precio del
enforcement estricto: más consistencia, más riesgo ante un error humano en Git.

**Talking point:** _"Activé prune y selfHeal para enforcement estricto del estado
declarado. Soy consciente de que prune es destructiva: un borrado accidental en
Git se propaga al clúster. Es un tradeoff entre consistencia garantizada y
blast radius de un error en el repo."_

---

## ADR-004 — Separar Application CRs de los workloads (semilla app-of-apps)

**Contexto:** organización del repositorio.

**Decisión:** `argocd-apps/` para los `Application` (punteros), `apps/` para los
manifiestos de workload.

**Por qué:** con un solo servicio es indiferente, pero al crecer a muchos, esta
separación es la base del patrón app-of-apps, donde un Application raíz gestiona
a los demás. Diseñar la estructura correcta desde el día 1 evita reorganizar
después.

**Talking point:** _"Separé los Application CRs de los workloads desde el inicio
como semilla de app-of-apps. Es una decisión de arquitectura barata hoy que
evita una reorganización dolorosa cuando el número de servicios crezca."_

---

## ADR-005 — Cómputo local, estado durable en la nube

Ver [`architecture.md`](architecture.md) para el desarrollo completo. Resumen: el
cómputo es local porque ahí no está el aprendizaje; la nube (GCS + Terraform) se
reserva para estado durable, que es donde vive el patrón real de producción.

---

## ADR-006 — Desactivación del applicationset-controller de Argo CD

**Contexto:** El `argocd-applicationset-controller` entró en CrashLoopBackOff
(139 reinicios). Diagnóstico vía `kubectl logs --previous`: el controller
arrancaba pero no encontraba su CRD (`no matches for kind "ApplicationSet" in
version "argoproj.io/v1alpha1"... if kind is a CRD, it should be installed
before calling Start`). Es el gotcha clásico de orden de instalación: un
controller que arranca antes de que exista el CRD que consume. El `describe`
confirmó que NO era problema de imagen ni de recursos (imagen pulled OK), sino
lógica interna por el CRD ausente.

**Decisión:** Desactivar el controller escalando su deployment a 0 réplicas:
`kubectl scale deployment argocd-applicationset-controller --replicas=0 -n argocd`

**Por qué (no instalar el CRD faltante):**
- El proyecto NO usa ApplicationSets. Las Applications (demo-app, monitoring) se
  crean manualmente, una por una. Un controller para un tipo que no se usa es
  superficie operativa sin beneficio.
- Principio aplicado: minimizar la superficie operativa. No se corren ni
  mantienen componentes que no se usan; cada uno es algo que puede fallar,
  consumir recursos o enmascarar otro problema (justo lo que este hizo).
- Reversible: si en el futuro se necesitan ApplicationSets (p. ej. para gestionar
  múltiples entornos), se instala el CRD y se reactiva el controller
  (`--replicas=1`) con el orden correcto.

**Por qué escalar a 0 y no borrar:** escalar a 0 elimina el CrashLoop y el
consumo pero mantiene el deployment reactivable con un comando. Borrarlo exigiría
reinstalar desde el manifiesto original de Argo. Menor blast radius, reversible.

**Nota sobre GitOps / imperativo:** Argo CD se instaló imperativamente en Fase 1
(bootstrap paradox) y no se gestiona a sí mismo vía un Application. Por eso este
cambio imperativo (`kubectl scale`) es legítimo aquí y no hay selfHeal que lo
revierta: los componentes de Argo no están bajo reconciliación de Argo.

**Tradeoff reconocido:** algunos preferirían instalar el CRD para dejar Argo en
su estado estándar completo. Se optó por mínimo-necesario sobre completo-por-
defecto, priorizando una superficie operativa justificable y documentada.

**Talking point:** Un componente sano junto a uno en CrashLoop sigue siendo un
sistema degradado. Diagnostiqué la causa (CRD faltante), evalué si usaba el
componente (no), y lo desactivé de forma reversible y documentada, en vez de
parchear instalando algo que no necesito. Apagar porque falla es un parche;
apagar porque no se necesita, con justificación escrita, es decisión de
plataforma.

---

## ADR-007 — Reordenamiento del roadmap tras completar el núcleo

**Contexto:** El plan original del proyecto contemplaba 7 fases:
1) Sustrato GitOps, 2) FastAPI instrumentada, 3) Observabilidad, 4) SLO +
burn-rate alerting, 5) Experimentos de carga formales, 6) Terraform + GCS,
7) Capa IA/AIOps. Tras completar el núcleo (Fases 1-4), se reevaluó el roadmap
antes de continuar.

**Decisión:** Reorganizar las fases restantes de la siguiente forma:
- La antigua **Fase 5 (experimentos de carga formales)** se considera CUBIERTA:
  sus objetivos —validar el sistema bajo estrés con evidencia medida— ya se
  cumplieron de forma distribuida en EXP-002 (chaos degradando el SLI) y EXP-004
  (carga sostenida disparando el burn-rate). No se crea una fase separada
  redundante.
- La antigua **Fase 7 (IA/AIOps)** pasa a ser la nueva **Fase 5**, y se prioriza
  para ejecutarse a continuación.
- La antigua **Fase 6 (Terraform + GCS)** se mantiene como **Fase 6**,
  planificada como trabajo futuro.

**Por qué priorizar AIOps (nueva Fase 5) sobre Terraform/GCS (Fase 6):**
- La capa de IA/AIOps es el diferenciador declarado para el mercado objetivo:
  demostrar orquestación responsable de IA, no solo operación manual de infra.
- Ya se cuenta con la telemetría real (SLI, burn-rate, alertas) necesaria para
  montar el enriquecimiento de incidentes sobre datos verificados. La base
  existe; es el momento de construir encima.
- Terraform/GCS es valioso (cubre la brecha de nube) pero más incremental y menos
  diferenciador; se difiere sin perder valor.

**Tradeoff reconocido:** el roadmap ya no es secuencial 1-2-3...; hay un
reordenamiento explícito. Se acepta porque un roadmap es una hipótesis que se
ajusta con evidencia, no un contrato inmutable. La numeración se mantiene sin
huecos (5 = IA, 6 = Terraform) para legibilidad, con esta trazabilidad del cambio.

**Talking point:** "Reevalué mi roadmap tras completar el núcleo en vez de
seguirlo rígidamente: verifiqué que los objetivos de validación bajo estrés ya
se habían cumplido en experimentos previos, y prioricé la capa de mayor valor
diferenciador con la evidencia de que la base ya existía. Gestionar prioridades
con criterio, y documentar el porqué del cambio, es parte de operar como
ingeniero, no solo ejecutar un plan."

---

## ADR-008 — Capa de IA: baseline determinista + LLM restringido (no LLM por moda)

**Contexto:** El enriquecimiento de incidentes puede resolverse con lógica
determinista o con un LLM. La regla del proyecto: no meter un LLM por moda; si una
regla determinista resuelve el problema, se usa esa.

**Decisión:** Arquitectura híbrida en dos capas que CONVIVEN (no se reemplazan):
1. **Baseline determinista** (siempre): el código recolecta contexto de 3 fuentes
   (alerta de Alertmanager, SLI de Prometheus, último deploy de Argo CD), calcula
   la correlación temporal de forma determinista (aritmética de timestamps), y
   arma un resumen con plantilla. Estos son HECHOS verificados.
2. **Narrativa LLM** (capa de valor añadido): un LLM toma ese contexto ya
   verificado y lo SINTETIZA en lenguaje natural accionable, explicitando la
   correlación que el baseline solo yuxtapone.

**Frontera de responsabilidad (lo esencial):**
- El CÓDIGO correlaciona de forma determinista; el LLM SOLO narra esa correlación
  ya calculada. Si se quita el LLM, el sistema sigue sabiendo qué deploy coincide
  con la caída — solo pierde la narrativa legible.
- El LLM está restringido por prompt: no inventar causas, no afirmar causalidad
  absoluta ("sospechoso probable a investigar", nunca "causa confirmada"),
  reportar datos faltantes como faltantes, no diagnosticar desde logs.
- Validado empíricamente en EXP-005: el LLM respetó la frontera con datos
  completos Y con un dato faltante (no lo inventó).

**Por qué la convivencia (Opción B) y no reemplazo:** los hechos deterministas son
la base confiable; el LLM es valor añadido verificable contra esa base. Si el LLM
falla, el ingeniero recibe igual el baseline completo (degradación con gracia,
demostrada cuando el primer proveedor devolvió 429).

**Decisión de proveedor:** Se optó por LLM vía API (no local) para no saturar el
hardware. Se evaluó primero Gemini; su free tier no estaba disponible para la
cuenta (quota limit: 0, probable restricción regional). Se cambió a Groq. El
cambio fue trivial —una sola función (generate_llm_narrative)— porque el proveedor
está desacoplado del resto del sistema. Esa intercambiabilidad es una propiedad
de diseño deliberada: no acoplarse a un proveedor de IA específico. 
Evidencia: evidence/5c-graceful-degradation-429.png 

**Tradeoff reconocido:** integrar un LLM añade latencia, costo y límites de rate
que la lógica determinista no tiene (topamos un 429). Un enricher de producción
necesitaría rate limiting o cache — irónicamente, una tormenta de alertas (cuando
más se necesita) es cuando más fácil se satura la cuota del LLM.

**Talking point:** El enriquecimiento se resuelve ~70% con una plantilla
determinista; el LLM aporta el 30% de síntesis y correlación explícita, no el tono.
La lógica crítica (detectar qué deploy coincide) es determinista y confiable; el
LLM solo comunica. Lo probé: respeta la frontera con y sin datos, y si falla, el
baseline sale igual. Y está desacoplado — cambié de proveedor tocando una función.

---

## Pendientes de decisión (a documentar cuando se aborden)

- **ADR-009** — Estrategia de burn-rate alerting (ventanas múltiples) vs.
  umbrales estáticos.

