# Especificación de Demo: Restaurante Autogestionado con Microsoft Fabric Real-Time Intelligence

**Versión**: 1.0  
**Autor**: Nelson López  
**Coautor**: Copilot  
**Estado**: Implementado

---

## 1. Objetivo

Diseñar y ejecutar una demo sencilla en **Microsoft Fabric** que simule un restaurante autogestionado, donde se emiten eventos en vivo y se toman decisiones automáticas con trazabilidad completa.

---

## 2. Alcance

### Dentro del alcance
1. Simulación de operación de restaurante (pedido, cocina, inventario, cierre).
2. Emisión de eventos en vivo durante un turno simulado.
3. Reglas automáticas orientadas a operación de cocina (foco principal).
4. Registro de decisiones y acciones para auditoría de la demo.

### Fuera del alcance
1. Integración con POS real de producción.
2. Optimización avanzada de costos/capacidad.
3. Modelado completo enterprise más allá de una demo mínima.

---

## 3. Operación funcional (visión general)

1. Llega pedido (`order.created`).
2. La cocina emite señales de actividad de estaciones (`kitchen.station.updated`).
3. Inventario refleja consumo (`inventory.level.changed`).
4. Si ETA se degrada, se marca retraso (`order.prep.delayed`).
5. El motor de reglas decide y ejecuta acciones automáticas.
6. Se completa pedido y cobro (`payment.completed`).

### RTI + Activator + Operations Agent

1. **RTI (Eventstream + Eventhouse/KQL)**: ingestar y analizar eventos en vivo.
2. **Fabric Activator**: detectar condiciones simples y objetivas (umbrales, retraso, cola alta, stock crítico) y disparar acciones técnicas.
3. **Operations Agent**: evaluar condiciones complejas con contexto mixto, explicar la recomendación en lenguaje natural y gestionar aprobación/ejecución.

### Modo de operación del agente

Se usará **human-in-the-loop en Teams**:
1. El agente recomienda la acción.
2. El operador aprueba o rechaza.
3. Solo tras aprobación se ejecuta la acción técnica.

### Detalles de implementación

1. Scripts Python locales emiten eventos del restaurante.
2. Eventstream enruta los eventos crudos hacia Eventhouse sin contener la lógica principal de clasificación.
3. Eventhouse/KQL Database actúa como fuente de conocimiento operacional y aplica el modelo de distribución con funciones KQL y update policies.
4. Fabric Activator evalúa reglas simples y dispara acciones automáticas o flujos.
5. Operations Agent usa Eventhouse como knowledge source, propone acción en Teams y solicita aprobación cuando corresponde.
6. Tras aprobación, se dispara la acción (Activator/Power Automate).
7. Se guarda trazabilidad: evento -> condición -> recomendación -> aprobación -> acción -> resultado.

### Tablas transaccionales

1. `raw_restaurant_events`
2. `order_events`
3. `kitchen_events`
4. `inventory_events`
5. `agent_events`
6. `approval_events`
7. `action_events`

`raw_restaurant_events` recibe el flujo crudo desde Eventstream. Las tablas operacionales derivadas guardan el detalle operativo normalizado en tiempo real y alimentan RTI/Eventhouse.

### Tablas de referencia

#### `stations` — Estaciones de cocina

Una **estación de cocina** es una unidad de producción especializada dentro de la cocina del restaurante. Cada estación agrupa un conjunto de equipos del mismo tipo (por ejemplo, varias hornillas de parrilla, varias freidoras) y puede procesar varios pedidos simultáneamente en paralelo. El número máximo de pedidos simultáneos es `max_capacity`.

La cocina del restaurante tiene **4 estaciones**:

| `station_id` | `display_name` | `specialization` | `max_capacity` | `avg_prep_minutes` |
|---|---|---|---|---|
| `grill` | Parrilla | Carnes y pescados a la brasa | 4 | 8 min |
| `fryer` | Freidora | Fritos, patatas, empanados | 4 | 6 min |
| `sauces` | Salsas y guarniciones | Arroces, verduras, salsas | 3 | 3 min |
| `assembly` | Montaje y emplatado | Composición final del plato | 5 | 2 min |

