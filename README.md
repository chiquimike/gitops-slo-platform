# Self-Healing GitOps Platform with SLO-based Alerting

Plataforma de Kubernetes gestionada 100% por GitOps (Argo CD), con una app de
demo instrumentada, observabilidad completa (Prometheus + Grafana) y alertas
basadas en SLOs reales con error budgets — no en umbrales arbitrarios de CPU.

> **Estado del proyecto:** en construcción. Ver progreso por fase en
> [`docs/phases.md`](docs/phases.md).

---

## Qué demuestra este proyecto

- **GitOps real:** el estado del clúster se declara en Git y Argo CD lo
  reconcilia. Nunca se aplica configuración a mano.
- **Self-healing:** el drift de configuración se revierte automáticamente al
  estado declarado (evidencia medida en [`experiments.md`](experiments.md)).
- **Observabilidad instrumentada:** métricas de aplicación expuestas y
  scrapeadas por Prometheus, visualizadas en Grafana.
- **SLO-driven alerting:** alertas basadas en consumo de error budget
  (burn-rate), no en umbrales de infraestructura.
- **Infraestructura como código:** estado durable en la nube (GCS) gestionado
  con Terraform y backend remoto.

## Arquitectura (resumen)

El plano de cómputo corre local (k3d) porque el aprendizaje está en el modelo
GitOps y SLO, no en el sustrato de cómputo. La nube se reserva para estado
durable. Detalle completo y diagrama en [`docs/architecture.md`](docs/architecture.md).

```
Git (GitHub) ──reconcilia──> Argo CD ──despliega──> [ demo-app | Prometheus | Grafana ]
     ▲                                                        (todo en k3d local)
     └── única fuente de verdad
```

## Stack

Estado por componente: `Operativo` (construido y probado), `En construcción`
(fase activa), `Planeado` (fase futura). El repo refleja el estado real; este
stack describe la arquitectura objetivo.

| Capa               | Herramienta                         | Estado            |
|--------------------|-------------------------------------|-------------------|
| Kubernetes local   | k3d (envuelve k3s)                  | Operativo         |
| GitOps             | Argo CD                             | Operativo         |
| App de demo        | FastAPI (Python) instrumentada      | Operativo         |
| Observabilidad     | Prometheus + Grafana + Alertmanager | Operativo         |
| SLO alerting       | Prometheus burn-rate rules          | Planeado          |
| Estado durable     | Google Cloud Storage (GCS)          | Planeado          |
| IaC                | Terraform (backend remoto en GCS)   | Planeado          |

> Nota: durante la Fase 1 el workload de demo es `traefik/whoami` (imagen
> trivial usada para validar el loop de GitOps). Se reemplaza por la FastAPI
> instrumentada en la Fase 2.

## Cómo correrlo

> _Pendiente: completar cuando la Fase 1 esté cerrada y probada de cero._

```bash
# 1. Crear el clúster local
k3d cluster create slo-platform --agents 1

# 2. Instalar Argo CD (paso imperativo único — ver bootstrap paradox en docs/decisions.md)
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# 3. Apuntar Argo CD a este repo
kubectl apply -f argocd-apps/demo-app.yaml
```

Rutina para retomar tras apagar la laptop:

```bash
k3d cluster start slo-platform
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

## Documentación

- [`docs/architecture.md`](docs/architecture.md) — arquitectura y diagrama.
- [`docs/decisions.md`](docs/decisions.md) — decisiones de diseño y tradeoffs (ADRs).
- [`docs/phases.md`](docs/phases.md) — bitácora de progreso por fase.
- [`experiments.md`](experiments.md) — bitácora de experimentos de fiabilidad.
- [`evidence/`](evidence/) — capturas y evidencia versionada.

---

_Proyecto de portafolio — Miguel Axel. Perfil DevOps/Platform con miras a SRE._
