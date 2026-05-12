# Especificación de Demo: Restaurante Autogestionado con Microsoft Fabric IQ

**Versión**: 1.0  
**Autor**: Nelson López  
**Coautor**: Copilot  
**Estado**: Para revisión

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
2. Cocina actualiza estado de estaciones y cola (`kitchen.station.updated`).
3. Inventario refleja consumo (`inventory.level.changed`).
4. Si ETA se degrada, se marca retraso (`order.prep.delayed`).
5. El motor de reglas decide y ejecuta acciones automáticas.
6. Se completa pedido y cobro (`payment.completed`).

### RTI + Operations Agent

1. **RTI (Eventstream + Eventhouse/KQL)**: ingestar y analizar eventos en vivo.
2. **Fabric Activator / reglas de ontología**: detectar condiciones operativas (retraso, cola alta, stock crítico) y preparar acciones.
3. **Operations Agent**: interpretar contexto, recomendar acción y gestionar aprobación/ejecución.

### Modo de operación del agente

Se usará **human-in-the-loop en Teams**:
1. El agente recomienda la acción.
2. El operador aprueba o rechaza.
3. Solo tras aprobación se ejecuta la acción técnica.

### Detalles de implementación

1. Scripts Python locales emiten eventos del restaurante.
2. Eventstream enruta y transforma hacia Eventhouse.
3. Ontology modela entidades (Pedido, Estación, Ingrediente) y propiedades.
4. Reglas (Ontology + Activator) detectan condiciones.
5. Operations Agent propone acción en Teams.
6. Tras aprobación, se dispara la acción (Activator/Power Automate).
7. Se guarda trazabilidad: evento -> condición -> recomendación -> aprobación -> acción -> resultado.

### Tablas transaccionales

1. `order_events`
2. `kitchen_events`
3. `inventory_events`
4. `agent_events`
5. `approval_events`
6. `action_events`

Estas tablas guardan el detalle operativo en tiempo real y alimentan RTI/Eventhouse.

### Modelo analítico mínimo

**Hechos**
1. `fact_orders`
2. `fact_kitchen_flow`
3. `fact_inventory_movement`
4. `fact_agent_decisions`
5. `fact_action_execution`

**Dimensiones**
1. `dim_time`
2. `dim_order`
3. `dim_station`
4. `dim_ingredient`
5. `dim_channel`
6. `dim_agent`
7. `dim_action`
8. `dim_approval_status`

**Medidas**
1. `PedidosTotales`
2. `PedidosAtrasados`
3. `AtrasoMedioMinutos`
4. `TiempoMedioCocinaMinutos`
5. `ColaMediaEstacion`
6. `PedidosEnSLA`
7. `AccionesAprobadas`
8. `AccionesEjecutadas`
9. `StockCriticoAlertas`
10. `RecomendacionesAgente`

### Ontología (Fabric IQ)

La ontología se construye sobre el modelo analítico y usa estas entidades:

1. `Pedido`
2. `LineaPedido`
3. `EstacionCocina`
4. `Ingrediente`
5. `Canal`
6. `Turno`
7. `AgenteOperacion`
8. `Recomendacion`
9. `Aprobacion`
10. `Accion`
11. `EventoOperacion`

Relaciones principales:
1. `Pedido` tiene muchas `LineaPedido`.
2. `Pedido` se procesa en `EstacionCocina`.
3. `LineaPedido` consume `Ingrediente`.
4. `Pedido` entra por `Canal`.
5. `AgenteOperacion` genera `Recomendacion`.
6. `Recomendacion` requiere `Aprobacion`.
7. `Aprobacion` habilita `Accion`.
8. `EventoOperacion` dispara reglas.

---

## 4. Eventos en vivo de la demo

| Evento | Cuándo se emite | Campos clave |
|---|---|---|
| `order.created` | Al entrar un pedido | `order_id`, `channel`, `items`, `created_at` |
| `kitchen.station.updated` | Cambio de carga en estación | `station_id`, `queue_size`, `active_orders`, `timestamp` |
| `inventory.level.changed` | Consumo/reposición de ingrediente | `ingredient_id`, `stock_pct`, `delta`, `timestamp` |
| `order.prep.delayed` | ETA supera umbral | `order_id`, `delay_minutes`, `station_id`, `timestamp` |
| `customer.sentiment.signal` | Señal simplificada de experiencia | `order_id`, `sentiment`, `reason`, `timestamp` |
| `payment.completed` | Cierre de ciclo | `order_id`, `amount`, `payment_method`, `timestamp` |

---

## 5. Reglas y acciones automáticas

### Regla principal (cocina)
Si `order.prep.delayed` > umbral y `queue_size` de estación crítica es alta, entonces:
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

