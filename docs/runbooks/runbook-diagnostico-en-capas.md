# Runbook — Diagnóstico en capas: "algo no responde / no carga"

> Método personal de diagnóstico de afuera hacia adentro para cuando un servicio,
> UI o endpoint deja de responder en un clúster de Kubernetes. Escrito para
> seguirse bajo estrés, sin depender de la memoria. — Miguel Axel

## Principio rector

Un "no carga" en el navegador (o un timeout) solo dice que ALGO en la cadena
falló, no QUÉ. La cadena tiene varias capas; el fallo puede estar en cualquiera.
Regla de oro: **diagnostica de la capa más externa a la más interna, y no
arregles una capa antes de confirmar que la anterior está sana.** Aislar dónde
vive el fallo evita perder tiempo arreglando la capa equivocada. Un port-forward
muerto y un pod en CrashLoop se ven IDÉNTICOS desde el navegador, pero tienen
causas y fixes opuestos.

## La cadena de capas (de afuera hacia adentro)

    [Navegador / cliente]
          ↓  (capa 1: túnel de acceso)
    [port-forward / ingress / LoadBalancer]
          ↓  (capa 2: enrutamiento interno)
    [Service → Endpoints]
          ↓  (capa 3: el workload)
    [Pod / contenedor corriendo]
          ↓  (capa 4: la configuración interna)
    [config, montajes, permisos, app]
          ↑  (capa 0: soporte — el clúster mismo)
    [nodos / k3d vivo]

## Procedimiento paso a paso

### Capa 0 — ¿El clúster está vivo? (empezar aquí siempre)
    kubectl get nodes
- Nodo(s) en `Ready`  -> clúster vivo, seguir a Capa 1.
- Error de conexión   -> el clúster (k3d) se detuvo. ¿Se suspendió la laptop?
  Fix: `k3d cluster start <cluster>` y re-levantar port-forwards.

### Capa 1 — ¿El túnel de acceso sigue vivo?
Contexto: un `port-forward` es un proceso local atado a UN pod. MUERE si:
cierras la terminal, la laptop suspende, o —MUY COMÚN— el pod se recreó tras un
deploy (el túnel queda huérfano apuntando a un pod que ya no existe).
- Sospecha esto PRIMERO si el "no carga" ocurrió justo después de un `git push`
  / redeploy (el deploy recrea el pod → el túnel viejo muere).
- Fix: re-levantar el port-forward:
    kubectl port-forward svc/<servicio> <local>:<remoto> -n <namespace>

### Capa 2 — ¿El Service enruta a algún pod?
    kubectl get endpoints <servicio> -n <namespace>
- Lista de IPs  -> el Service tiene backends sanos, seguir a Capa 3.
- Vacío (<none>) -> el `selector` del Service no matchea las labels de ningún
  pod. Fallo SILENCIOSO clásico. Revisar que selector == labels del pod.

### Capa 3 — ¿El pod está corriendo?
    kubectl get pods -n <namespace>
- `Running` (READY 1/1)     -> el pod está sano; el problema estaba más afuera
  (Capa 1 o 2). Si llegaste aquí y todo lo externo estaba bien, revisa Capa 4.
- `CrashLoopBackOff`/`Error` -> el contenedor arranca y se cae. Ir a Capa 4 (logs).
- `Pending`/`ContainerCreating` (atascado) -> problema de scheduling, imagen,
  o montaje de volúmenes/ConfigMaps. Ver `kubectl describe pod`.
- `ImagePullBackOff`/`ErrImagePull` -> no encuentra la imagen. ¿Está en el
  registry / importada a k3d? ¿Nombre y tag correctos?

### Capa 4 — ¿Por qué el contenedor falla? (la config interna)
    kubectl describe pod <pod> -n <namespace>     # ver Events + State + Reason + Exit Code
    kubectl logs <pod> -n <namespace> --previous   # logs de la instancia que YA crasheó
- `--previous` es CLAVE en CrashLoop: los logs normales muestran el arranque
  nuevo (que aún no falla); `--previous` muestra el crash real.
- Causas típicas: error de config, permisos de volumen (fsGroup), CRD faltante
  ("if kind is a CRD, it should be installed before calling Start"), OOMKilled,
  secreto/variable de entorno ausente.

## Reglas de oro (para no meter la pata bajo estrés)
1. No arregles la capa 4 antes de confirmar que la 0-1 están sanas.
2. El editor/navegador ADIVINA; el sistema que consume el recurso es la autoridad.
3. Tras un deploy, sospecha del port-forward ANTES que de la config.
4. `--dry-run=client` valida un manifiesto sin aplicarlo.
5. Verifica, no asumas. Un `get pods` de 3 segundos ahorra 30 minutos de teoría.

## Talking point derivado
Diagnostico incidentes de afuera hacia adentro: 
clúster vivo → túnel → Service/endpoints → pod → config. 
No reviso la configuración interna antes de confirmar
que las capas externas están sanas, porque un port-forward roto y un pod en
CrashLoop se ven idénticos desde el cliente pero tienen fixes opuestos. Aislar la
capa del fallo antes de actuar es lo que evita perder tiempo en la capa equivocada.
