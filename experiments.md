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
_"Mi self-heal por defecto tardó ~4.5 min porque Argo CD reconcilia por polling
cada ~3 min. No es lentitud, es un tradeoff entre latencia de reconciliación y
carga sobre Git/API server. Si necesitara más reactividad, bajaría el intervalo
o añadiría webhooks, a costa de más carga. El número no es fijo: es una decisión
de diseño."_

---

## EXP-002 — [[siguiente experimento]]  _(plantilla)_

- **Fecha:**
- **Fase:**
- **Entorno:**

### Hipótesis

### Método

### Resultado

### Interpretación

### Limitaciones / honestidad

### Evidencia
