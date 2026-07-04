# Arquitectura

## Principio rector

El estado deseado de todo el sistema vive en Git. Argo CD reconcilia el clúster
contra ese estado de forma continua. El clúster es un **reflejo** de Git, no una
fuente de verdad independiente. Corolario operativo: cuando algo está mal, se
corrige en Git, no en el clúster.

## Diagrama

```
                          ┌──────────────────────────┐
                          │  GitHub (source of truth)│
                          │  gitops-slo-platform     │
                          └───────────┬──────────────┘
                                      │ polling (~3 min) / webhook
                                      ▼
        ┌──────────────────────────────────────────────────────────┐
        │  k3d cluster  "slo-platform"  (laptop)                   │
        │                                                          │
        │   ┌──────────┐   reconcilia    despliega                 │
        │   │ Argo CD  │────────────────────────────┐              │
        │   └──────────┘                             ▼             │
        │                                  ┌───────────────────┐   │
        │                                  │ ns: demo          │   │
        │                                  │ demo-app (FastAPI)│   │
        │                                  │  /metrics         │───┼──┐
        │                                  └───────────────────┘   │  │ scrape
        │                                  ┌───────────────────┐   │  │
        │                                  │ ns: monitoring    │◄──┼──┘
        │                                  │  Prometheus       │   │
        │                                  │  Grafana          │   │
        │                                  │  Alertmanager     │   │
        │                                  └───────────────────┘   │
        └──────────────────────────────────────────────────────────┘
                                      │ backups / estado durable
                                      ▼
                          ┌─────────────────────────┐
                          │  GCS bucket (Terraform) │
                          │  + backend remoto TF    │
                          └─────────────────────────┘
```

## Por qué el cómputo es local y la nube es solo para estado durable

El aprendizaje del proyecto está en el modelo GitOps y en los SLOs, no en el
sustrato de cómputo. Correr Argo CD sobre un EKS/GKE en lugar de un k3d local no
enseña nada nuevo sobre GitOps y sí introduce costo y riesgo de factura.

Por eso el cómputo se mantiene local (iteración rápida, costo cero) y la nube se
reserva para lo que sí justifica salir de la laptop: **estado durable**
(backups de dashboards/config) gestionado con Terraform y backend remoto. Ese es
el patrón real de producción para el estado de Terraform.

**Tradeoff aceptado:** el proyecto no demuestra operación de un clúster
gestionado en la nube (EKS/GKE). Esa brecha se cubre deliberadamente en un
proyecto posterior, donde lo híbrido sí aporta valor.

## Estructura del repositorio

```
gitops-slo-platform/
├── README.md
├── apps/
│   └── demo-app/            # manifiestos del workload (Deployment, Service)
│       ├── deployment.yaml
│       └── service.yaml
├── argocd-apps/
│   └── demo-app.yaml        # Application CR de Argo CD (el "puntero")
├── docs/
├── experiments.md
└── evidence/
```

Se separan los `Application` de Argo CD (`argocd-apps/`, punteros) de los
manifiestos de workload (`apps/`). Es la semilla del patrón **app-of-apps**: al
crecer a muchos servicios, la estructura escala sin reorganizarse. Ver
[`decisions.md`](decisions.md).