**Relación con los pedidos:**
- Un pedido (`order_events`) se asigna a una estación mediante `station_id`.
- La estación procesa el pedido dentro de su `max_capacity`. La carga activa se calcula contando los pedidos en curso en `order_events` (`order_status = "in_prep"` en los últimos 10 minutos). Si esa cuenta supera la capacidad, los pedidos se acumulan y el tiempo de espera aumenta.
- El tiempo estimado de desatasco se calcula como: `(active_orders - max_capacity) × avg_prep_minutes / max_capacity`, donde `active_orders` es el conteo real desde `order_events`.
- El retraso acumulado en una estación (`delay_minutes` en `order_events`) se usa para detectar riesgo de SLA y desencadenar recomendaciones del Operations Agent.

**Relación con el inventario:**
- Cada estación consume ingredientes del inventario (`inventory_events`). Si un ingrediente cae por debajo de su umbral crítico (`stock_pct < threshold_pct`), la estación asociada puede quedarse sin materia prima, lo que eleva la cola y el riesgo de SLA.

**Campos de la tabla:**

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `station_id` | string | Identificador canónico de la estación |
| `display_name` | string | Nombre legible |
| `specialization` | string | Tipo de platos que prepara |
| `max_capacity` | long | Unidades que puede procesar en paralelo |
| `avg_prep_minutes` | real | Tiempo medio de preparación por unidad |
| `is_active` | bool | Si la estación está operativa |

Se puebla con `.set-or-replace` desde `scripts/eventhouse_schema.py` (datos estáticos, idempotente).

### Modelo operacional en Eventhouse

La demo usa tablas KQL operacionales, no un modelo semántico analítico:

1. `raw_restaurant_events`: landing/staging de eventos crudos recibidos desde Eventstream.
2. `order_events`: ciclo de vida de pedidos.
3. `kitchen_events`: señales de actividad de estaciones (eventos `kitchen.station.updated`). La carga y el estado se derivan de `order_events`.
4. `inventory_events`: consumo, reposición y stock crítico.
5. `agent_events`: recomendaciones del Operations Agent.
6. `approval_events`: aprobaciones/rechazos humanos.
7. `action_events`: acciones disparadas y resultado.
8. `stations` *(referencia)*: definición estática de las 4 estaciones de cocina con capacidad y tiempo medio de preparación.

El reparto desde `raw_restaurant_events` hacia las tablas operacionales se implementa en Eventhouse con funciones KQL y update policies. Eventstream se mantiene como capa de ingesta/enrutamiento y no como lugar principal para reglas de modelado operativo.

Consultas KQL principales:

1. Pedidos en riesgo de SLA por canal y estación.
2. Estaciones con cola alta o saturación sostenida.
3. Ingredientes bajo umbral crítico.
4. Correlación entre retraso, saturación, stock bajo y sentimiento.
5. Historial de recomendaciones, aprobaciones y acciones.

---

## 4. Eventos en vivo de la demo

| Evento | Cuándo se emite | Campos clave |
|---|---|---|
| `order.created` | Al entrar un pedido | `order_id`, `channel`, `items`, `created_at` |
| `kitchen.station.updated` | Señal de actividad en estación | `station_id`, `capacity`, `severity`, `timestamp` |
| `inventory.level.changed` | Consumo/reposición de ingrediente | `ingredient_id`, `stock_pct`, `delta`, `timestamp` |
| `order.prep.delayed` | ETA supera umbral | `order_id`, `delay_minutes`, `station_id`, `timestamp` |
| `customer.sentiment.signal` | Señal simplificada de experiencia | `order_id`, `sentiment`, `reason`, `timestamp` |
| `payment.completed` | Cierre de ciclo | `order_id`, `amount`, `payment_method`, `timestamp` |

