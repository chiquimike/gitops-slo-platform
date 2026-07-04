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

## Pendientes de decisión (a documentar cuando se aborden)

- **ADR-006** — Definición formal del SLI/SLO (qué mide exactamente la
  disponibilidad: ¿pods healthy o tasa de éxito de requests?).
- **ADR-007** — Estrategia de burn-rate alerting (ventanas múltiples) vs.
  umbrales estáticos.
- **ADR-008** — Decisión sobre la capa de IA: qué se resuelve con reglas
  deterministas y qué justifica un LLM (enriquecimiento de incidentes).