---

## 5. Reglas y acciones automáticas

### Regla principal (cocina)
Si `order.prep.delayed` > umbral y la carga activa de la estación (desde `order_events`) supera su capacidad, entonces:
1. **Fabric Activator** detecta la condición.
2. Fabric Activator dispara la repriorización del pedido.
3. Se ejecuta la repriorización y, si aplica, asignación de estación de apoyo.

**Evento de acción**: `action.kitchen.reprioritized`

### Regla compleja asistida por LLM
Si coinciden varias señales a la vez:
1. un pedido con retraso,
2. una estación saturada,
3. un ingrediente en stock bajo,
4. un canal con acumulación de retrasos,
5. y una posible queja del cliente,

entonces el Operations Agent debe:
1. evaluar el contexto completo,
2. comparar opciones de prioridad,
3. explicar el motivo de la recomendación en lenguaje natural,
4. proponer la acción con mejor equilibrio entre SLA, stock y experiencia cliente.

**Ejemplo de salida esperada del agente**:  
"Recomiendo priorizar ORD-1042 porque está en riesgo de incumplir SLA, la parrilla está saturada y el canal delivery acumula retrasos. El stock de pan brioche aún permite completar el pedido sin ruptura, así que la mejor acción es repriorizarlo y mantener el resto de pedidos en cola."

### Reglas secundarias
1. Inventario crítico: si `stock_pct` < umbral, emitir `action.restock.triggered`.
2. Saturación delivery: si se acumulan retrasos por canal, emitir `action.channel.throttled`.
3. Mala experiencia: si hay retraso + sentimiento negativo, emitir `action.compensation.issued`.

### División de responsabilidad
1. **Fabric Activator**: reglas simples y objetivas (umbrales, saturación, stock crítico).
2. **Operations Agent**: regla compleja con contexto mixto y explicación en lenguaje natural.

### Política de autonomía en esta versión

- Las acciones quedan en **modo aprobado por humano**.
- No se habilitan reglas autónomas en esta versión de demo.

---

## 6. Ejemplo operativo A (hora pico, foco cocina)

### Secuencia
1. `00:00` -> `order.created` (ORD-1042, delivery, 4 items).
2. `00:05` -> `kitchen.station.updated` (parrilla, cola=7).
3. `00:12` -> `inventory.level.changed` (pan brioche=15%).
4. `00:18` -> `order.prep.delayed` (ORD-1042, +6 min).
5. Operations Agent recomienda acción en Teams (repriorizar + activar estación de apoyo).
6. Operador aprueba en Teams.
7. Se ejecuta `action.kitchen.reprioritized`.
8. `00:25` -> `kitchen.station.updated` (cola baja a 4).
9. `00:30` -> `payment.completed` (pedido cerrado).

### Resultado esperado
1. Reducción del atraso de ORD-1042.
2. Menor congestión en estación crítica.
3. Evidencia trazable: evento -> regla -> recomendación -> aprobación -> acción -> resultado.

---

## 7. Ejemplo operativo B (inventario crítico)

1. `inventory.level.changed` informa tomate en 8%.
2. Regla de inventario crítico dispara `action.restock.triggered`.
3. Se registra evento de reposición y actualización posterior de stock.

Resultado esperado: continuidad operativa sin bloquear órdenes dependientes.

---

## 8. Evidencias para la demo

1. Timeline de eventos emitidos en vivo.
2. Registro de evaluaciones de reglas (condición, resultado).
3. Registro de acciones automáticas ejecutadas.
4. Resumen final: pedidos a tiempo, atrasos mitigados, acciones realizadas.

---

## 9. Convención de autoría

1. Este archivo (`specs/especificaciones.md`):
   - Autor principal: Nelson López  
   - Coautor: Copilot
2. Resto de archivos técnicos del proyecto:
   - Autor: Copilot (sin coautor adicional)

